//! The client against the real backend: starts `docbox.backend.main` from the repository's
//! own `.venv` on a free port with a throwaway data folder and the test suite's fake models
//! (tests/bench_fakes.py, which read instantly), then goes through every route the app
//! uses and deserializes each answer, reading a file and running a benchmark end to end.
//! Skipped when the repository has no `.venv` (run `uv sync` first).

use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

use crate::api::{Api, BenchState, Device, ModelStatus, OutputFormat, ReadState, SettingsUpdate};
use crate::backend::parse_port_report;

struct Server {
    child: Child,
    data: PathBuf,
}

impl Drop for Server {
    fn drop(&mut self) {
        // Closing stdin (the lifeline) stops it; kill in case it doesn't.
        drop(self.child.stdin.take());
        let deadline = Instant::now() + Duration::from_secs(10);
        while Instant::now() < deadline && matches!(self.child.try_wait(), Ok(None)) {
            std::thread::sleep(Duration::from_millis(100));
        }
        let _ = self.child.kill();
        let _ = self.child.wait();
        let _ = std::fs::remove_dir_all(&self.data);
    }
}

fn repo() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).parent().unwrap().to_path_buf()
}

fn python() -> Option<PathBuf> {
    let venv = repo().join(".venv");
    let python = if cfg!(windows) { venv.join("Scripts").join("python.exe") } else { venv.join("bin").join("python") };
    python.exists().then_some(python)
}

fn python_path() -> std::ffi::OsString {
    std::env::join_paths([repo().join("tests"), repo().join("src")]).unwrap()
}

fn start(python: &Path) -> (Server, Api) {
    let data = std::env::temp_dir().join(format!("docbox-contract-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&data);
    std::fs::create_dir_all(&data).unwrap();
    let script = "import sys; sys.argv = ['docbox-backend', '--port', '0', '--exit-on-stdin-close']; \
                  import bench_fakes; from docbox.backend.main import main; main()";
    let mut child = Command::new(python)
        .args(["-c", script])
        .current_dir(repo())
        .env("DOCBOX_DATA_DIR", &data)
        .env("PYTHONPATH", python_path())
        // Benchmark workers register the fakes too.
        .env("DOCBOX_PRELOAD", "bench_fakes")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .expect("start the backend");
    let stdout = child.stdout.take().unwrap();
    let port = BufReader::new(stdout)
        .lines()
        .map_while(Result::ok)
        .find_map(|line| parse_port_report(&line))
        .expect("the backend reports its port");
    let api = Api::new(format!("http://127.0.0.1:{port}"));
    (Server { child, data }, api)
}

fn wait_for<T>(what: &str, mut check: impl FnMut() -> Option<T>) -> T {
    let deadline = Instant::now() + Duration::from_secs(60);
    loop {
        if let Some(v) = check() {
            return v;
        }
        assert!(Instant::now() < deadline, "timed out waiting for {what}");
        std::thread::sleep(Duration::from_millis(200));
    }
}

/// Writes the fake models' page 1 (it reads as "Total due $1,284.00 / Ref INV-0312").
fn page_image(python: &Path, path: &Path) {
    let code = format!("import bench_fakes; bench_fakes.page_image(1).save({:?})", path.to_string_lossy());
    let ok = Command::new(python).args(["-c", &code]).env("PYTHONPATH", python_path()).status().unwrap();
    assert!(ok.success());
}

#[test]
fn every_route_the_app_uses_answers_in_the_shape_it_expects() {
    let Some(python) = python() else {
        eprintln!("skipped: no .venv in the repository (run `uv sync`)");
        return;
    };
    let (server, api) = start(&python);
    wait_for("health", || api.device_capabilities().ok());

    // Settings, hardware, models, engines, outside programs.
    let caps = api.device_capabilities().unwrap();
    assert!(caps.ram_total_gb > 0.0);
    let settings = api.update_settings(&SettingsUpdate { cloud_enabled: Some(false), ..Default::default() }).unwrap();
    assert!(!settings.cloud_enabled);
    let models = api.list_models().unwrap();
    let good = models.iter().find(|m| m.id == "fake-good").expect("the fake models are listed");
    assert_eq!(good.status, ModelStatus::Ready);
    assert!(models.iter().any(|m| m.engine == "paddleocr"), "the built-in catalog is listed too");
    let _ = api.engine_storage().unwrap();
    let gpu = api.gpu_status().unwrap();
    assert!(gpu.engines.iter().all(|e| e.installed != Some(Device::Gpu) || gpu.name.is_some()));
    assert!(!api.list_platforms().unwrap().is_empty());
    let _ = api.nvidia_api_key_status().unwrap();
    assert_eq!(api.get_prerequisite("tesseract").unwrap().id, "tesseract");
    let patch = SettingsUpdate {
        model_devices: Some([("fake-good".to_string(), crate::api::DevicePreference::Cpu)].into()),
        default_model_id: Some("fake-good".into()),
        ..Default::default()
    };
    assert_eq!(api.update_settings(&patch).unwrap().default_model_id.as_deref(), Some("fake-good"));

    // Read a file, end to end.
    let docs = server.data.join("docs");
    std::fs::create_dir_all(&docs).unwrap();
    let invoice = docs.join("invoice.png");
    page_image(&python, &invoice);
    let started = api.start_reads("fake-good", &[invoice.clone()], OutputFormat::Md, true).unwrap();
    let id = started.reads[0].id.clone();
    let done = wait_for("the read", || {
        let r = api.list_reads().unwrap().into_iter().find(|r| r.id == id)?;
        matches!(r.state, ReadState::Done | ReadState::Error).then_some(r)
    });
    assert_eq!(done.state, ReadState::Done, "{:?}", done.error);
    let detail = api.get_read(&id).unwrap();
    assert!(detail.text.contains("Total due"), "{}", detail.text);
    assert_eq!(detail.pages[0].lines.len(), 2);
    api.delete_read(&id).unwrap();
    assert!(api.list_reads().unwrap().iter().all(|r| r.id != id));

    // A benchmark with reference text: the careful model must beat the sloppy one.
    std::fs::write(docs.join("invoice.gt.txt"), "Total due $1,284.00\nRef INV-0312\n").unwrap();
    let files = vec![
        (invoice.clone(), "batch/invoice.png".to_string()),
        (docs.join("invoice.gt.txt"), "batch/invoice.gt.txt".to_string()),
    ];
    let run = api.start_benchmark(&files, &["fake-good".into(), "fake-sloppy".into()], "Contract").unwrap();
    let run = wait_for("the benchmark", || {
        let r = api.get_benchmark(&run.id).unwrap();
        (!r.state.active()).then_some(r)
    });
    assert_eq!(run.state, BenchState::Done, "{:?}", run.error);
    let summary = run.summary.clone().expect("a finished run has a summary");
    assert_eq!(summary.ranked_by, "cer");
    assert_eq!(summary.best_model_id.as_deref(), Some("fake-good"));
    assert!(api.list_benchmarks().unwrap().iter().any(|r| r.id == run.id));
    let file = &run.files[0];
    assert!(file.has_reference);
    let page = api.benchmark_page(&run.id, &file.id, 1, None).unwrap();
    assert_eq!(page.reference_kind, "reference");
    let sloppy = page.reads.iter().find(|r| r.model_id == "fake-sloppy").unwrap();
    assert!(sloppy.slips.unwrap_or(0) > 0 && sloppy.diff.iter().any(|d| d.op != "equal"));
    let png = api.benchmark_image(&run.id, &file.id, 1).unwrap();
    assert_eq!(&png[1..4], b"PNG");
    let reference = api.benchmark_reference().unwrap();
    assert!(reference.benchmarks.contains_key("ocrbench_v1") && !reference.models.is_empty());
    api.delete_benchmark(&run.id).unwrap();

    // Errors come back as the backend's own words.
    let err = api.start_download("no-such-model").unwrap_err();
    assert!(!err.is_empty() && !err.contains("Couldn't reach"), "{err}");
    drop(server);
}
