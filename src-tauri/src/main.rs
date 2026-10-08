// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::fs::{self, File};
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, ChildStdout, Command, Stdio};
use std::sync::mpsc::{self, RecvTimeoutError};
use std::sync::Mutex;
use std::time::Duration;

use serde::Serialize;
use tauri::{AppHandle, Manager, State};

// For the backend to report its port, and then again to answer /api/health.
const HEALTH_TIMEOUT: Duration = Duration::from_secs(60);
// Lines of backend.log quoted when the backend doesn't come up.
const LOG_TAIL_LINES: usize = 15;
// How long a process group gets to exit on SIGTERM before it's SIGKILLed.
#[cfg(not(windows))]
const STOP_GRACE: Duration = Duration::from_secs(3);

#[derive(Clone, Default, Serialize)]
struct BootStatus {
    // "starting" | "ready" | "failed"
    state: String,
    message: String,
    progress: f32,
    base_url: Option<String>,
    log_path: Option<String>,
}

#[derive(Default)]
struct Backend {
    status: Mutex<BootStatus>,
    child: Mutex<Option<Child>>,
    // The backend's stdin, never written to. The backend shuts down when it closes, which
    // happens when this is dropped and also when the shell dies without cleaning up
    // (crash, force-quit): the OS closes the pipe either way. Drop it only to stop it.
    lifeline: Mutex<Option<ChildStdin>>,
    // The bootstrap `uv sync`, so closing the window mid-setup doesn't orphan it.
    setup_pid: Mutex<Option<u32>>,
}

/// Where everything lives for this run. Release builds use a private, app-managed
/// Python env under the per-user data dir, built from the backend source + `uv.lock`
/// bundled as resources and the `uv` sidecar. Dev builds (`cargo tauri dev`) use the
/// repo checkout's own `.venv`, synced by the developer.
struct Layout {
    managed: bool,
    project_dir: PathBuf,
    python: PathBuf,
    uv: Option<PathBuf>,
    data_dir: PathBuf,
    runtime_dir: PathBuf,
    logs_dir: PathBuf,
}

fn venv_python(venv: &Path) -> PathBuf {
    if cfg!(windows) {
        venv.join("Scripts").join("python.exe")
    } else {
        venv.join("bin").join("python")
    }
}

fn layout(app: &AppHandle) -> Result<Layout, String> {
    let data_dir = app
        .path()
        .app_local_data_dir()
        .map_err(|e| format!("no app data dir: {e}"))?;
    let runtime_dir = data_dir.join("runtime");
    let logs_dir = data_dir.join("logs");

    if cfg!(debug_assertions) {
        // src-tauri's parent is the repo root (contains pyproject.toml).
        let project_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .ok_or("src-tauri has no parent directory")?
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

    let project_dir = app
        .path()
        .resource_dir()
        .map_err(|e| format!("no resource dir: {e}"))?
        .join("backend");
    let exe_dir = std::env::current_exe()
        .map_err(|e| e.to_string())?
        .parent()
        .ok_or("executable has no parent directory")?
        .to_path_buf();
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

fn set_status(app: &AppHandle, state: &str, message: &str, progress: f32) {
    let backend = app.state::<Backend>();
    let mut s = backend.status.lock().unwrap();
    s.state = state.to_string();
    s.message = message.to_string();
    s.progress = progress;
}

fn no_window(cmd: &mut Command) -> &mut Command {
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
fn outside_appimage(cmd: &mut Command) -> &mut Command {
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

/// uv env vars that pin the managed env, interpreter and cache to the app's data dir.
/// Passed to the backend too, so its own on-demand `uv sync` (engine installs) targets
/// the same environment.
fn uv_env(l: &Layout) -> Vec<(&'static str, PathBuf)> {
    if !l.managed {
        return vec![];
    }
    vec![
        ("UV_PROJECT_ENVIRONMENT", l.runtime_dir.join(".venv")),
        ("UV_PYTHON_INSTALL_DIR", l.runtime_dir.join("python")),
        ("UV_CACHE_DIR", l.runtime_dir.join("uv-cache")),
    ]
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

/// Create/refresh the managed env when it's missing, when this app version ships a
/// different `uv.lock` than the one last installed (an update), or when the backend
/// left a removal for startup (an engine that was in use when the user uninstalled it).
/// Previously installed engine extras are re-synced, so updates keep the user's engines.
fn ensure_runtime(app: &AppHandle, l: &Layout) -> Result<(), String> {
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
    let lock_unchanged = fs::read(&installed_lock_path).ok().as_deref() == Some(&bundled_lock[..]);
    if l.python.exists() && lock_unchanged && !resync_pending {
        return Ok(());
    }

    let uv = l.uv.as_ref().ok_or("no uv sidecar")?;
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
    set_status(
        app,
        "starting",
        if first_run { "Setting up DocBox (one-time)" } else { "Updating DocBox's packages" },
        1.0,
    );

    let mut child = no_window(&mut cmd)
        .spawn()
        .map_err(|e| format!("couldn't run bundled uv at {uv:?}: {e}"))?;
    *app.state::<Backend>().setup_pid.lock().unwrap() = Some(child.id());

    // uv writes progress to stderr; stdout is quiet. Mirror both to the setup log.
    let mut log = File::create(l.logs_dir.join("setup.log")).map_err(|e| e.to_string())?;
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
        set_status(app, "starting", trimmed, pct);
    }
    let status = child.wait().map_err(|e| e.to_string())?;
    *app.state::<Backend>().setup_pid.lock().unwrap() = None;
    if !status.success() {
        return Err(format!("Setup failed:\n{}", tail.join("\n")));
    }

    fs::write(&installed_lock_path, &bundled_lock).map_err(|e| e.to_string())?;
    state["resync_pending"] = serde_json::Value::Bool(false);
    write_state(l, &state)
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

/// Start the backend on a port the OS picks (`--port 0`; it reports the port on stdout).
/// Returns a second handle on backend.log for `port_report` to write to.
fn spawn_backend(l: &Layout, log_path: &Path) -> Result<(Child, File), String> {
    let log = File::create(log_path).map_err(|e| e.to_string())?;
    let log_err = log.try_clone().map_err(|e| e.to_string())?;
    let mut cmd = Command::new(&l.python);
    outside_appimage(&mut cmd);
    own_process_group(&mut cmd);
    cmd.args(["-m", "docbox.backend.main", "--host", "127.0.0.1", "--port", "0"])
        // The backend exits when its stdin closes: see `Backend::lifeline`.
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
        cmd.env("PYTHONPATH", l.project_dir.join("src"))
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

// A plain `child.kill()` only terminates that one process. That's not enough on
// Windows: a uv-managed venv's `python.exe` is itself a trampoline stub that spawns the
// real CPython interpreter as a *further* child, so the process we hold a `Child` for
// isn't the one actually doing OCR/model-download work. `taskkill /T` kills the whole
// process tree rooted at that PID, which reaches the real interpreter regardless of how
// many stub layers are in between. On Unix the children run in their own process group,
// which covers everything they start (unless something leaves the group on purpose).

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
        let deadline = std::time::Instant::now() + STOP_GRACE;
        while std::time::Instant::now() < deadline && matches!(child.try_wait(), Ok(None)) {
            std::thread::sleep(Duration::from_millis(50));
        }
        // The child if it ignored SIGTERM, and anything it started that's still running.
        signal_group(pgid, libc::SIGKILL);
    }
    let _ = child.wait();
}

/// Stop a process tree we only know the PID of (the bootstrap `uv`, whose `Child` its
/// own thread holds and reaps).
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
        let deadline = std::time::Instant::now() + STOP_GRACE;
        // Signal 0 only checks that the group still has a member.
        while std::time::Instant::now() < deadline && signal_group(pid, 0) {
            std::thread::sleep(Duration::from_millis(50));
        }
        signal_group(pid, libc::SIGKILL);
    }
}

async fn wait_until_ready(base_url: &str) -> Result<(), String> {
    let client = reqwest::Client::new();
    let health_url = format!("{base_url}/api/health");
    let deadline = tokio::time::Instant::now() + HEALTH_TIMEOUT;
    while tokio::time::Instant::now() < deadline {
        if let Ok(resp) = client.get(&health_url).send().await {
            if resp.status().is_success() {
                return Ok(());
            }
        }
        tokio::time::sleep(Duration::from_millis(250)).await;
    }
    Err(format!("The backend didn't respond within {HEALTH_TIMEOUT:?}"))
}

fn boot(app: &AppHandle) -> Result<(), String> {
    let l = layout(app)?;
    fs::create_dir_all(&l.logs_dir).map_err(|e| e.to_string())?;
    app.state::<Backend>().status.lock().unwrap().log_path =
        Some(l.logs_dir.to_string_lossy().into_owned());

    ensure_runtime(app, &l)?;

    set_status(app, "starting", "Starting the OCR backend", 97.0);
    let log_path = l.logs_dir.join("backend.log");
    let (mut child, log) = spawn_backend(&l, &log_path)?;
    let stdout = child.stdout.take().ok_or("the backend has no stdout pipe")?;
    let backend = app.state::<Backend>();
    *backend.lifeline.lock().unwrap() = child.stdin.take();
    *backend.child.lock().unwrap() = Some(child);

    let port = match port_report(stdout, log).recv_timeout(HEALTH_TIMEOUT) {
        Ok(port) => port,
        Err(err) => {
            stop_backend(&backend);
            let why = match err {
                RecvTimeoutError::Timeout => {
                    format!("it didn't report its port within {HEALTH_TIMEOUT:?}")
                }
                RecvTimeoutError::Disconnected => "it stopped before reporting its port".into(),
            };
            return Err(format!("The backend didn't start: {why}.{}", log_tail(&log_path)));
        }
    };
    let base_url = format!("http://127.0.0.1:{port}");
    tauri::async_runtime::block_on(wait_until_ready(&base_url))
        .map_err(|e| format!("{e}{}", log_tail(&log_path)))?;
    let mut s = backend.status.lock().unwrap();
    s.state = "ready".into();
    s.message = "ready".into();
    s.progress = 100.0;
    s.base_url = Some(base_url);
    Ok(())
}

fn start_boot(app: AppHandle) {
    set_status(&app, "starting", "Starting", 0.0);
    tauri::async_runtime::spawn_blocking(move || {
        if let Err(err) = boot(&app) {
            eprintln!("[docbox] {err}");
            set_status(&app, "failed", &err, 0.0);
        }
    });
}

#[tauri::command]
fn backend_status(state: State<Backend>) -> BootStatus {
    state.status.lock().unwrap().clone()
}

#[tauri::command]
fn backend_base_url(state: State<Backend>) -> Result<String, String> {
    state
        .status
        .lock()
        .unwrap()
        .base_url
        .clone()
        .ok_or_else(|| "backend not ready yet".to_string())
}

/// Stop the backend and everything it started: close its lifeline (it starts shutting
/// down by itself), then stop the process tree.
fn stop_backend(state: &Backend) {
    drop(state.lifeline.lock().unwrap().take());
    let child = state.child.lock().unwrap().take();
    if let Some(mut child) = child {
        stop_child(&mut child);
    }
}

/// Stop the bootstrap `uv` and the backend (whole process trees). Every way the app can
/// end goes through here: window close, the updater handing off to the installer on
/// Windows, an in-app restart after an update, and normal exit. If the shell dies
/// without getting here, the backend still exits: its lifeline closes with the shell.
fn shutdown_backend(app: &AppHandle) {
    let state = app.state::<Backend>();
    let setup_pid = state.setup_pid.lock().unwrap().take();
    if let Some(pid) = setup_pid {
        kill_tree(pid);
    }
    stop_backend(&state);
}

#[tauri::command]
fn prepare_restart(app: AppHandle) {
    shutdown_backend(&app);
}

#[tauri::command]
fn retry_backend(app: AppHandle, state: State<Backend>) {
    if state.status.lock().unwrap().state != "failed" {
        return;
    }
    stop_backend(&state);
    start_boot(app);
}

fn main() {
    let app = tauri::Builder::default()
        // Updates are driven from the frontend, which calls `prepare_restart` right
        // before installing (on Windows the updater exits the app to run the installer).
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        // Opens a few fixed web pages in the default browser (the capability lists them):
        // the releases page when an in-app update can't be used, and where to get an
        // NVIDIA key, Ollama or Tesseract.
        .plugin(tauri_plugin_opener::init())
        .manage(Backend::default())
        .setup(|app| {
            // The window shows right away (on the setup screen); the backend comes up
            // in the background and the frontend polls `backend_status`.
            start_boot(app.handle().clone());
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            backend_status,
            backend_base_url,
            retry_backend,
            prepare_restart
        ])
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                shutdown_backend(window.app_handle());
                // Closing the window doesn't reliably end the app process on its own —
                // `AppHandle::exit` posts an exit request through Tauri's event loop,
                // but that request can be dropped depending on exactly how the close
                // was triggered, leaving a windowless docbox.exe running indefinitely.
                // The backend is already torn down above, so terminate directly.
                std::process::exit(0);
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(|handle, event| {
        if let tauri::RunEvent::Exit = event {
            shutdown_backend(handle);
        }
    });
}

#[cfg(test)]
mod tests {
    use super::parse_port_report;

    #[test]
    fn reads_the_backends_port_report() {
        assert_eq!(parse_port_report("{\"docbox_backend\": {\"port\": 51234}}\n"), Some(51234));
        // Other output before the report, and reports that can't be a listening port.
        assert_eq!(parse_port_report("INFO:     Started server process [42]"), None);
        assert_eq!(parse_port_report("{\"docbox_backend\": {\"port\": 0}}"), None);
        assert_eq!(parse_port_report("{\"docbox_backend\": {\"port\": 70000}}"), None);
        assert_eq!(parse_port_report("{\"port\": 51234}"), None);
    }
}
