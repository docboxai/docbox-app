//! The typed HTTP client for the local backend: one struct per schema in
//! `src/docbox/backend/schemas.py` (and the benchmark store/report), one method per route.
//! Calls block, so run them off the UI thread (`cx.background_spawn`).

use std::collections::BTreeMap;
use std::path::Path;
use std::time::Duration;

use serde::de::DeserializeOwned;
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Deserialize)]
pub struct DeviceCapabilities {
    pub ram_total_gb: f64,
    pub ram_available_gb: f64,
    pub cpu_physical_cores: u32,
    pub cpu_logical_cores: u32,
    pub disk_free_gb: f64,
    pub disk_total_gb: f64,
    pub gpu_name: Option<String>,
    /// An NVIDIA card's memory, when its driver is installed.
    pub gpu_memory_gb: Option<f64>,
    pub os_name: String,
    pub arch: String,
}

#[derive(Clone, Debug, Deserialize)]
pub struct FitResult {
    pub fits: bool,
    pub reasons: Vec<String>,
    /// Soft warnings that don't stop it running, e.g. "Slow without a GPU".
    pub notes: Vec<String>,
    /// One short phrase for tables and chips: "Runs well", "Needs 8 GB free RAM", ...
    pub summary: String,
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum Device {
    Cpu,
    Gpu,
}

/// Where models read (settings): "auto" puts the ones that read best on a graphics card there.
#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum DevicePreference {
    Auto,
    Cpu,
    Gpu,
}

impl DevicePreference {
    pub fn label(self) -> &'static str {
        match self {
            DevicePreference::Auto => "Automatic",
            DevicePreference::Gpu => "Graphics card",
            DevicePreference::Cpu => "Processor",
        }
    }
}

#[derive(Clone, Debug, Deserialize)]
pub struct InferenceDevice {
    pub runs_on: Device,
    /// The setting deciding it: the model's own, else the global one.
    pub setting: DevicePreference,
    /// Whether its engine has a graphics-card build DocBox can install.
    pub gpu_capable: bool,
    /// Where it reads best: "gpu" when a graphics card makes it several times faster.
    pub preferred: Device,
    pub gpu_speedup: Option<f64>,
    /// What would make it faster here; None when it's already at its best.
    pub note: Option<String>,
}

/// What one click on the model does; see ModelStatus in backend/schemas.py.
#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ModelStatus {
    Ready,
    NeedsDownload,
    NeedsEngine,
    NeedsPrerequisite,
}

#[derive(Clone, Debug, Deserialize)]
pub struct ModelInfo {
    pub id: String,
    pub name: String,
    pub engine: String,
    pub description: String,
    pub languages: Vec<String>,
    pub approx_download_mb: f64,
    /// The most memory it takes while reading a page.
    pub approx_ram_mb: f64,
    /// Whether approx_ram_mb and cpu_page_seconds were measured, not estimated.
    #[serde(default)]
    pub ram_measured: bool,
    pub cpu_page_seconds: Option<f64>,
    /// Where its published sizes and speeds come from.
    pub figures_source: Option<String>,
    pub min_disk_mb: f64,
    pub device: InferenceDevice,
    pub downloaded: bool,
    pub engine_installed: bool,
    pub status: ModelStatus,
    pub requires_extra: Option<String>,
    pub prerequisite: Option<String>,
    pub fit: FitResult,
    /// The one model Setup recommends: the best built-in reader that runs smoothly here.
    #[serde(default)]
    pub recommended: bool,
    /// Its running or paused download, if any.
    pub active_job: Option<DownloadStatus>,
}

#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum DownloadState {
    Pending,
    Installing,
    Downloading,
    Paused,
    Done,
    Error,
}

impl DownloadState {
    pub fn finished(self) -> bool {
        matches!(self, DownloadState::Done | DownloadState::Error)
    }
}

#[derive(Clone, Debug, Deserialize)]
pub struct DownloadStatus {
    pub job_id: String,
    pub model_id: String,
    pub state: DownloadState,
    pub progress_pct: Option<f64>,
    pub message: Option<String>,
}

#[derive(Clone, Debug, Deserialize)]
pub struct JobStarted {
    pub job_id: String,
}

#[derive(Clone, Debug, Deserialize)]
pub struct OcrLine {
    pub text: String,
    pub confidence: Option<f64>,
}

#[derive(Clone, Debug, Deserialize)]
pub struct PlatformStatus {
    pub id: String,
    pub name: String,
    pub available: bool,
    pub detail: Option<String>,
}

#[derive(Clone, Debug, Deserialize)]
pub struct NvidiaApiKeyStatus {
    pub configured: bool,
}

#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum PrerequisiteState {
    Ready,
    Installed,
    Missing,
}

#[derive(Clone, Debug, Deserialize)]
pub struct PrerequisiteInfo {
    pub id: String,
    pub name: String,
    pub about: String,
    pub state: PrerequisiteState,
    pub can_auto_install: bool,
    pub can_start: bool,
    pub commands: Vec<String>,
    pub download_url: String,
}

#[derive(Clone, Debug, Deserialize)]
pub struct EngineStorage {
    pub id: String,
    pub name: String,
    pub installed: bool,
    pub can_install: bool,
    pub package_bytes: u64,
    pub model_bytes: u64,
    pub models_downloaded: u32,
    pub removal_pending: bool,
}

#[derive(Clone, Debug, Deserialize)]
pub struct StorageInfo {
    pub data_dir: String,
    pub models_bytes: u64,
    pub engines: Vec<EngineStorage>,
}

#[derive(Clone, Debug, Deserialize)]
pub struct EngineRemoveResult {
    pub removed: bool,
    pub pending_restart: bool,
    pub detail: String,
}

#[derive(Clone, Debug, Deserialize)]
pub struct Settings {
    pub default_model_id: Option<String>,
    pub cloud_enabled: bool,
    pub output_dir: String,
    /// The most memory a model may take while reading; None: no limit.
    pub ram_limit_gb: Option<f64>,
    pub device_preference: DevicePreference,
    /// Models set to a device other than what device_preference gives them.
    #[serde(default)]
    pub model_devices: BTreeMap<String, Device>,
}

/// Fields left out are unchanged; default_model_id "" clears the default, ram_limit_gb 0
/// removes the limit.
#[derive(Clone, Debug, Default, Serialize)]
pub struct SettingsUpdate {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub default_model_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub cloud_enabled: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub ram_limit_gb: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub device_preference: Option<DevicePreference>,
    /// Merged into the saved ones; "auto" makes a model follow device_preference again.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub model_devices: Option<BTreeMap<String, DevicePreference>>,
}

#[derive(Clone, Debug, Deserialize)]
pub struct EngineGpuBuild {
    pub id: String,
    pub name: String,
    /// Which build is installed; None: the engine isn't.
    pub installed: Option<Device>,
    pub gpu_download_mb: f64,
    /// Why it can't switch to the graphics card now, or None.
    pub blocked: Option<String>,
    /// A switch that waits for DocBox to restart (the engine was in use).
    pub pending_restart: bool,
    pub job: Option<DownloadStatus>,
}

#[derive(Clone, Debug, Deserialize)]
pub struct GpuStatus {
    pub usable: bool,
    pub reason: Option<String>,
    pub name: Option<String>,
    pub driver_version: Option<String>,
    pub cuda_version: Option<String>,
    pub cuda_required: String,
    pub compute_capability: Option<String>,
    pub memory_total_gb: Option<f64>,
    pub memory_free_gb: Option<f64>,
    pub engines: Vec<EngineGpuBuild>,
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum OutputFormat {
    Txt,
    Md,
    Pdf,
    Json,
}

impl OutputFormat {
    pub const ALL: [OutputFormat; 4] =
        [OutputFormat::Txt, OutputFormat::Md, OutputFormat::Pdf, OutputFormat::Json];

    pub fn label(self) -> &'static str {
        match self {
            OutputFormat::Txt => "Plain text",
            OutputFormat::Md => "Markdown",
            OutputFormat::Pdf => "Searchable PDF",
            OutputFormat::Json => "JSON",
        }
    }

    pub fn as_str(self) -> &'static str {
        match self {
            OutputFormat::Txt => "txt",
            OutputFormat::Md => "md",
            OutputFormat::Pdf => "pdf",
            OutputFormat::Json => "json",
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum ReadState {
    Queued,
    Reading,
    Done,
    Error,
    Cancelled,
}

#[derive(Clone, Debug, Deserialize)]
pub struct ReadSummary {
    pub id: String,
    pub file_name: String,
    pub model_id: String,
    pub model_name: String,
    pub output_format: OutputFormat,
    pub state: ReadState,
    pub pages_total: Option<u32>,
    pub pages_done: u32,
    pub seconds: Option<f64>,
    pub created_at: f64,
    pub output_path: Option<String>,
    pub error: Option<String>,
}

#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum PageSource {
    Ocr,
    PdfText,
}

#[derive(Clone, Debug, Deserialize)]
pub struct ReadPage {
    pub lines: Vec<OcrLine>,
    pub text: String,
    /// PdfText: the PDF page carried its own text, used as-is instead of OCR.
    pub source: PageSource,
}

#[derive(Clone, Debug, Deserialize)]
pub struct ReadDetail {
    #[serde(flatten)]
    pub summary: ReadSummary,
    pub pages: Vec<ReadPage>,
    pub text: String,
}

#[derive(Clone, Debug, Deserialize)]
pub struct ReadsStarted {
    pub reads: Vec<ReadSummary>,
}

// Benchmarks (backend benchmark/store.py and report.py).

#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum BenchState {
    Queued,
    Running,
    Done,
    Error,
    Cancelled,
    Interrupted,
}

impl BenchState {
    pub fn active(self) -> bool {
        matches!(self, BenchState::Queued | BenchState::Running)
    }
}

#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum ModelRunState {
    Pending,
    Installing,
    Running,
    Done,
    Error,
    Skipped,
}

#[derive(Clone, Debug, Deserialize)]
pub struct BenchFile {
    pub id: String,
    pub path: String,
    pub pages: u32,
    pub has_reference: bool,
}

#[derive(Clone, Debug, Deserialize)]
pub struct ModelRun {
    pub model_id: String,
    pub name: String,
    pub state: ModelRunState,
    pub error: Option<String>,
    pub load_seconds: Option<f64>,
    pub peak_memory_mb: Option<f64>,
    pub memory_note: Option<String>,
    pub device: Option<Device>,
}

#[derive(Clone, Debug, Deserialize)]
pub struct LeaderboardRow {
    pub model_id: String,
    pub name: String,
    pub rank: Option<u32>,
    pub pages_read: u32,
    pub pages_failed: u32,
    pub load_seconds: Option<f64>,
    pub seconds_per_page: Option<f64>,
    pub median_seconds_per_page: Option<f64>,
    pub peak_memory_mb: Option<f64>,
    pub mean_confidence: Option<f64>,
    /// Only with reference text; accuracy is 1 - cer.
    pub cer: Option<f64>,
    pub wer: Option<f64>,
    pub accuracy: Option<f64>,
    pub scored_chars: u64,
    /// Half-width of a 95% interval around accuracy, over `scored_units` references.
    pub accuracy_margin: Option<f64>,
    pub scored_units: u32,
    pub engine: String,
    pub family: Option<String>,
    pub variant: Option<String>,
    pub memory_note: Option<String>,
    pub device: Option<Device>,
}

#[derive(Clone, Debug, Deserialize)]
pub struct BenchSummary {
    pub ranked_by: String,
    pub leaderboard: Vec<LeaderboardRow>,
    pub best_model_id: Option<String>,
}

#[derive(Clone, Debug, Deserialize)]
pub struct BenchRun {
    pub id: String,
    pub name: String,
    pub created_at: f64,
    pub finished_at: Option<f64>,
    pub state: BenchState,
    pub error: Option<String>,
    pub ignore_case: bool,
    /// "app" | "cli" | "mcp"
    pub source: String,
    pub files: Vec<BenchFile>,
    pub models: Vec<ModelRun>,
    pub pages_total: u32,
    pub pages_done: u32,
    pub current_model_id: Option<String>,
    pub summary: Option<BenchSummary>,
}

/// Relative to the reference: kept text, text the model added, reference text it missed,
/// or reference text it replaced.
#[derive(Clone, Debug, Deserialize)]
pub struct DiffSpan {
    pub op: String,
    pub text: String,
    pub reference: String,
}

#[derive(Clone, Debug, Deserialize)]
pub struct PageRead {
    pub model_id: String,
    pub name: String,
    pub text: String,
    pub error: Option<String>,
    pub seconds: Option<f64>,
    pub mean_confidence: Option<f64>,
    pub slips: Option<u32>,
    pub cer: Option<f64>,
    pub diff: Vec<DiffSpan>,
}

#[derive(Clone, Debug, Deserialize)]
pub struct PageView {
    pub run_id: String,
    pub file_id: String,
    pub page: u32,
    pub pages: u32,
    /// "reference" | "model" | "none"
    pub reference_kind: String,
    pub reference_model_id: Option<String>,
    pub reference: Option<String>,
    pub reads: Vec<PageRead>,
}

#[derive(Clone, Debug, Deserialize)]
pub struct ReferenceScoreV1 {
    pub value: f64,
    pub self_reported: bool,
    pub source: String,
    pub url: String,
}

#[derive(Clone, Debug, Deserialize)]
pub struct ReferenceScoreV2 {
    pub en: Option<f64>,
    pub zh: Option<f64>,
    pub self_reported: bool,
    pub source: String,
    pub url: String,
}

#[derive(Clone, Debug, Deserialize)]
pub struct ReferenceBenchmark {
    pub name: String,
    pub max: f64,
    pub about: String,
    pub url: String,
    pub splits: Vec<String>,
}

#[derive(Clone, Debug, Deserialize)]
pub struct ReferenceScores {
    pub ocrbench_v1: Option<ReferenceScoreV1>,
    pub ocrbench_v2: Option<ReferenceScoreV2>,
}

#[derive(Clone, Debug, Deserialize)]
pub struct ReferenceModel {
    pub model_id: String,
    pub label: String,
    pub scores: ReferenceScores,
}

#[derive(Clone, Debug, Deserialize)]
pub struct ReferenceData {
    pub benchmarks: BTreeMap<String, ReferenceBenchmark>,
    pub models: Vec<ReferenceModel>,
    pub notes: Vec<String>,
    pub checked: String,
}

/// A failed call: the backend's `detail` when it sent one, else the status and body, or
/// why the request didn't get an answer at all.
pub type ApiResult<T> = Result<T, String>;

/// The backend refuses state-changing requests without this header (so other websites
/// can't trigger them with a form post); see backend core/client_header.py.
const CLIENT_HEADER: (&str, &str) = ("X-DocBox-Client", "app");

#[derive(Clone)]
pub struct Api {
    base: String,
    http: reqwest::blocking::Client,
}

fn error_message(resp: reqwest::blocking::Response) -> String {
    let status = resp.status();
    let text = resp.text().unwrap_or_default();
    if let Ok(value) = serde_json::from_str::<serde_json::Value>(&text) {
        if let Some(detail) = value.get("detail").and_then(|d| d.as_str()) {
            return detail.to_string();
        }
    }
    format!("{} {text}", status.as_u16())
}

fn query(value: &str) -> String {
    url::form_urlencoded::byte_serialize(value.as_bytes()).collect()
}

/// A path segment: model ids carry ':' and '/' (Ollama tags, NIM names), sent encoded.
fn segment(value: &str) -> String {
    query(value)
}

impl Api {
    pub fn new(base: impl Into<String>) -> Self {
        let http = reqwest::blocking::Client::builder()
            // Long enough for a whole read page (/api/ocr/run isn't used here) and the
            // storage figures, which walk the installed packages.
            .timeout(Duration::from_secs(120))
            .build()
            .expect("an HTTP client with default settings");
        Self { base: base.into(), http }
    }

    pub fn base_url(&self) -> &str {
        &self.base
    }

    fn send(&self, req: reqwest::blocking::RequestBuilder) -> ApiResult<reqwest::blocking::Response> {
        let resp = req
            .header(CLIENT_HEADER.0, CLIENT_HEADER.1)
            .send()
            .map_err(|e| format!("Couldn't reach DocBox's engine: {e}"))?;
        if !resp.status().is_success() {
            return Err(error_message(resp));
        }
        Ok(resp)
    }

    fn json<T: DeserializeOwned>(&self, req: reqwest::blocking::RequestBuilder) -> ApiResult<T> {
        let resp = self.send(req)?;
        resp.json::<T>().map_err(|e| format!("Unexpected answer from DocBox's engine: {e}"))
    }

    fn empty(&self, req: reqwest::blocking::RequestBuilder) -> ApiResult<()> {
        self.send(req).map(|_| ())
    }

    fn get(&self, path: &str) -> reqwest::blocking::RequestBuilder {
        self.http.get(format!("{}{path}", self.base))
    }

    fn post(&self, path: &str) -> reqwest::blocking::RequestBuilder {
        self.http.post(format!("{}{path}", self.base))
    }

    fn delete(&self, path: &str) -> reqwest::blocking::RequestBuilder {
        self.http.delete(format!("{}{path}", self.base))
    }

    pub fn device_capabilities(&self) -> ApiResult<DeviceCapabilities> {
        self.json(self.get("/api/device/capabilities"))
    }

    pub fn list_models(&self) -> ApiResult<Vec<ModelInfo>> {
        self.json(self.get("/api/models"))
    }

    pub fn get_settings(&self) -> ApiResult<Settings> {
        self.json(self.get("/api/settings"))
    }

    pub fn update_settings(&self, patch: &SettingsUpdate) -> ApiResult<Settings> {
        self.json(self.http.patch(format!("{}/api/settings", self.base)).json(patch))
    }

    pub fn start_download(&self, model_id: &str) -> ApiResult<JobStarted> {
        self.json(self.post(&format!("/api/models/{}/download", segment(model_id))))
    }

    pub fn download_status(&self, model_id: &str, job_id: &str) -> ApiResult<DownloadStatus> {
        self.json(self.get(&format!(
            "/api/models/{}/download/status?job_id={}",
            segment(model_id),
            query(job_id)
        )))
    }

    pub fn pause_download(&self, model_id: &str, job_id: &str) -> ApiResult<DownloadStatus> {
        self.json(self.post(&format!(
            "/api/models/{}/download/pause?job_id={}",
            segment(model_id),
            query(job_id)
        )))
    }

    pub fn delete_model(&self, model_id: &str) -> ApiResult<()> {
        self.empty(self.delete(&format!("/api/models/{}", segment(model_id))))
    }

    pub fn get_prerequisite(&self, id: &str) -> ApiResult<PrerequisiteInfo> {
        self.json(self.get(&format!("/api/prerequisites/{}", segment(id))))
    }

    pub fn start_prerequisite_install(&self, id: &str) -> ApiResult<JobStarted> {
        self.json(self.post(&format!("/api/prerequisites/{}/install", segment(id))))
    }

    pub fn prerequisite_install_status(&self, id: &str, job_id: &str) -> ApiResult<DownloadStatus> {
        self.json(self.get(&format!(
            "/api/prerequisites/{}/install/status?job_id={}",
            segment(id),
            query(job_id)
        )))
    }

    pub fn start_ollama(&self) -> ApiResult<PrerequisiteInfo> {
        self.json(self.post("/api/prerequisites/ollama/start"))
    }

    pub fn engine_storage(&self) -> ApiResult<StorageInfo> {
        self.json(self.get("/api/engines/storage"))
    }

    pub fn open_models_folder(&self) -> ApiResult<()> {
        self.empty(self.post("/api/engines/storage/open"))
    }

    pub fn uninstall_engine(&self, id: &str) -> ApiResult<EngineRemoveResult> {
        self.json(self.delete(&format!("/api/engines/{}", segment(id))))
    }

    pub fn gpu_status(&self) -> ApiResult<GpuStatus> {
        self.json(self.get("/api/engines/gpu"))
    }

    pub fn switch_engine_build(&self, id: &str, build: Device) -> ApiResult<DownloadStatus> {
        self.json(
            self.post(&format!("/api/engines/{}/build", segment(id)))
                .json(&serde_json::json!({ "build": build })),
        )
    }

    pub fn engine_build_status(&self, job_id: &str) -> ApiResult<DownloadStatus> {
        self.json(self.get(&format!("/api/engines/build/status?job_id={}", query(job_id))))
    }

    pub fn list_platforms(&self) -> ApiResult<Vec<PlatformStatus>> {
        self.json(self.get("/api/platforms"))
    }

    pub fn set_nvidia_api_key(&self, key: &str) -> ApiResult<NvidiaApiKeyStatus> {
        self.json(
            self.post("/api/platforms/nvidia-nim/api-key")
                .json(&serde_json::json!({ "api_key": key })),
        )
    }

    pub fn nvidia_api_key_status(&self) -> ApiResult<NvidiaApiKeyStatus> {
        self.json(self.get("/api/platforms/nvidia-nim/api-key"))
    }

    pub fn clear_nvidia_api_key(&self) -> ApiResult<NvidiaApiKeyStatus> {
        self.json(self.delete("/api/platforms/nvidia-nim/api-key"))
    }

    /// Upload files from disk to read. `use_pdf_text` false reads every PDF page with the
    /// model, even pages with their own text.
    pub fn start_reads(
        &self,
        model_id: &str,
        files: &[std::path::PathBuf],
        format: OutputFormat,
        use_pdf_text: bool,
    ) -> ApiResult<ReadsStarted> {
        let mut form = reqwest::blocking::multipart::Form::new();
        for path in files {
            form = form
                .file("files", path)
                .map_err(|e| format!("Couldn't open {}: {e}", path.display()))?;
        }
        let form = form
            .text("model_id", model_id.to_string())
            .text("output_format", format.as_str())
            .text("use_pdf_text", use_pdf_text.to_string());
        self.json(self.post("/api/reads").multipart(form))
    }

    pub fn list_reads(&self) -> ApiResult<Vec<ReadSummary>> {
        self.json(self.get("/api/reads"))
    }

    pub fn get_read(&self, id: &str) -> ApiResult<ReadDetail> {
        self.json(self.get(&format!("/api/reads/{}", segment(id))))
    }

    pub fn delete_read(&self, id: &str) -> ApiResult<()> {
        self.empty(self.delete(&format!("/api/reads/{}", segment(id))))
    }

    /// "file" opens the saved output; "folder" shows it in the file manager.
    pub fn open_read(&self, id: &str, target: &str) -> ApiResult<()> {
        self.empty(self.post(&format!("/api/reads/{}/open?target={target}", segment(id))))
    }

    /// Files keep their path relative to the folder they were picked from
    /// ("Invoices/march/a.pdf") so sidecar references (a.gt.txt) stay next to their
    /// documents on the backend.
    pub fn start_benchmark(
        &self,
        files: &[(std::path::PathBuf, String)],
        model_ids: &[String],
        name: &str,
    ) -> ApiResult<BenchRun> {
        let mut form = reqwest::blocking::multipart::Form::new();
        for (path, relative) in files {
            let bytes = std::fs::read(path)
                .map_err(|e| format!("Couldn't open {}: {e}", path.display()))?;
            form = form.part(
                "files",
                reqwest::blocking::multipart::Part::bytes(bytes).file_name(relative.clone()),
            );
        }
        let form = form.text("model_ids", model_ids.join(",")).text("name", name.to_string());
        self.json(self.post("/api/benchmarks").multipart(form))
    }

    pub fn list_benchmarks(&self) -> ApiResult<Vec<BenchRun>> {
        self.json(self.get("/api/benchmarks"))
    }

    pub fn benchmark_reference(&self) -> ApiResult<ReferenceData> {
        self.json(self.get("/api/benchmarks/reference"))
    }

    pub fn get_benchmark(&self, id: &str) -> ApiResult<BenchRun> {
        self.json(self.get(&format!("/api/benchmarks/{}", segment(id))))
    }

    pub fn benchmark_page(
        &self,
        id: &str,
        file_id: &str,
        page: u32,
        against: Option<&str>,
    ) -> ApiResult<PageView> {
        let mut path = format!(
            "/api/benchmarks/{}/page?file_id={}&page={page}",
            segment(id),
            query(file_id)
        );
        if let Some(against) = against {
            path.push_str(&format!("&against={}", query(against)));
        }
        self.json(self.get(&path))
    }

    /// The page image a benchmark read, as encoded image bytes.
    pub fn benchmark_image(&self, id: &str, file_id: &str, page: u32) -> ApiResult<Vec<u8>> {
        let resp = self.send(self.get(&format!(
            "/api/benchmarks/{}/image?file_id={}&page={page}",
            segment(id),
            query(file_id)
        )))?;
        resp.bytes().map(|b| b.to_vec()).map_err(|e| e.to_string())
    }

    /// The desktop app shows the saved report (or its folder) on this computer.
    pub fn open_benchmark_report(&self, id: &str, target: &str) -> ApiResult<()> {
        self.empty(self.post(&format!("/api/benchmarks/{}/report/open?target={target}", segment(id))))
    }

    pub fn cancel_benchmark(&self, id: &str) -> ApiResult<BenchRun> {
        self.json(self.post(&format!("/api/benchmarks/{}/cancel", segment(id))))
    }

    pub fn rerun_benchmark(&self, id: &str) -> ApiResult<BenchRun> {
        self.json(self.post(&format!("/api/benchmarks/{}/rerun", segment(id))))
    }

    pub fn delete_benchmark(&self, id: &str) -> ApiResult<()> {
        self.empty(self.delete(&format!("/api/benchmarks/{}", segment(id))))
    }
}

/// Whether DocBox can read this file (PDFs, TIFFs and images), by its extension.
pub fn is_readable(path: &Path) -> bool {
    let ext = path.extension().and_then(|e| e.to_str()).unwrap_or("").to_ascii_lowercase();
    matches!(
        ext.as_str(),
        "pdf" | "tif" | "tiff" | "png" | "jpg" | "jpeg" | "bmp" | "gif" | "webp"
    )
}
