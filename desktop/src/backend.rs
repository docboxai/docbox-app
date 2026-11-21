//! Starting and stopping the Python backend: the one-time `uv sync` of the managed runtime,
//! the backend process with its port report and lifeline, and stopping whole process trees.
//! No UI here; the window reads [`Backend::status`] while [`Backend::boot`] runs on a thread.

use std::ffi::OsString;
use std::fs::{self, File, OpenOptions};
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, ChildStdout, Command, ExitStatus, Stdio};
use std::sync::mpsc::{self, RecvTimeoutError};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

/// The bundle identifier the installed app has always used. Its per-user data folder is
/// named after it, and the Python side (`core/paths.py::APP_IDENTIFIER`) looks for the
/// same folder, so models, history and settings carry over between versions.
pub const APP_IDENTIFIER: &str = "io.github.docboxai.docbox";

// For the backend to report its port, and then again to answer /api/health.
const HEALTH_TIMEOUT: Duration = Duration::from_secs(60);
// Lines of backend.log quoted when the backend doesn't come up.
const LOG_TAIL_LINES: usize = 15;
// How long a process group gets to exit on SIGTERM before it's SIGKILLed.
#[cfg(not(windows))]
const STOP_GRACE: Duration = Duration::from_secs(3);

#[derive(Clone, Debug, PartialEq)]
pub enum BootState {
    Starting,
    Ready,
    Failed,
}

#[derive(Clone, Debug)]
pub struct BootStatus {
    pub state: BootState,
    pub message: String,
    pub progress: f32,
    pub base_url: Option<String>,
    pub log_path: Option<PathBuf>,
}

impl Default for BootStatus {
    fn default() -> Self {
        Self {
            state: BootState::Starting,
            message: "Starting".into(),
            progress: 0.0,
            base_url: None,
            log_path: None,
        }
    }
}

#[derive(Default)]
struct Processes {
    child: Option<Child>,
    // The backend's stdin, never written to. The backend shuts down when it closes, which
    // happens when this is dropped and also when the app dies without cleaning up (crash,
    // force-quit): the OS closes the pipe either way. Drop it only to stop it.
    lifeline: Option<ChildStdin>,
    // The bootstrap `uv sync`, so closing the window mid-setup doesn't orphan it.
    setup_pid: Option<u32>,
}

/// The backend's lifecycle, shared between the boot thread and the window.
#[derive(Clone, Default)]
pub struct Backend {
    status: Arc<Mutex<BootStatus>>,
    processes: Arc<Mutex<Processes>>,
}

/// Where everything lives for this run. Release builds use a private, app-managed Python
/// env under the per-user data dir, built from the backend source + `uv.lock` bundled as
/// resources and the bundled `uv`. Debug builds use the repo checkout's own `.venv`,
/// synced by the developer.
pub struct Layout {
    managed: bool,
    project_dir: PathBuf,
    python: PathBuf,
    uv: Option<PathBuf>,
    pub data_dir: PathBuf,
    runtime_dir: PathBuf,
    pub logs_dir: PathBuf,
}

fn venv_python(venv: &Path) -> PathBuf {
    if cfg!(windows) {
        venv.join("Scripts").join("python.exe")
    } else {
        venv.join("bin").join("python")
    }
}

/// The per-user folder the installed app keeps its data in: %LOCALAPPDATA%\<id> on
/// Windows, ~/Library/Application Support/<id> on macOS, $XDG_DATA_HOME/<id> on Linux.
/// `DOCBOX_DATA_DIR` overrides it (test runs, a second copy side by side).
pub fn data_dir() -> Result<PathBuf, String> {
    if let Some(dir) = std::env::var_os("DOCBOX_DATA_DIR").filter(|d| !d.is_empty()) {
        return Ok(PathBuf::from(dir));
    }
    dirs::data_local_dir()
        .map(|d| d.join(APP_IDENTIFIER))
        .ok_or_else(|| "no per-user data folder on this system".to_string())
}

/// Where an installed build keeps the bundled backend (`backend/`): next to the program on
/// Windows, `Contents/Resources` in the macOS app, `lib/DocBox` beside `bin/` on Linux
/// (the .deb, .rpm and AppImage). `DOCBOX_RESOURCE_DIR` overrides it.
fn resource_dir(exe_dir: &Path) -> Result<PathBuf, String> {
    if let Some(dir) = std::env::var_os("DOCBOX_RESOURCE_DIR").filter(|d| !d.is_empty()) {
        return Ok(PathBuf::from(dir));
    }
    let candidates = [
        exe_dir.to_path_buf(),
        exe_dir.join("../Resources"),
        exe_dir.join("../lib/DocBox"),
        exe_dir.join("../lib/docbox"),
    ];
    candidates
        .iter()
        .find(|dir| dir.join("backend").join("uv.lock").is_file())
        .cloned()
        .ok_or_else(|| format!("DocBox's backend files aren't next to {}", exe_dir.display()))
}

pub fn layout() -> Result<Layout, String> {
    let data_dir = data_dir()?;
    let runtime_dir = data_dir.join("runtime");
    let logs_dir = data_dir.join("logs");

    if cfg!(debug_assertions) {
        // desktop/'s parent is the repo root (contains pyproject.toml).
        let project_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .ok_or("desktop/ has no parent directory")?
            .to_path_buf();
        return Ok(Layout {
            managed: false,
            python: venv_python(&project_dir.join(".venv")),
            project_dir,
            uv: None,
            data_dir,
            runtime_dir,
            logs_dir,
        });
    }

    let exe_dir = std::env::current_exe()
        .map_err(|e| e.to_string())?
        .parent()
        .ok_or("the program has no parent directory")?
        .to_path_buf();
    let project_dir = resource_dir(&exe_dir)?.join("backend");
    let uv = exe_dir.join(if cfg!(windows) { "uv.exe" } else { "uv" });
    Ok(Layout {
        managed: true,
        python: venv_python(&runtime_dir.join(".venv")),
        project_dir,
        uv: Some(uv),
        data_dir,
        runtime_dir,
        logs_dir,
    })
}

pub fn no_window(cmd: &mut Command) -> &mut Command {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        // CREATE_NO_WINDOW: release builds have no console, so children would pop one.
        cmd.creation_flags(0x0800_0000);
    }
    cmd
}

/// On Unix, start the child as the leader of a new process group, so `stop_child` and
/// `kill_tree` reach everything it starts in turn (engine installs, benchmark workers).
fn own_process_group(cmd: &mut Command) -> &mut Command {
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        cmd.process_group(0);
    }
    cmd
}

/// The AppImage's launcher points PYTHONHOME, PYTHONPATH and LD_LIBRARY_PATH into its own
/// mounted image. Inherited, they send uv's Python looking for its standard library in
/// there ("No module named 'encodings'"), so child processes get them back without the
/// AppImage's parts. Other launches have no APPDIR and are left alone.
pub fn outside_appimage(cmd: &mut Command) -> &mut Command {
    let Some(appdir) = std::env::var_os("APPDIR") else {
        return cmd;
    };
    cmd.env_remove("PYTHONHOME")
        .env_remove("PYTHONPATH")
        .env_remove("PYTHONDONTWRITEBYTECODE");
    if let Some(paths) = std::env::var_os("LD_LIBRARY_PATH") {
        let kept: Vec<PathBuf> = std::env::split_paths(&paths)
            .filter(|p| !p.as_os_str().is_empty() && !p.starts_with(&appdir))
            .collect();
        match std::env::join_paths(kept) {
            Ok(joined) if !joined.is_empty() => cmd.env("LD_LIBRARY_PATH", joined),
            _ => cmd.env_remove("LD_LIBRARY_PATH"),
        };
    }
    cmd
}

/// uv env vars for every uv the app runs: the bootstrap sync, and the backend's own
/// on-demand `uv sync` (engine installs), which gets them passed down.
/// - UV_SYSTEM_CERTS: verify HTTPS against the OS trust store, so downloads work behind
///   proxies that inspect HTTPS with a CA IT installed there (Python does the same through
///   `core/tls.py`).
/// - Managed builds pin the env, interpreter and cache to the app's data dir, so both
///   syncs target the same environment.
fn uv_env(l: &Layout) -> Vec<(&'static str, OsString)> {
    let mut env = vec![("UV_SYSTEM_CERTS", OsString::from("1"))];
    if l.managed {
        env.extend([
            ("UV_PROJECT_ENVIRONMENT", l.runtime_dir.join(".venv").into_os_string()),
            ("UV_PYTHON_INSTALL_DIR", l.runtime_dir.join("python").into_os_string()),
            ("UV_CACHE_DIR", l.runtime_dir.join("uv-cache").into_os_string()),
        ]);
    }
    env
}

fn read_state(l: &Layout) -> serde_json::Value {
    fs::read_to_string(l.runtime_dir.join("state.json"))
        .ok()
        .and_then(|t| serde_json::from_str(&t).ok())
        .unwrap_or_else(|| serde_json::json!({}))
}

fn write_state(l: &Layout, state: &serde_json::Value) -> Result<(), String> {
    let path = l.runtime_dir.join("state.json");
    let tmp = path.with_extension("tmp");
    fs::write(&tmp, serde_json::to_string_pretty(state).unwrap()).map_err(|e| e.to_string())?;
    fs::rename(&tmp, &path).map_err(|e| e.to_string())
}

/// The error for a bootstrap `uv sync` that failed: how uv ended (an exit status, or on
/// Unix the signal, e.g. "signal: 11 (SIGSEGV) (core dumped)"), then the last lines it
/// printed. A crash prints nothing, so then how it ended is all there is to show.
fn setup_failure(status: ExitStatus, tail: &[String]) -> String {
    if tail.is_empty() {
        format!("Setup failed: uv ended with {status} before printing anything.")
    } else {
        format!("Setup failed: uv ended with {status}.\n{}", tail.join("\n"))
    }
}

/// The line the backend prints first when started with `--port 0`:
/// `{"docbox_backend": {"port": N}}`.
fn parse_port_report(line: &str) -> Option<u16> {
    let report: serde_json::Value = serde_json::from_str(line.trim()).ok()?;
    let port = report.get("docbox_backend")?.get("port")?.as_u64()?;
    u16::try_from(port).ok().filter(|port| *port != 0)
}

/// Wait for the backend's port report on its stdout. Anything else it prints there goes
/// to the log, and the pipe is read to the end so the backend can never block on it.
fn port_report(stdout: ChildStdout, mut log: File) -> mpsc::Receiver<u16> {
    let (tx, rx) = mpsc::channel();
    std::thread::spawn(move || {
        let mut reported = false;
        for line in BufReader::new(stdout).lines().map_while(Result::ok) {
            if !reported {
                if let Some(port) = parse_port_report(&line) {
                    reported = true;
                    let _ = tx.send(port);
                    continue;
                }
            }
            let _ = writeln!(log, "{line}");
        }
    });
    rx
}

/// The end of backend.log, for errors about a backend that didn't come up.
fn log_tail(path: &Path) -> String {
    let text = fs::read(path).map(|b| String::from_utf8_lossy(&b).into_owned()).unwrap_or_default();
    let lines: Vec<&str> = text.lines().collect();
    let tail = lines[lines.len().saturating_sub(LOG_TAIL_LINES)..].join("\n");
    if tail.trim().is_empty() {
        return String::new();
    }
    format!("\n\nThe end of {}:\n{tail}", path.display())
}

/// Send `signal` to the process group `pgid` leads (see `own_process_group`).
#[cfg(not(windows))]
fn signal_group(pgid: u32, signal: libc::c_int) -> bool {
    // kill(-1) would signal every process we may signal, and kill(-0) our own group.
    if pgid <= 1 {
        return false;
    }
    // SAFETY: kill(2) only reads its arguments.
    unsafe { libc::kill(-(pgid as libc::pid_t), signal) == 0 }
}

// A plain `child.kill()` only terminates that one process. That's not enough on Windows: a
// uv-managed venv's `python.exe` is itself a trampoline stub that spawns the real CPython
// interpreter as a *further* child, so the process we hold a `Child` for isn't the one
// actually doing OCR/model-download work. `taskkill /T` kills the whole process tree rooted
// at that PID, which reaches the real interpreter regardless of how many stub layers are in
// between. On Unix the children run in their own process group, which covers everything
// they start (unless something leaves the group on purpose).

/// Stop a child we spawned and everything it started, and reap it.
fn stop_child(child: &mut Child) {
    #[cfg(windows)]
    {
        kill_tree(child.id());
    }
    #[cfg(not(windows))]
    {
        let pgid = child.id();
        signal_group(pgid, libc::SIGTERM);
        let deadline = Instant::now() + STOP_GRACE;
        while Instant::now() < deadline && matches!(child.try_wait(), Ok(None)) {
            std::thread::sleep(Duration::from_millis(50));
        }
        // The child if it ignored SIGTERM, and anything it started that's still running.
        signal_group(pgid, libc::SIGKILL);
    }
    let _ = child.wait();
}

/// Stop a process tree we only know the PID of (the bootstrap `uv`, whose `Child` its own
/// thread holds and reaps).
fn kill_tree(pid: u32) {
    #[cfg(windows)]
    {
        let mut cmd = Command::new("taskkill");
        cmd.args(["/PID", &pid.to_string(), "/T", "/F"]);
        let _ = no_window(&mut cmd).status();
    }
    #[cfg(not(windows))]
    {
        signal_group(pid, libc::SIGTERM);
        let deadline = Instant::now() + STOP_GRACE;
        // Signal 0 only checks that the group still has a member.
        while Instant::now() < deadline && signal_group(pid, 0) {
            std::thread::sleep(Duration::from_millis(50));
        }
        signal_group(pid, libc::SIGKILL);
    }
}

fn wait_until_ready(base_url: &str) -> Result<(), String> {
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(5))
        .build()
        .map_err(|e| e.to_string())?;
    let health_url = format!("{base_url}/api/health");
    let deadline = Instant::now() + HEALTH_TIMEOUT;
    while Instant::now() < deadline {
        if let Ok(resp) = client.get(&health_url).send() {
            if resp.status().is_success() {
                return Ok(());
            }
        }
        std::thread::sleep(Duration::from_millis(250));
    }
    Err(format!("The backend didn't respond within {HEALTH_TIMEOUT:?}"))
}

// The window's controls reach it (Restart DocBox, quitting) through the app's globals.
impl gpui_kit::Global for Backend {}

impl Backend {
    pub fn status(&self) -> BootStatus {
        self.status.lock().unwrap().clone()
    }

    fn set_status(&self, state: BootState, message: &str, progress: f32) {
        let mut s = self.status.lock().unwrap();
        s.state = state;
        s.message = message.to_string();
        s.progress = progress;
    }

    /// Start (or, after a failure, restart) the backend on a thread of its own. The window
    /// shows right away, on the setup screen, and polls [`Backend::status`].
    pub fn start(&self) {
        self.set_status(BootState::Starting, "Starting", 0.0);
        let this = self.clone();
        std::thread::spawn(move || {
            if let Err(err) = this.boot() {
                eprintln!("[docbox] {err}");
                this.set_status(BootState::Failed, &err, 0.0);
            }
        });
    }

    /// Try again after a failed start.
    pub fn retry(&self) {
        if self.status().state != BootState::Failed {
            return;
        }
        self.stop_backend();
        self.start();
    }

    /// Create/refresh the managed env when it's missing, when this app version ships a
    /// different `uv.lock` than the one last installed (an update), or when the backend left
    /// a removal for startup (an engine that was in use when the user uninstalled it).
    /// Previously installed engine extras are re-synced, so updates keep the user's engines.
    fn ensure_runtime(&self, l: &Layout) -> Result<(), String> {
        if !l.managed {
            if !l.python.exists() {
                return Err(format!(
                    "Dev virtualenv not found at {:?}. Run `uv sync --extra paddle` in {:?}.",
                    l.python, l.project_dir
                ));
            }
            return Ok(());
        }

        fs::create_dir_all(&l.runtime_dir).map_err(|e| e.to_string())?;
        let bundled_lock = fs::read(l.project_dir.join("uv.lock")).map_err(|e| e.to_string())?;
        let installed_lock_path = l.runtime_dir.join("uv.lock.installed");
        let mut state = read_state(l);
        let resync_pending = state["resync_pending"].as_bool().unwrap_or(false);
        let lock_unchanged =
            fs::read(&installed_lock_path).ok().as_deref() == Some(&bundled_lock[..]);
        if l.python.exists() && lock_unchanged && !resync_pending {
            return Ok(());
        }

        let uv = l.uv.as_ref().ok_or("no bundled uv")?;
        let mut cmd = Command::new(uv);
        outside_appimage(&mut cmd);
        own_process_group(&mut cmd);
        cmd.args(["sync", "--frozen", "--no-dev", "--no-install-project", "--project"])
            .arg(&l.project_dir)
            .env("UV_PYTHON_PREFERENCE", "only-managed")
            .envs(uv_env(l))
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        let extras: Vec<String> = state["extras"]
            .as_array()
            .map(|a| a.iter().filter_map(|v| v.as_str().map(String::from)).collect())
            .unwrap_or_default();
        for extra in &extras {
            cmd.args(["--extra", extra]);
        }
        let first_run = !l.python.exists();
        self.set_status(
            BootState::Starting,
            if first_run { "Setting up DocBox (one-time)" } else { "Updating DocBox's packages" },
            1.0,
        );

        // uv writes progress to stderr; stdout is quiet. Mirror both to the setup log.
        let mut log = File::create(l.logs_dir.join("setup.log")).map_err(|e| e.to_string())?;
        let mut child = match no_window(&mut cmd).spawn() {
            Ok(child) => child,
            Err(e) => {
                let err = format!("couldn't run bundled uv at {uv:?}: {e}");
                let _ = writeln!(log, "[docbox] {err}");
                return Err(err);
            }
        };
        self.processes.lock().unwrap().setup_pid = Some(child.id());

        let stderr = child.stderr.take().unwrap();
        let mut steps = 0i32;
        let mut tail: Vec<String> = Vec::new();
        for line in BufReader::new(stderr).lines().map_while(Result::ok) {
            let _ = writeln!(log, "{line}");
            let trimmed = line.trim();
            if trimmed.is_empty() {
                continue;
            }
            steps += 1;
            tail.push(trimmed.to_string());
            if tail.len() > 20 {
                tail.remove(0);
            }
            let pct = (100.0 * (1.0 - 0.95f32.powi(steps))).min(95.0);
            self.set_status(BootState::Starting, trimmed, pct);
        }
        let status = child.wait().map_err(|e| e.to_string())?;
        self.processes.lock().unwrap().setup_pid = None;
        if !status.success() {
            // In the log too: uv may have printed nothing (a crash), leaving it empty.
            let _ = writeln!(log, "[docbox] uv ended with {status}");
            return Err(setup_failure(status, &tail));
        }

        fs::write(&installed_lock_path, &bundled_lock).map_err(|e| e.to_string())?;
        state["resync_pending"] = serde_json::Value::Bool(false);
        write_state(l, &state)
    }

    /// Start the backend on a port the OS picks (`--port 0`; it reports the port on
    /// stdout). Returns a second handle on backend.log for `port_report` to write to.
    fn spawn_backend(l: &Layout, log_path: &Path) -> Result<(Child, File), String> {
        let log = File::create(log_path).map_err(|e| e.to_string())?;
        let log_err = log.try_clone().map_err(|e| e.to_string())?;
        let mut cmd = Command::new(&l.python);
        outside_appimage(&mut cmd);
        own_process_group(&mut cmd);
        cmd.args(["-m", "docbox.backend.main", "--host", "127.0.0.1", "--port", "0"])
            // The backend exits when its stdin closes: see `Processes::lifeline`.
            .arg("--exit-on-stdin-close")
            .current_dir(&l.project_dir)
            .env("DOCBOX_DATA_DIR", &l.data_dir)
            .env("DOCBOX_PROJECT_DIR", &l.project_dir)
            .envs(uv_env(l))
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::from(log_err));
        if l.managed {
            // The project isn't installed into the managed env (its source is read-only in
            // the install dir), so put the bundled source on the import path instead.
            // Bytecode for that source goes in the data dir too: written next to it, the
            // .pyc files are left in the install dir after the uninstaller has run.
            cmd.env("PYTHONPATH", l.project_dir.join("src"))
                .env("PYTHONPYCACHEPREFIX", l.runtime_dir.join("pycache"))
                .env("DOCBOX_RUNTIME_MODE", "managed")
                .env("UV_PYTHON_PREFERENCE", "only-managed");
            if let Some(uv) = &l.uv {
                cmd.env("DOCBOX_UV", uv);
            }
        }
        let child = no_window(&mut cmd)
            .spawn()
            .map_err(|e| format!("failed to start the backend ({:?}): {e}", l.python))?;
        Ok((child, log))
    }

    fn boot(&self) -> Result<(), String> {
        let l = layout()?;
        fs::create_dir_all(&l.logs_dir).map_err(|e| e.to_string())?;
        self.status.lock().unwrap().log_path = Some(l.logs_dir.clone());

        self.ensure_runtime(&l)?;

        self.set_status(BootState::Starting, "Starting the OCR backend", 97.0);
        let log_path = l.logs_dir.join("backend.log");
        let (mut child, log) = Self::spawn_backend(&l, &log_path)?;
        let stdout = child.stdout.take().ok_or("the backend has no stdout pipe")?;
        {
            let mut p = self.processes.lock().unwrap();
            p.lifeline = child.stdin.take();
            p.child = Some(child);
        }

        let port = match port_report(stdout, log).recv_timeout(HEALTH_TIMEOUT) {
            Ok(port) => port,
            Err(err) => {
                // If it ended by itself, say how: a crash leaves nothing of its own in the log.
                let ended = self
                    .processes
                    .lock()
                    .unwrap()
                    .child
                    .as_mut()
                    .and_then(|child| child.try_wait().ok().flatten());
                self.stop_backend();
                let why = match (ended, err) {
                    (Some(status), _) => format!("it ended with {status} before reporting its port"),
                    (None, RecvTimeoutError::Timeout) => {
                        format!("it didn't report its port within {HEALTH_TIMEOUT:?}")
                    }
                    (None, RecvTimeoutError::Disconnected) => {
                        "it stopped before reporting its port".into()
                    }
                };
                let tail = log_tail(&log_path);
                if let Ok(mut log) = OpenOptions::new().append(true).open(&log_path) {
                    let _ = writeln!(log, "[docbox] The backend didn't start: {why}.");
                }
                return Err(format!("The backend didn't start: {why}.{tail}"));
            }
        };
        let base_url = format!("http://127.0.0.1:{port}");
        wait_until_ready(&base_url).map_err(|e| format!("{e}{}", log_tail(&log_path)))?;
        let mut s = self.status.lock().unwrap();
        s.state = BootState::Ready;
        s.message = "ready".into();
        s.progress = 100.0;
        s.base_url = Some(base_url);
        Ok(())
    }

    /// Stop the backend and everything it started: close its lifeline (it starts shutting
    /// down by itself), then stop the process tree.
    fn stop_backend(&self) {
        let child = {
            let mut p = self.processes.lock().unwrap();
            drop(p.lifeline.take());
            p.child.take()
        };
        if let Some(mut child) = child {
            stop_child(&mut child);
        }
    }

    /// Stop the bootstrap `uv` and the backend (whole process trees). Every way the app
    /// ends goes through here: closing the window, quitting, a restart, an update. If the
    /// app dies without getting here, the backend still exits: its lifeline closes with it.
    pub fn shutdown(&self) {
        let setup_pid = self.processes.lock().unwrap().setup_pid.take();
        if let Some(pid) = setup_pid {
            kill_tree(pid);
        }
        self.stop_backend();
    }
}

#[cfg(test)]
mod tests {
    use super::{parse_port_report, setup_failure};

    #[test]
    fn reads_the_backends_port_report() {
        assert_eq!(parse_port_report("{\"docbox_backend\": {\"port\": 51234}}\n"), Some(51234));
        // Other output before the report, and reports that can't be a listening port.
        assert_eq!(parse_port_report("INFO:     Started server process [42]"), None);
        assert_eq!(parse_port_report("{\"docbox_backend\": {\"port\": 0}}"), None);
        assert_eq!(parse_port_report("{\"docbox_backend\": {\"port\": 70000}}"), None);
        assert_eq!(parse_port_report("{\"port\": 51234}"), None);
    }

    #[cfg(unix)]
    #[test]
    fn a_failed_setup_says_how_uv_ended() {
        use std::os::unix::process::ExitStatusExt;
        use std::process::ExitStatus;
        // Raw wait statuses: a segfault with a core dump (signal 11 | 0x80), and exit code 2.
        let crashed = setup_failure(ExitStatus::from_raw(11 | 0x80), &[]);
        assert!(crashed.contains("SIGSEGV"), "{crashed}");
        assert!(crashed.contains("before printing anything"), "{crashed}");
        let failed = setup_failure(ExitStatus::from_raw(2 << 8), &["error: no network".into()]);
        assert!(failed.contains("exit status: 2"), "{failed}");
        assert!(failed.ends_with("\nerror: no network"), "{failed}");
    }
}
