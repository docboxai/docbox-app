import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, ArrowLeft, Check, Loader2, Plus, RefreshCw } from "lucide-react";
import { api, type ModelInfo } from "../lib/api";
import {
  ENGINE_BLURBS,
  ENGINE_CAPABILITIES,
  ENGINE_GUIDANCE,
  ENGINE_LABELS,
  ENGINE_ORDER,
  ENGINE_PREREQUISITE,
  RECOMMENDED_MODEL_ID,
} from "../lib/engineMeta";
import { languageNames } from "../lib/languages";
import { ModelActions } from "./ModelActions";
import { Chevrons } from "./Poster";
import { PrerequisiteCard } from "./PrerequisiteCard";
import { StoragePanel } from "./StoragePanel";

type EngineState = "ready" | "needs" | "idle";

function engineState(engine: string, variants: ModelInfo[]): { state: EngineState; label: string } {
  if (variants.some((v) => v.status === "ready")) {
    return { state: "ready", label: engine === "nvidia-nim" ? "Connected" : "Ready" };
  }
  if (engine === "nvidia-nim") return { state: "needs", label: "Needs a key" };
  if (variants.some((v) => v.status === "needs_prerequisite")) {
    return { state: "needs", label: engine === "ollama" ? "Needs Ollama" : "Needs setup" };
  }
  return { state: "idle", label: "Not set up yet" };
}

function StatusIcon({ state }: { state: EngineState }) {
  if (state === "ready") {
    return (
      <span aria-hidden="true" className="flex h-[30px] w-[30px] items-center justify-center rounded-full bg-accent-bright">
        <Check className="h-4 w-4 text-white" strokeWidth={3} />
      </span>
    );
  }
  if (state === "needs") {
    return (
      <span aria-hidden="true" className="flex h-[30px] w-[30px] items-center justify-center rounded-full bg-ink">
        <svg width="14" height="14" viewBox="0 0 14 14">
          <path d="M3 3 L11 11 M11 5 V11 H5" fill="none" stroke="#fff" strokeWidth="2" />
        </svg>
      </span>
    );
  }
  return (
    <span aria-hidden="true" className="flex h-[30px] w-[30px] items-center justify-center rounded-full border-2 border-ink">
      <Plus className="h-3.5 w-3.5" strokeWidth={3} />
    </span>
  );
}

function EngineCard({
  engine,
  variants,
  checking,
  onClick,
}: {
  engine: string;
  variants: ModelInfo[];
  checking: boolean;
  onClick: () => void;
}) {
  const { state, label } = engineState(engine, variants);
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex min-h-32 flex-col justify-between gap-4 rounded-2xl border border-border bg-panel p-4.5 text-left transition-colors hover:border-ink"
    >
      <span className="flex items-center justify-between gap-2">
        {checking ? (
          <span aria-hidden="true" className="flex h-[30px] w-[30px] items-center justify-center rounded-full border-2 border-border">
            <Loader2 className="h-3.5 w-3.5 animate-spin text-text-muted" />
          </span>
        ) : (
          <StatusIcon state={state} />
        )}
        <span className="text-[13px] font-medium text-text-muted">{checking ? "Checking…" : label}</span>
      </span>
      <span>
        <span className="block text-lg font-bold">{ENGINE_LABELS[engine] ?? engine}</span>
        <span className="mt-0.5 block text-[13px] text-text-muted">{ENGINE_BLURBS[engine]}</span>
      </span>
    </button>
  );
}

function RecommendedHero({ model, onChanged }: { model: ModelInfo; onChanged: () => void }) {
  return (
    <section
      aria-label="Recommended model"
      className="relative mb-8 flex flex-col gap-5 overflow-hidden rounded-[18px] bg-accent-pale px-7 py-6 sm:flex-row sm:items-center"
    >
      <div aria-hidden="true" className="halftone absolute -right-2 bottom-0 h-full w-[46%] opacity-35" />
      <div aria-hidden="true" className="skyline-light absolute right-0 bottom-0 h-[42%] w-[30%] bg-accent-light" />
      <div aria-hidden="true" className="skyline-dark absolute right-0 bottom-0 h-[26%] w-[18%] bg-accent-bright" />
      <div className="relative min-w-0 flex-1">
        <span className="rounded-full bg-ink px-2.5 py-1 font-mono text-[11px] font-bold tracking-wider text-white">
          RECOMMENDED START
        </span>
        <div className="mt-3 text-2xl font-extrabold tracking-tight">{model.name}</div>
        <div className="mt-1 text-text/80">
          Small and fast on any computer. One click sets up everything it needs.
        </div>
      </div>
      <div className="relative rounded-2xl bg-panel/90 p-3 sm:w-80">
        <ModelActions model={model} onChanged={onChanged} />
      </div>
    </section>
  );
}

function EngineDetail({
  engine,
  variants,
  onBack,
  onChanged,
}: {
  engine: string;
  variants: ModelInfo[];
  onBack: () => void;
  onChanged: () => void;
}) {
  const prerequisite = ENGINE_PREREQUISITE[engine];

  const [selectedId, setSelectedId] = useState<string>(
    () => (variants.find((v) => v.fit.fits) ?? variants[0])?.id ?? "",
  );
  useEffect(() => {
    if (!variants.some((v) => v.id === selectedId)) {
      setSelectedId((variants.find((v) => v.fit.fits) ?? variants[0])?.id ?? "");
    }
  }, [variants, selectedId]);
  const selected = variants.find((v) => v.id === selectedId) ?? null;

  return (
    <div>
      <button
        type="button"
        onClick={onBack}
        className="mb-5 flex min-h-11 items-center gap-2 font-semibold text-text/80 hover:text-text"
      >
        <ArrowLeft className="h-4 w-4" strokeWidth={2.5} /> All engines
      </button>

      <div className="mb-6 flex flex-wrap items-stretch gap-6">
        <div className="min-w-0 flex-[1_1_420px]">
          <h2 className="text-[34px] font-extrabold tracking-tight">{ENGINE_LABELS[engine] ?? engine}</h2>
          <p className="mt-2 max-w-[58ch] leading-relaxed text-text/80">{ENGINE_CAPABILITIES[engine]}</p>
        </div>
        <aside className="relative flex-[1_1_320px] overflow-hidden rounded-2xl bg-accent-pale px-5 py-4">
          <div aria-hidden="true" className="halftone absolute -top-1.5 -right-1.5 h-24 w-24 opacity-40" />
          <div className="relative mb-1.5 font-bold">Which one do I need?</div>
          <p className="relative leading-relaxed text-text/80">{ENGINE_GUIDANCE[engine]}</p>
        </aside>
      </div>

      {prerequisite && (
        <div className="mb-6 max-w-2xl">
          <PrerequisiteCard id={prerequisite} onReady={onChanged} />
        </div>
      )}

      {variants.length === 0 ? (
        <p className="text-text-muted">
          {engine === "nvidia-nim"
            ? "Not connected. Add an API key under Connections to see models here."
            : "No versions available."}
        </p>
      ) : (
        <div className="flex flex-wrap items-start gap-5">
          <section aria-label="Versions" className="flex min-w-0 flex-[999_1_480px] flex-col gap-2">
            <h3 className="mb-1 text-lg font-bold">Versions</h3>
            {variants.map((v) => {
              const isSelected = v.id === selectedId;
              return (
                <button
                  key={v.id}
                  type="button"
                  aria-pressed={isSelected}
                  onClick={() => setSelectedId(v.id)}
                  className={`flex min-h-14 items-center gap-3.5 rounded-[14px] bg-panel px-4.5 text-left ${
                    isSelected ? "border-2 border-ink" : "border border-border hover:border-ink"
                  }`}
                >
                  <span className="min-w-0 flex-1">
                    <span className={`block ${isSelected ? "font-bold" : "font-semibold"}`}>{v.name}</span>
                    <span className="block text-[13px] text-text-muted">
                      {languageNames(v.languages)}
                      {!v.fit.fits && " · may not fit this computer"}
                    </span>
                  </span>
                  <span className="font-mono text-[13px] font-bold">
                    {v.engine === "nvidia-nim" ? "cloud" : `${v.approx_download_mb} MB`}
                  </span>
                  {v.status === "ready" && (
                    <span className="rounded-full bg-accent-pale px-2.5 py-0.5 text-xs font-bold text-accent">
                      Ready
                    </span>
                  )}
                </button>
              );
            })}
          </section>

          {selected && (
            <section
              aria-label="Selected version"
              className="flex flex-[1_1_340px] flex-col gap-3.5 rounded-[18px] border border-border bg-panel-2 p-5.5"
            >
              <div className="font-mono text-xs font-bold tracking-widest text-accent">SELECTED</div>
              <div className="text-xl leading-snug font-extrabold">{selected.name}</div>
              <div className="flex flex-wrap gap-1.5">
                {selected.fit.fits ? (
                  <span className="rounded-full bg-accent-pale px-2.5 py-0.5 text-[13px] font-bold text-accent">
                    Fits this computer
                  </span>
                ) : (
                  <span
                    className="flex items-center gap-1 rounded-full bg-warn-bg px-2.5 py-0.5 text-[13px] font-bold text-warn"
                    title={selected.fit.reasons.join("; ")}
                  >
                    <AlertTriangle className="h-3.5 w-3.5" /> May not fit this computer
                  </span>
                )}
              </div>
              <p className="text-sm leading-relaxed text-text-muted">{selected.description}</p>
              <ModelActions key={selected.id} model={selected} onChanged={onChanged} />
            </section>
          )}
        </div>
      )}
    </div>
  );
}

export function SetupView() {
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [selectedEngine, setSelectedEngine] = useState<string | null>(null);
  const [storageKey, setStorageKey] = useState(0);
  // Until the first answer arrives, show "Checking…" rather than statuses derived from
  // an empty list (which would wrongly read "Not set up yet").
  const [loaded, setLoaded] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setModels(await api.listModels());
      setStorageKey((k) => k + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const grouped = useMemo(() => {
    const byEngine = new Map<string, ModelInfo[]>();
    for (const engine of ENGINE_ORDER) byEngine.set(engine, []);
    for (const m of models) {
      if (!byEngine.has(m.engine)) byEngine.set(m.engine, []);
      byEngine.get(m.engine)!.push(m);
    }
    return byEngine;
  }, [models]);

  const recommended = models.find((m) => m.id === RECOMMENDED_MODEL_ID);
  const onChanged = useCallback(() => void refresh(), [refresh]);

  if (selectedEngine) {
    return (
      <EngineDetail
        engine={selectedEngine}
        variants={grouped.get(selectedEngine) ?? []}
        onBack={() => setSelectedEngine(null)}
        onChanged={onChanged}
      />
    );
  }

  return (
    <div>
      <div className="mb-7 flex flex-wrap items-end justify-between gap-4">
        <p className="max-w-[56ch] leading-relaxed text-text-muted">
          Pick an engine. DocBox installs whatever it needs and keeps everything on this
          computer.
        </p>
        <div className="flex items-center gap-4">
          <Chevrons colors={["#afcdf4", "#2f7de1", "#0b0b0c", "#0b0b0c"]} />
          <button
            type="button"
            onClick={() => void refresh()}
            disabled={loading}
            aria-label="Refresh"
            className="flex h-11 w-11 items-center justify-center rounded-full border border-border hover:bg-accent-pale disabled:opacity-50"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-6 flex items-center gap-2 rounded-xl border border-warn/30 bg-warn-bg px-4 py-3 text-sm text-warn">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          Couldn't reach DocBox's engine: {error}
        </div>
      )}

      {recommended && recommended.status !== "ready" && (
        <RecommendedHero model={recommended} onChanged={onChanged} />
      )}

      <div className="mb-3.5 flex flex-wrap items-baseline justify-between gap-3">
        <h2 className="text-lg font-bold">All engines</h2>
        <span className="text-[13px] text-text-muted">
          4 run on this computer · 1 through Ollama · 1 in the cloud
        </span>
      </div>
      <div className="mb-8 grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-3">
        {ENGINE_ORDER.map((engine) => (
          <EngineCard
            key={engine}
            engine={engine}
            variants={grouped.get(engine) ?? []}
            checking={!loaded}
            onClick={() => setSelectedEngine(engine)}
          />
        ))}
      </div>

      <StoragePanel refreshKey={storageKey} onChanged={onChanged} />
    </div>
  );
}
