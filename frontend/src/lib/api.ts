import { invoke } from "@tauri-apps/api/core";

export interface DeviceCapabilities {
  ram_total_gb: number;
  ram_available_gb: number;
  cpu_physical_cores: number;
  cpu_logical_cores: number;
  disk_free_gb: number;
}

export interface FitResult {
  fits: boolean;
  reasons: string[];
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
}

export type DownloadState = "pending" | "installing" | "downloading" | "done" | "error";

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
}

export interface OcrResult {
  model_id: string;
  lines: OcrLine[];
  text: string;
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
  engines: EngineStorage[];
}

export interface EngineRemoveResult {
  removed: boolean;
  pending_restart: boolean;
  detail: string;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1e6) return `${Math.round(bytes / 1e3)} KB`;
  if (bytes < 1e9) return `${Math.round(bytes / 1e6)} MB`;
  return `${(bytes / 1e9).toFixed(1)} GB`;
}

let baseUrlPromise: Promise<string> | null = null;

// Falls back to the backend's default port when not running inside the Tauri
// webview (e.g. `npm run dev` opened directly in a browser for UI iteration).
async function getBaseUrl(): Promise<string> {
  if (!baseUrlPromise) {
    baseUrlPromise =
      "__TAURI_INTERNALS__" in window
        ? invoke<string>("backend_base_url").catch((err) => {
            // Not ready yet (or restarted after Retry): don't cache the failure.
            baseUrlPromise = null;
            throw err;
          })
        : Promise.resolve("http://127.0.0.1:8756");
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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const base = await getBaseUrl();
  const resp = await fetch(`${base}${path}`, init);
  if (!resp.ok) throw new Error(await errorMessage(resp));
  if (resp.status === 204) return undefined as T;
  return resp.json() as Promise<T>;
}

export const api = {
  health: () => request<{ status: string }>("/api/health"),
  deviceCapabilities: () => request<DeviceCapabilities>("/api/device/capabilities"),
  listModels: () => request<ModelInfo[]>("/api/models"),
  startDownload: (modelId: string) =>
    request<{ job_id: string }>(`/api/models/${modelId}/download`, { method: "POST" }),
  downloadStatus: (modelId: string, jobId: string) =>
    request<DownloadStatus>(
      `/api/models/${modelId}/download/status?job_id=${encodeURIComponent(jobId)}`,
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
  uninstallEngine: (id: string) =>
    request<EngineRemoveResult>(`/api/engines/${id}`, { method: "DELETE" }),
  listPlatforms: () => request<PlatformStatus[]>("/api/platforms"),
  setNvidiaApiKey: (apiKey: string) =>
    request<NvidiaApiKeyStatus>("/api/platforms/nvidia-nim/api-key", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key: apiKey }),
    }),
  clearNvidiaApiKey: () =>
    request<NvidiaApiKeyStatus>("/api/platforms/nvidia-nim/api-key", { method: "DELETE" }),
  runOcr: async (modelId: string, file: File, page = 0): Promise<OcrResult> => {
    const base = await getBaseUrl();
    const form = new FormData();
    form.append("file", file);
    form.append("model_id", modelId);
    form.append("page", String(page));
    const resp = await fetch(`${base}/api/ocr/run`, { method: "POST", body: form });
    if (!resp.ok) throw new Error(await errorMessage(resp));
    return resp.json() as Promise<OcrResult>;
  },
};
