import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowDownRight,
  ArrowLeft,
  ArrowRight,
  Check,
  Download,
  ArrowUpRight,
  Loader,
  Pause,
  Play,
  Plus,
  RefreshCw,
} from "lucide-react";
import { api, type ModelInfo } from "../lib/api";
import { useApp } from "../lib/app";
import {
  ENGINE_BLURBS,
  ENGINE_CAPABILITIES,
  ENGINE_GUIDANCE,
  ENGINE_LABELS,
  ENGINE_ORDER,
  ENGINE_PREREQUISITE,
} from "../lib/engineMeta";
import { formatGb, shortGpu } from "../lib/format";
import { languageNames } from "../lib/languages";
import { useModelJob } from "../lib/useModelJob";
import { ModelSetupPanel, isCloud, sizeLabel } from "./ModelActions";
import { PrerequisiteCard } from "./PrerequisiteCard";
import {
  Button,
  Card,
  CardButton,
  Chip,
  IconAction,
  Notice,
  ProgressBar,
  SectionLabel,
  Spinner,
  StatCard,
  Switch,
  cx,
  type CardTone,
} from "./ui";

type EngineState = "ready" | "needs" | "idle" | "checking";

function engineState(engine: string, variants: ModelInfo[]): { state: EngineState; label: string } {
  if (variants.some((v) => v.status === "ready")) {
    return { state: "ready", label: engine === "nvidia-nim" ? "Connected" : "Ready" };
  }
  if (engine === "nvidia-nim") return { state: "needs", label: "Needs a key" };
  if (variants.some((v) => v.status === "needs_prerequisite")) {
    return { state: "needs", label: engine === "ollama" ? "Needs Ollama" : "Needs setup" };
  }
  return { state: "idle", label: ENGINE_BLURBS[engine] ?? "" };
}

const ENGINE_LOOK: Record<EngineState, { tone: CardTone; action: "ink" | "primary-soft" | "light" }> = {
  ready: { tone: "primary-muted", action: "ink" },
  idle: { tone: "primary-soft", action: "ink" },
  needs: { tone: "surface", action: "primary-soft" },
  checking: { tone: "surface", action: "light" },
};

function EngineCard({
  engine,
  variants,
  checking,
  onOpen,
}: {
  engine: string;
  variants: ModelInfo[];
  checking: boolean;
  onOpen: () => void;
}) {
  const { state, label } = checking
    ? { state: "checking" as const, label: "Checking…" }
    : engineState(engine, variants);
  const look = ENGINE_LOOK[state];
  const name = ENGINE_LABELS[engine] ?? engine;
  const icon = state === "ready" ? Check : state === "needs" ? ArrowDownRight : state === "checking" ? Loader : Plus;
  return (
    <CardButton
      onClick={onOpen}
      aria-label={`${name}: ${label}. Show versions`}
      tone={look.tone}
      label={label}
      value={name}
      valueSize="md"
      icon={icon}
      iconTone={look.action}
      spin={state === "checking"}
      className="min-h-[150px] min-w-[150px] flex-1"
    />
  );
}

function RecommendedCard({ model, onChanged }: { model: ModelInfo; onChanged: () => void }) {
  const { navigate } = useApp();
  const job = useModelJob(model, onChanged);
  const busy = job.phase === "running" || job.phase === "pausing";
  const ready = model.status === "ready" && job.phase === "idle";

  let action;
  if (busy) {
    action = (
      <IconAction
        icon={Pause}
        label={job.phase === "pausing" ? "Pausing after the current step" : "Pause"}
        disabled={job.phase === "pausing"}
        onClick={() => void job.pause()}
      />
    );
  } else if (job.phase === "paused") {
    action = <IconAction icon={Play} label="Resume" onClick={() => void job.start()} />;
  } else if (ready) {
    action = <IconAction icon={Check} label="Installed" />;
  } else {
    // The labelled Install button below is the one way to start; no second control here.
    action = null;
  }

  return (
    <Card tone="secondary-soft" className="flex min-h-[216px] flex-col justify-between gap-4 px-5 pt-4 pb-5">
      <div className="flex items-center justify-between gap-2">
        <div className="flex flex-wrap gap-1.5">
          <Chip>Best for this computer</Chip>
          {busy && <Chip>Installing · {Math.round(job.progress)}%</Chip>}
          {job.phase === "paused" && <Chip>Paused · {Math.round(job.progress)}%</Chip>}
          {ready && <Chip>Installed · {sizeLabel(model)}</Chip>}
        </div>
        {action}
      </div>
      <div className="flex flex-col gap-3">
        <h3 className="font-heading text-[clamp(26px,2.6vw,34px)] leading-[1.1] font-semibold tracking-[-0.6px]">
          {model.name}
        </h3>
        {busy || job.phase === "paused" ? (
          <div className="flex flex-col gap-1.5">
            <ProgressBar value={job.progress} label={`Setting up ${model.name}`} light />
            <div className="flex items-center gap-1.5 text-xs font-medium text-on-light">
              {busy && <Spinner />}
              <span className="truncate">
                {job.phase === "paused"
                  ? "Paused · press resume to pick up where it stopped"
                  : job.phase === "pausing"
                    ? "Pausing after the current step…"
                    : (job.message ?? "Working…")}
              </span>
            </div>
          </div>
        ) : ready ? (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-on-light-muted">Set up and ready. Next, read a file with it.</p>
            <Button variant="ink" size="sm" icon={ArrowRight} onClick={() => navigate("ocr")}>
              Read a file
            </Button>
          </div>
        ) : (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-on-light-muted">
              {model.description} One click sets up everything it needs ({sizeLabel(model)}).
            </p>
            <Button variant="ink" size="sm" icon={Download} onClick={() => void job.start()}>
              Install
            </Button>
          </div>
        )}
        {job.error && <p className="text-xs text-on-light">{job.error}</p>}
      </div>
    </Card>
  );
}

function DeviceCards({ engineReady }: { engineReady: (engine: string) => boolean }) {
  const { caps, settings, updateSettings, navigate } = useApp();
  const cloud = settings?.cloud_enabled ?? false;
  const device = (label: string, value: string, title?: string) => (
    <CardButton
      onClick={() => navigate("device")}
      aria-label={`${label}: ${value}. Open This device`}
      label={label}
      value={value}
      valueTitle={title}
      icon={ArrowUpRight}
      className="min-h-[102px]"
    />
  );
  return (
    <div className="grid grid-cols-2 gap-3">
      {device("Memory", caps ? formatGb(caps.ram_total_gb) : "…")}
      {device("Disk free", caps ? formatGb(caps.disk_free_gb) : "…")}
      {device("Graphics", caps?.gpu_name ? shortGpu(caps.gpu_name) : "CPU only", caps?.gpu_name ?? undefined)}
      <StatCard
        tone="grey"
        label="NVIDIA cloud engine"
        value={cloud ? (engineReady("nvidia-nim") ? "On" : "On · no key") : "Off"}
        action={
          <Switch
            label="Cloud engine: allow NVIDIA's cloud models"
            checked={cloud}
            disabled={!settings}
            onChange={(next) => void updateSettings({ cloud_enabled: next })}
          />
        }
        className="min-h-[102px]"
      />
    </div>
  );
}


// The version an engine's page opens on: the recommended one, else the first that fits.
function defaultVariant(variants: ModelInfo[]): string {
  return (variants.find((v) => v.recommended) ?? variants.find((v) => v.fit.fits) ?? variants[0])?.id ?? "";
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
  const { navigate, settings } = useApp();
  const prerequisite = ENGINE_PREREQUISITE[engine];
  const [selectedId, setSelectedId] = useState<string>(() => defaultVariant(variants));
  useEffect(() => {
    if (!variants.some((v) => v.id === selectedId)) {
      setSelectedId(defaultVariant(variants));
    }
  }, [variants, selectedId]);
  const selected = variants.find((v) => v.id === selectedId) ?? null;

  return (
    <div className="flex flex-col gap-4">
      <div>
        <Button variant="ghost" size="sm" icon={ArrowLeft} onClick={onBack}>
          All engines
        </Button>
      </div>
      <div className="flex flex-wrap items-stretch gap-4">
        <Card className="flex min-w-0 flex-[1_1_420px] flex-col gap-2 px-5 py-4">
          <h2 className="font-heading text-[34px] leading-[1.1] font-semibold tracking-[-0.6px]">
            {ENGINE_LABELS[engine] ?? engine}
          </h2>
          <p className="max-w-[62ch] leading-relaxed text-fg-muted">{ENGINE_CAPABILITIES[engine]}</p>
        </Card>
        <Card tone="primary-soft" as="aside" className="flex flex-[1_1_320px] flex-col gap-1.5 px-5 py-4">
          <h3 className="font-heading text-lg font-semibold">Which one do I need?</h3>
          <p className="leading-relaxed text-on-light-muted">{ENGINE_GUIDANCE[engine]}</p>
        </Card>
      </div>

      {prerequisite && <PrerequisiteCard id={prerequisite} onReady={onChanged} />}

      {variants.length === 0 ? (
        <Card className="flex flex-wrap items-center justify-between gap-3 px-5 py-4 text-fg-muted">
          {engine === "nvidia-nim"
            ? settings?.cloud_enabled
              ? "Not connected. Add an API key under Connections to see models here."
              : "The cloud engine is switched off. Switch it on, then add an API key under Connections."
            : "No versions available."}
          {engine === "nvidia-nim" && (
            <Button size="sm" variant="outline" onClick={() => navigate("platforms")}>
              Open Connections
            </Button>
          )}
        </Card>
      ) : (
        <div className="flex flex-wrap items-start gap-4">
          <section aria-labelledby="versions-label" className="flex min-w-0 flex-[999_1_480px] flex-col gap-2.5">
            <SectionLabel id="versions-label">Versions</SectionLabel>
            <Card as="div" className="overflow-hidden">
              <ul>
                {variants.map((v) => {
                  const isSelected = v.id === selectedId;
                  return (
                    <li key={v.id} className="border-b border-line last:border-b-0">
                      <button
                        type="button"
                        aria-pressed={isSelected}
                        onClick={() => setSelectedId(v.id)}
                        className={cx(
                          // The list's card clips (rounded corners), so keep the focus ring inside.
                          "flex min-h-14 w-full items-center gap-3 px-4 text-left transition-colors focus-visible:outline-offset-[-2px]",
                          isSelected ? "bg-line/70" : "hover:bg-line/40",
                        )}
                      >
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm font-medium">{v.name}</span>
                          <span className="block truncate text-[13px] text-fg-muted">
                            {languageNames(v.languages)}
                          </span>
                        </span>
                        <Chip tone={v.fit.fits && v.fit.notes.length === 0 ? "success" : "warning"} title={[...v.fit.reasons, ...v.fit.notes].join("; ") || undefined}>
                          {v.recommended ? "Best for this computer" : v.fit.summary}
                        </Chip>
                        <span className="w-16 text-right text-[13px] text-fg-muted tabular-nums">{sizeLabel(v)}</span>
                        {v.status === "ready" && (
                          <Check aria-label="Installed" className="h-4 w-4 shrink-0 text-secondary" />
                        )}
                      </button>
                    </li>
                  );
                })}
              </ul>
            </Card>
          </section>

          {selected && <SelectedVersion key={selected.id} model={selected} onChanged={onChanged} />}
        </div>
      )}
    </div>
  );
}

function SelectedVersion({ model, onChanged }: { model: ModelInfo; onChanged: () => void }) {
  const job = useModelJob(model, onChanged);
  return (
    <section aria-label="Selected version" className="flex flex-[1_1_340px] flex-col gap-2.5">
      <SectionLabel>Selected</SectionLabel>
      <Card tone="secondary-soft" className="flex flex-col gap-3 px-5 pt-4 pb-5">
        <h3 className="font-heading text-[24px] leading-[1.15] font-semibold tracking-[-0.4px]">{model.name}</h3>
        <p className="text-sm leading-relaxed text-on-light-muted">{model.description}</p>
        {!model.fit.fits && (
          <p className="text-sm font-medium text-on-light">May not fit: {model.fit.reasons.join("; ")}</p>
        )}
        {isCloud(model) && (
          <p className="text-sm font-medium text-on-light">Runs in NVIDIA's cloud: images you read with it leave this computer.</p>
        )}
        <ModelSetupPanel model={model} job={job} light />
      </Card>
    </section>
  );
}

export function SetupView() {
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [selectedEngine, setSelectedEngine] = useState<string | null>(null);
  const { revision, bump } = useApp();

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setModels(await api.listModels());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh, revision]);

  const grouped = useMemo(() => {
    const byEngine = new Map<string, ModelInfo[]>();
    for (const engine of ENGINE_ORDER) byEngine.set(engine, []);
    for (const m of models) {
      if (!byEngine.has(m.engine)) byEngine.set(m.engine, []);
      byEngine.get(m.engine)!.push(m);
    }
    return byEngine;
  }, [models]);

  const recommended = models.find((m) => m.recommended);
  // The revision bump refetches this view (effect above) and the hero's numbers.
  const onChanged = bump;
  const engineReady = (engine: string) => (grouped.get(engine) ?? []).some((m) => m.status === "ready");

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
    <div className="flex flex-col gap-4">
      {error && <Notice>Couldn't reach DocBox's engine: {error}</Notice>}

      <div className="flex flex-wrap items-end gap-4">
        <section aria-labelledby="recommended-label" className="flex min-w-0 flex-[1_1_440px] flex-col gap-2.5">
          <SectionLabel id="recommended-label">Recommended start</SectionLabel>
          {recommended ? (
            <RecommendedCard model={recommended} onChanged={onChanged} />
          ) : (
            <Card tone="secondary-soft" className="flex min-h-[216px] items-center justify-center text-on-light-muted">
              {loaded ? (
                <p className="max-w-[36ch] px-6 text-center">
                  {error
                    ? "Unable to check which model suits this computer."
                    : "No model runs smoothly on this computer right now. Free up memory or disk space, then refresh."}
                </p>
              ) : (
                <Spinner className="h-6 w-6" />
              )}
            </Card>
          )}
        </section>
        <section aria-labelledby="device-label" className="flex min-w-0 flex-[0_1_580px] flex-col gap-2.5 max-[1180px]:flex-[1_1_440px]">
          <SectionLabel id="device-label">This device</SectionLabel>
          <DeviceCards engineReady={engineReady} />
        </section>
      </div>

      <section aria-labelledby="engines-label" className="flex flex-col gap-2.5">
        <div className="flex items-center justify-between gap-3">
          <SectionLabel id="engines-label">All engines</SectionLabel>
          <Button
            variant="ghost"
            size="sm"
            icon={loading ? undefined : RefreshCw}
            onClick={() => void refresh()}
            disabled={loading}
          >
            {loading && <Spinner />}
            Refresh
          </Button>
        </div>
        <div className="flex flex-wrap gap-3">
          {ENGINE_ORDER.map((engine) => (
            <EngineCard
              key={engine}
              engine={engine}
              variants={grouped.get(engine) ?? []}
              checking={!loaded}
              onOpen={() => setSelectedEngine(engine)}
            />
          ))}
        </div>
      </section>
    </div>
  );
}
