import { invoke } from "@tauri-apps/api/core";

export interface DeviceCapabilities {
  ram_total_gb: number;
  ram_available_gb: number;
  cpu_physical_cores: number;
  cpu_logical_cores: number;
  disk_free_gb: number;
  disk_total_gb: number;
  gpu_name: string | null;
  os_name: string;
  arch: string;
}

export interface FitResult {
  fits: boolean;
  reasons: string[];
  // Soft warnings that don't stop it running, e.g. "Slow without a GPU".
  notes: string[];
  // One short phrase for tables and chips: "Runs well", "Needs 8 GB free RAM", ...
  summary: string;
}

// What one click on the model does; see ModelStatus in backend/schemas.py.
export type ModelStatus = "ready" | "needs_download" | "needs_engine" | "needs_prerequisite";

export interface ModelInfo {
  id: string;
  name: string;
  engine: string;
  description: string;
  languages: string[];
  approx_download_mb: number;
  approx_ram_mb: number;
  min_disk_mb: number;
  downloaded: boolean;
  engine_installed: boolean;
  status: ModelStatus;
  requires_extra: string | null;
  prerequisite: string | null;
  fit: FitResult;
  // The one model Setup recommends: the best built-in reader that runs smoothly here.
  recommended: boolean;
  // Its running or paused download, if any.
  active_job: DownloadStatus | null;
}

export type DownloadState =
  | "pending"
  | "installing"
  | "downloading"
  | "paused"
  | "done"
  | "error";

export interface DownloadStatus {
  job_id: string;
  model_id: string;
  state: DownloadState;
  progress_pct: number | null;
  message: string | null;
}

export interface OcrLine {
  text: string;
  confidence: number | null;
  box: number[] | null;
}

export interface PlatformStatus {
  id: string;
  name: string;
  available: boolean;
  detail: string | null;
}

export interface NvidiaApiKeyStatus {
  configured: boolean;
}

export interface PrerequisiteInfo {
  id: string;
  name: string;
  about: string;
  state: "ready" | "installed" | "missing";
  can_auto_install: boolean;
  can_start: boolean;
  commands: string[];
  download_url: string;
}

export interface EngineStorage {
  id: string;
  name: string;
  installed: boolean;
  can_install: boolean;
  package_bytes: number;
  model_bytes: number;
  models_downloaded: number;
  removal_pending: boolean;
}

export interface StorageInfo {
  data_dir: string;
  models_bytes: number;
  engines: EngineStorage[];
}

export interface EngineRemoveResult {
  removed: boolean;
  pending_restart: boolean;
  detail: string;
}

export interface Settings {
  default_model_id: string | null;
  cloud_enabled: boolean;
  output_dir: string;
}

export type OutputFormat = "txt" | "md" | "pdf" | "json";
export type ReadState = "queued" | "reading" | "done" | "error" | "cancelled";

export interface ReadSummary {
  id: string;
  file_name: string;
  model_id: string;
  model_name: string;
  output_format: OutputFormat;
  state: ReadState;
  pages_total: number | null;
  pages_done: number;
  seconds: number | null;
  created_at: number;
  output_path: string | null;
  error: string | null;
}

export interface ReadPage {
  lines: OcrLine[];
  text: string;
}

export interface ReadDetail extends ReadSummary {
  pages: ReadPage[];
  text: string;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1e6) return `${Math.round(bytes / 1e3)} KB`;
  if (bytes < 1e9) return `${Math.round(bytes / 1e6)} MB`;
  return `${(bytes / 1e9).toFixed(1)} GB`;
}

let baseUrlPromise: Promise<string> | null = null;

// Outside the Tauri webview (`npm run dev` in a browser, including from another device
// through a reverse proxy) requests go to this page's own origin, and Vite proxies /api
// to the backend (vite.config.ts). Same-origin means no CORS or mixed-content issues.
async function getBaseUrl(): Promise<string> {
  if (!baseUrlPromise) {
    baseUrlPromise =
      "__TAURI_INTERNALS__" in window
        ? invoke<string>("backend_base_url").catch((err) => {
            // Not ready yet (or restarted after Retry): don't cache the failure.
            baseUrlPromise = null;
            throw err;
          })
        : Promise.resolve("");
  }
  return baseUrlPromise;
}

async function errorMessage(resp: Response): Promise<string> {
  const text = await resp.text().catch(() => resp.statusText);
  try {
    const detail = (JSON.parse(text) as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
  } catch {
    // not JSON; fall through to the raw text
  }
  return `${resp.status} ${text}`;
}

// The backend refuses state-changing requests without this header (so other websites
// can't trigger them with a form post); see backend core/client_header.py.
const CLIENT_HEADER = { "X-DocBox-Client": "app" };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const base = await getBaseUrl();
  const headers = new Headers(init?.headers);
  for (const [k, v] of Object.entries(CLIENT_HEADER)) headers.set(k, v);
  const resp = await fetch(`${base}${path}`, { ...init, headers });
  if (!resp.ok) throw new Error(await errorMessage(resp));
  if (resp.status === 204) return undefined as T;
  return resp.json() as Promise<T>;
}

export const api = {
  health: () => request<{ status: string }>("/api/health"),
  deviceCapabilities: () => request<DeviceCapabilities>("/api/device/capabilities"),
  listModels: () => request<ModelInfo[]>("/api/models"),
  getSettings: () => request<Settings>("/api/settings"),
  updateSettings: (patch: { default_model_id?: string; cloud_enabled?: boolean }) =>
    request<Settings>("/api/settings", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    }),
  startDownload: (modelId: string) =>
    request<{ job_id: string }>(`/api/models/${modelId}/download`, { method: "POST" }),
  downloadStatus: (modelId: string, jobId: string) =>
    request<DownloadStatus>(
      `/api/models/${modelId}/download/status?job_id=${encodeURIComponent(jobId)}`,
    ),
  pauseDownload: (modelId: string, jobId: string) =>
    request<DownloadStatus>(
      `/api/models/${modelId}/download/pause?job_id=${encodeURIComponent(jobId)}`,
      { method: "POST" },
    ),
  deleteModel: (modelId: string) =>
    request<void>(`/api/models/${modelId}`, { method: "DELETE" }),
  listPrerequisites: () => request<PrerequisiteInfo[]>("/api/prerequisites"),
  getPrerequisite: (id: string) => request<PrerequisiteInfo>(`/api/prerequisites/${id}`),
  startPrerequisiteInstall: (id: string) =>
    request<{ job_id: string }>(`/api/prerequisites/${id}/install`, { method: "POST" }),
  prerequisiteInstallStatus: (id: string, jobId: string) =>
    request<DownloadStatus>(
      `/api/prerequisites/${id}/install/status?job_id=${encodeURIComponent(jobId)}`,
    ),
  startOllama: () => request<PrerequisiteInfo>("/api/prerequisites/ollama/start", { method: "POST" }),
  engineStorage: () => request<StorageInfo>("/api/engines/storage"),
  openModelsFolder: () => request<void>("/api/engines/storage/open", { method: "POST" }),
  uninstallEngine: (id: string) =>
    request<EngineRemoveResult>(`/api/engines/${id}`, { method: "DELETE" }),
  listPlatforms: () => request<PlatformStatus[]>("/api/platforms"),
  setNvidiaApiKey: (apiKey: string) =>
    request<NvidiaApiKeyStatus>("/api/platforms/nvidia-nim/api-key", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key: apiKey }),
    }),
  nvidiaApiKeyStatus: () =>
    request<NvidiaApiKeyStatus>("/api/platforms/nvidia-nim/api-key"),
  clearNvidiaApiKey: () =>
    request<NvidiaApiKeyStatus>("/api/platforms/nvidia-nim/api-key", { method: "DELETE" }),
  startReads: (modelId: string, files: File[], format: OutputFormat) => {
    const form = new FormData();
    for (const file of files) form.append("files", file);
    form.append("model_id", modelId);
    form.append("output_format", format);
    return request<{ reads: ReadSummary[] }>("/api/reads", { method: "POST", body: form });
  },
  listReads: () => request<ReadSummary[]>("/api/reads"),
  getRead: (id: string) => request<ReadDetail>(`/api/reads/${id}`),
  deleteRead: (id: string) => request<void>(`/api/reads/${id}`, { method: "DELETE" }),
  // A plain URL (for <a download>), resolved against the backend like every request.
  readFileUrl: async (id: string) => `${await getBaseUrl()}/api/reads/${id}/file`,
  openRead: (id: string, target: "file" | "folder") =>
    request<void>(`/api/reads/${id}/open?target=${target}`, { method: "POST" }),
};
