// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::fs::{self, File};
use std::io::{BufRead, BufReader, Write};
use std::net::TcpListener;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::Duration;

use serde::Serialize;
use tauri::{AppHandle, Manager, State};

const PREFERRED_PORT: u16 = 8756;
const HEALTH_TIMEOUT: Duration = Duration::from_secs(60);

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
    cmd.args(["sync", "--frozen", "--no-dev", "--no-install-project", "--project"])
        .arg(&l.project_dir)
        .env("UV_PYTHON_PREFERENCE", "only-managed")
        .envs(uv_env(l))
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

fn pick_port() -> u16 {
    if TcpListener::bind(("127.0.0.1", PREFERRED_PORT)).is_ok() {
        return PREFERRED_PORT;
    }
    let listener = TcpListener::bind(("127.0.0.1", 0)).expect("failed to bind ephemeral port");
    listener.local_addr().unwrap().port()
}

fn spawn_backend(l: &Layout, port: u16) -> Result<Child, String> {
    let log = File::create(l.logs_dir.join("backend.log")).map_err(|e| e.to_string())?;
    let log_err = log.try_clone().map_err(|e| e.to_string())?;
    let mut cmd = Command::new(&l.python);
    cmd.args(["-m", "docbox.backend.main", "--host", "127.0.0.1", "--port", &port.to_string()])
        .current_dir(&l.project_dir)
        .env("DOCBOX_DATA_DIR", &l.data_dir)
        .env("DOCBOX_PROJECT_DIR", &l.project_dir)
        .envs(uv_env(l))
        .stdout(Stdio::from(log))
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
    no_window(&mut cmd)
        .spawn()
        .map_err(|e| format!("failed to start the backend ({:?}): {e}", l.python))
}

// A plain `child.kill()` only terminates that one process. That's not enough on
// Windows: a uv-managed venv's `python.exe` is itself a trampoline stub that spawns the
// real CPython interpreter as a *further* child, so the process we hold a `Child` for
// isn't the one actually doing OCR/model-download work. `taskkill /T` kills the whole
// process tree rooted at that PID, which reaches the real interpreter regardless of how
// many stub layers are in between.
fn kill_tree(pid: u32) {
    #[cfg(windows)]
    {
        let mut cmd = Command::new("taskkill");
        cmd.args(["/PID", &pid.to_string(), "/T", "/F"]);
        let _ = no_window(&mut cmd).status();
    }
    #[cfg(not(windows))]
    {
        let _ = Command::new("kill").args(["-TERM", &pid.to_string()]).status();
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
    let port = pick_port();
    let base_url = format!("http://127.0.0.1:{port}");
    let child = spawn_backend(&l, port)?;
    *app.state::<Backend>().child.lock().unwrap() = Some(child);

    tauri::async_runtime::block_on(wait_until_ready(&base_url))?;
    let backend = app.state::<Backend>();
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

/// Stop the bootstrap `uv` and the backend (whole process trees). Every way the app can
/// end goes through here: window close and normal exit.
fn shutdown_backend(app: &AppHandle) {
    let state = app.state::<Backend>();
    let setup_pid = state.setup_pid.lock().unwrap().take();
    if let Some(pid) = setup_pid {
        kill_tree(pid);
    }
    let child = state.child.lock().unwrap().take();
    if let Some(mut child) = child {
        kill_tree(child.id());
        let _ = child.wait();
    }
}

#[tauri::command]
fn retry_backend(app: AppHandle, state: State<Backend>) {
    if state.status.lock().unwrap().state != "failed" {
        return;
    }
    if let Some(mut child) = state.child.lock().unwrap().take() {
        kill_tree(child.id());
        let _ = child.wait();
    }
    start_boot(app);
}

fn main() {
    let app = tauri::Builder::default()
        // Opens the releases page from the update notice in the default browser; the
        // capability allows only that page.
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
            retry_backend
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
