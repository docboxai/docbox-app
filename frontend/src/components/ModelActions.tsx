import { useCallback, useState } from "react";
import { CheckCircle2, Download, Loader2, PackagePlus, Trash2 } from "lucide-react";
import { api, type ModelInfo } from "../lib/api";
import { PREREQUISITE_LABELS } from "../lib/engineMeta";

// The single control for a model: one button that says what a click will do (download,
// or install the engine first), live progress for the whole job, and Remove with an
// inline confirm. Shared by the Setup and Models views.
export function ModelActions({ model, onChanged }: { model: ModelInfo; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const [removing, setRemoving] = useState(false);

  const isCloud = model.engine === "nvidia-nim";
  const isOllama = model.engine === "ollama";

  const start = useCallback(async () => {
    setBusy(true);
    setError(null);
    setProgress(0);
    setMessage(null);
    try {
      const { job_id } = await api.startDownload(model.id);
      // eslint-disable-next-line no-constant-condition
      while (true) {
        const status = await api.downloadStatus(model.id, job_id);
        setProgress(status.progress_pct ?? 0);
        setMessage(
          status.state === "installing"
            ? `Installing engine · ${status.message ?? ""}`
            : status.message,
        );
        if (status.state === "done") break;
        if (status.state === "error") {
          setError(status.message ?? "Setup failed");
          break;
        }
        await new Promise((r) => setTimeout(r, 1000));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
      onChanged();
    }
  }, [model.id, onChanged]);

  const remove = useCallback(async () => {
    setRemoving(true);
    setError(null);
    try {
      await api.deleteModel(model.id);
      setConfirmRemove(false);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRemoving(false);
    }
  }, [model.id, onChanged]);

  if (busy) {
    return (
      <div>
        <div
          className="h-2 w-full overflow-hidden rounded-full bg-panel-2"
          role="progressbar"
          aria-valuenow={Math.round(progress)}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={`Setting up ${model.name}`}
        >
          <div
            className="h-full rounded-full bg-accent transition-all"
            style={{ width: `${Math.max(4, progress)}%` }}
          />
        </div>
        <div className="mt-2 flex items-center gap-1.5 text-xs text-text-muted">
          <Loader2 className="h-3 w-3 shrink-0 animate-spin" />
          <span className="truncate">{message ?? "working…"}</span>
          <span className="ml-auto tabular-nums">{Math.round(progress)}%</span>
        </div>
      </div>
    );
  }

  const size = isCloud ? "cloud, nothing to store" : `~${model.approx_download_mb} MB`;

  return (
    <div>
      {confirmRemove ? (
        <div className="flex flex-wrap items-center gap-2 rounded-xl border border-ink px-3 py-2">
          <span className="flex-1 text-sm">
            Remove this model?{" "}
            {!isOllama && `Frees about ${model.approx_download_mb} MB.`}
            {isOllama && "Ollama deletes it from its own store."}
          </span>
          <button
            type="button"
            onClick={() => void remove()}
            disabled={removing}
            className="rounded-full bg-accent px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
          >
            {removing ? "Removing…" : "Remove"}
          </button>
          <button
            type="button"
            onClick={() => setConfirmRemove(false)}
            className="rounded-full border border-border px-3 py-1.5 text-sm text-text hover:bg-panel-2"
          >
            Keep
          </button>
        </div>
      ) : (
        <div className="flex items-center justify-between gap-3">
          <span className="text-xs text-text-muted">{size}</span>
          {model.status === "ready" && (
            <span className="flex items-center gap-3">
              <span className="flex items-center gap-1 text-sm text-accent">
                <CheckCircle2 className="h-4 w-4" /> {isCloud ? "Connected" : "Ready"}
              </span>
              {!isCloud && (
                <button
                  type="button"
                  onClick={() => setConfirmRemove(true)}
                  aria-label={`Remove ${model.name}`}
                  className="flex items-center gap-1 rounded-full border border-border px-2.5 py-1 text-xs text-text-muted hover:bg-panel-2 hover:text-text"
                >
                  <Trash2 className="h-3.5 w-3.5" /> Remove
                </button>
              )}
            </span>
          )}
          {model.status === "needs_download" &&
            (isCloud ? (
              <span className="text-xs text-warn">Add an API key under Connections</span>
            ) : (
              <button
                type="button"
                onClick={() => void start()}
                className="flex items-center gap-1.5 rounded-full bg-accent px-3 py-1.5 text-sm font-medium text-white transition-opacity hover:opacity-90"
              >
                <Download className="h-3.5 w-3.5" /> {isOllama ? "Pull" : "Download"}
              </button>
            ))}
          {model.status === "needs_engine" && (
            <button
              type="button"
              onClick={() => void start()}
              title="Installs this engine's packages once, then downloads the model"
              className="flex items-center gap-1.5 rounded-full bg-accent px-3 py-1.5 text-sm font-medium text-white transition-opacity hover:opacity-90"
            >
              <PackagePlus className="h-3.5 w-3.5" /> Install engine + download
            </button>
          )}
          {model.status === "needs_prerequisite" && (
            <span className="text-xs text-warn">
              Set up {PREREQUISITE_LABELS[model.prerequisite ?? ""] ?? model.prerequisite} first
            </span>
          )}
        </div>
      )}
      {error && <p className="mt-2 text-xs text-warn">{error}</p>}
    </div>
  );
}
