import { useEffect, useState, useCallback, useMemo } from "react";
import { CheckCircle2, AlertTriangle, ScanText, Search, RefreshCw, Cloud } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { api, type ModelInfo } from "../lib/api";
import { ENGINE_ICONS, ENGINE_LABELS } from "../lib/engineMeta";
import { languageNames } from "../lib/languages";
import { ModelActions } from "./ModelActions";

function engineIcon(engine: string): LucideIcon {
  return ENGINE_ICONS[engine] ?? ScanText;
}

function ModelCard({
  model,
  onChanged,
}: {
  model: ModelInfo;
  onChanged: () => void;
}) {
  const Icon = engineIcon(model.engine);

  return (
    <div className="flex flex-col rounded-2xl border border-border bg-panel p-5">
      <div className="mb-3 flex items-start gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-accent-pale">
          <Icon className="h-5 w-5 text-accent" strokeWidth={2} />
        </div>
        <div className="min-w-0">
          <div className="truncate font-medium">{model.name}</div>
          <div className="text-xs text-text-muted">{model.engine}</div>
        </div>
      </div>

      <p className="mb-3 line-clamp-3 text-sm text-text-muted">{model.description}</p>

      <div className="mb-4 flex flex-wrap gap-1.5">
        <span className="rounded-full bg-panel-2 px-2 py-0.5 text-xs text-text-muted">
          {languageNames(model.languages)}
        </span>
        {model.fit.fits ? (
          <span className="flex items-center gap-1 rounded-full bg-accent-pale px-2 py-0.5 text-xs font-semibold text-accent">
            <CheckCircle2 className="h-3 w-3" /> Fits this computer
          </span>
        ) : (
          <span
            className="flex items-center gap-1 rounded-full bg-warn-bg px-2 py-0.5 text-xs text-warn"
            title={model.fit.reasons.join("; ")}
          >
            <AlertTriangle className="h-3 w-3" /> May not fit
          </span>
        )}
        {model.engine === "nvidia-nim" && (
          <span
            className="flex items-center gap-1 rounded-full bg-accent-pale px-2 py-0.5 text-xs text-accent"
            title="This model runs in NVIDIA's cloud, not on this device"
          >
            <Cloud className="h-3 w-3" /> Cloud call
          </span>
        )}
      </div>

      <div className="mt-auto">
        <ModelActions model={model} onChanged={onChanged} />
      </div>
    </div>
  );
}

export function ModelsView() {
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [query, setQuery] = useState("");
  const [engineFilter, setEngineFilter] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setModels(await api.listModels());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const engines = useMemo(
    () => Array.from(new Set(models.map((m) => m.engine))).sort(),
    [models],
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return models.filter((m) => {
      if (engineFilter && m.engine !== engineFilter) return false;
      if (!q) return true;
      return (
        m.name.toLowerCase().includes(q) ||
        m.description.toLowerCase().includes(q) ||
        m.languages.some((lang) => lang.toLowerCase().includes(q))
      );
    });
  }, [models, query, engineFilter]);

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <p className="max-w-lg text-sm text-text-muted">
          Every model DocBox can set up. One click installs whatever it needs; models
          that suit this device's RAM and disk are marked as a good fit.
        </p>
        <button
          type="button"
          onClick={() => void refresh()}
          disabled={loading}
          className="flex items-center gap-2 rounded-full border border-border px-4 py-2 text-sm font-medium text-text hover:bg-panel-2 disabled:opacity-50"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      <div className="mb-6 flex flex-wrap items-center gap-3">
        <div className="flex min-w-[220px] flex-1 items-center gap-2 rounded-full border border-border bg-panel px-4 py-2">
          <Search className="h-4 w-4 text-text-muted" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search models or languages…"
            className="w-full bg-transparent text-sm outline-none placeholder:text-text-muted"
          />
        </div>
        <div className="flex flex-wrap gap-1.5">
          <button
            type="button"
            onClick={() => setEngineFilter(null)}
            className={`rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${
              engineFilter === null
                ? "bg-accent text-white"
                : "border border-border text-text-muted hover:bg-panel-2"
            }`}
          >
            All
          </button>
          {engines.map((engine) => (
            <button
              key={engine}
              type="button"
              onClick={() => setEngineFilter(engine === engineFilter ? null : engine)}
              className={`rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${
                engineFilter === engine
                  ? "bg-accent text-white"
                  : "border border-border text-text-muted hover:bg-panel-2"
              }`}
            >
              {ENGINE_LABELS[engine] ?? engine}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="mb-6 flex items-center gap-2 rounded-xl border border-warn/30 bg-warn-bg px-4 py-3 text-sm text-warn">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          Could not reach backend: {error}
        </div>
      )}

      {!error && filtered.length === 0 && (
        <p className="text-sm text-text-muted">No models match your search.</p>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {filtered.map((m) => (
          <ModelCard key={m.id} model={m} onChanged={() => void refresh()} />
        ))}
      </div>
    </div>
  );
}
