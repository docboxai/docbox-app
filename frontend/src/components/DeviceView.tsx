import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { relaunch } from "@tauri-apps/plugin-process";
import { ChevronDown, RefreshCw } from "lucide-react";
import {
  api,
  type DeviceCapabilities,
  type DevicePreference,
  type DownloadStatus,
  type EngineGpuBuild,
  type GpuStatus,
} from "../lib/api";
import { useApp } from "../lib/app";
import { formatGb, formatMb, shortGpu } from "../lib/format";
import { IN_TAURI } from "../lib/host";
import { Button, Card, Notice, ProgressBar, SectionLabel, Spinner, StatCard, Switch } from "./ui";

// What reads fastest on this computer, from its hardware.
function speedAdvice(caps: DeviceCapabilities, gpu: GpuStatus | null): string {
  const onCard = gpu?.engines.find((e) => e.installed === "gpu");
  if (caps.gpu_memory_gb && onCard) {
    return (
      `${onCard.name.replace(/ engine.*$/, "")} reads on your ${shortGpu(caps.gpu_name ?? "graphics card")}, ` +
      "and so do Ollama's models. PaddleOCR Mobile and Tesseract stay on the processor, where " +
      "they're quick anyway."
    );
  }
  if (caps.gpu_memory_gb) {
    return (
      `Ollama models read on your ${shortGpu(caps.gpu_name ?? "graphics card")} (${formatGb(caps.gpu_memory_gb)}), ` +
      "the fastest way to run the large vision models here. DocBox's own models read on the " +
      `${caps.cpu_physical_cores}-core processor: PaddleOCR Mobile is quickest on it, and the ` +
      "larger PaddleOCR models read several times faster on the graphics card" +
      (gpu?.usable ? " once you switch PaddleOCR to it below." : ".")
    );
  }
  return (
    `DocBox's models read on the ${caps.cpu_physical_cores}-core processor. Without an NVIDIA ` +
    "graphics card, PaddleOCR Mobile is the quickest choice, and large vision models in " +
    "Ollama will be slow."
  );
}

// Whole and half gigabytes, from 1 GB up to all of this computer's memory.
function RamLimit({ totalGb }: { totalGb: number }) {
  const { settings, updateSettings } = useApp();
  const saved = settings?.ram_limit_gb ?? null;
  const max = Math.max(1, Math.floor(totalGb * 2) / 2);
  const [draft, setDraft] = useState<number | null>(null);
  const value = Math.min(draft ?? saved ?? max, max);

  // Saved once the slider rests, not at every step of a drag.
  useEffect(() => {
    if (draft === null || draft === saved) return;
    const timer = setTimeout(() => void updateSettings({ ram_limit_gb: draft }), 400);
    return () => clearTimeout(timer);
  }, [draft, saved, updateSettings]);

  const toggle = (on: boolean) => {
    setDraft(null);
    void updateSettings({ ram_limit_gb: on ? Math.min(max, Math.max(1, Math.round(totalGb / 2))) : 0 });
  };

  return (
    <section aria-labelledby="ram-limit-label" className="flex flex-col gap-2.5">
      <SectionLabel id="ram-limit-label">Memory limit</SectionLabel>
      <Card className="flex flex-col gap-3 px-5 pt-4 pb-[18px]">
        <div className="flex items-start justify-between gap-4">
          <p className="max-w-[64ch] text-sm leading-relaxed text-fg-muted">
            The most memory a model may take while it reads. Models over it aren't recommended,
            and DocBox won't start a read with one, so other apps keep what they need.
          </p>
          <Switch checked={saved !== null} onChange={toggle} label="Limit how much memory a model may take" />
        </div>
        {saved !== null && (
          <div className="flex items-center gap-4">
            <input
              type="range"
              min={1}
              max={max}
              step={0.5}
              value={value}
              aria-label="Memory limit"
              aria-valuetext={formatGb(value)}
              onChange={(e) => setDraft(Number(e.target.value))}
              className="w-full accent-secondary"
            />
            <span className="w-16 shrink-0 text-right text-sm font-medium tabular-nums">{formatGb(value)}</span>
          </div>
        )}
      </Card>
    </section>
  );
}

const PREFERENCES: { value: DevicePreference; label: string }[] = [
  { value: "auto", label: "Automatic: the models that read best on it" },
  { value: "gpu", label: "Every model that can" },
  { value: "cpu", label: "None: always the processor" },
];

async function restartDocBox() {
  // Stops the backend first, as an update does; the next start applies the switch.
  await invoke("prepare_restart");
  await relaunch();
}

// One engine's build: switching to the graphics card asks first, with the download size.
function EngineBuildRow({ engine, onChanged }: { engine: EngineGpuBuild; onChanged: () => void }) {
  const [confirming, setConfirming] = useState(false);
  const [job, setJob] = useState<DownloadStatus | null>(engine.job);
  const [result, setResult] = useState<{ text: string; error: boolean } | null>(null);
  const running = job !== null && job.state !== "done" && job.state !== "error";

  useEffect(() => {
    if (!running || !job) return;
    const timer = setInterval(async () => {
      try {
        const next = await api.engineBuildStatus(job.job_id);
        setJob(next);
        if (next.state === "done" || next.state === "error") {
          setResult({ text: next.message ?? "", error: next.state === "error" });
          setJob(null);
          onChanged();
        }
      } catch (err) {
        setResult({ text: err instanceof Error ? err.message : String(err), error: true });
        setJob(null);
      }
    }, 1000);
    return () => clearInterval(timer);
  }, [running, job, onChanged]);

  const start = async (build: "cpu" | "gpu") => {
    setConfirming(false);
    setResult(null);
    try {
      setJob(await api.switchEngineBuild(engine.id, build));
    } catch (err) {
      setResult({ text: err instanceof Error ? err.message : String(err), error: true });
    }
  };

  const onCard = engine.installed === "gpu";
  const size = formatMb(engine.gpu_download_mb);
  return (
    <div className="flex flex-col gap-2 border-t border-line pt-3 first:border-t-0 first:pt-0">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-medium">{engine.name}</p>
          <p className="text-[13px] text-fg-muted">
            {engine.pending_restart
              ? "Switches the next time DocBox starts."
              : onCard
                ? "Graphics-card build installed."
                : engine.installed
                  ? "Processor build installed."
                  : "Not installed yet."}
          </p>
        </div>
        {engine.pending_restart ? (
          IN_TAURI && (
            <Button size="sm" variant="outline" onClick={() => void restartDocBox()}>
              Restart DocBox
            </Button>
          )
        ) : running ? null : onCard ? (
          <Button size="sm" variant="outline" onClick={() => void start("cpu")}>
            Use the processor instead
          </Button>
        ) : confirming ? (
          <div className="flex items-center gap-2">
            <Button size="sm" onClick={() => void start("gpu")}>
              Download {size}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
          </div>
        ) : (
          <Button size="sm" variant="outline" disabled={engine.blocked !== null} onClick={() => setConfirming(true)}>
            Use the graphics card · {size}
          </Button>
        )}
      </div>
      {confirming && (
        <p className="max-w-[70ch] text-[13px] leading-relaxed text-fg-muted">
          DocBox downloads {engine.name.replace(/ engine.*$/, "")}'s build for NVIDIA graphics
          cards, NVIDIA's CUDA libraries included, and installs it in place of the processor build.
          Your models stay, and read on the card from the next read.
        </p>
      )}
      {!onCard && engine.blocked && !running && (
        <p className="text-[13px] text-fg-muted">{engine.blocked}</p>
      )}
      {running && job && (
        <div className="flex flex-col gap-1.5">
          <ProgressBar value={job.progress_pct ?? 0} label={`Installing ${engine.name}`} />
          <p className="truncate text-[13px] text-fg-muted">{job.message ?? "Starting"}</p>
        </div>
      )}
      {result && <p className={result.error ? "text-[13px] text-danger" : "text-[13px] text-fg-muted"}>{result.text}</p>}
    </div>
  );
}

function GraphicsCard({ gpu, onChanged }: { gpu: GpuStatus | null; onChanged: () => void }) {
  const { settings, updateSettings } = useApp();
  if (!gpu) return null;
  const free = gpu.memory_free_gb !== null ? `, ${formatGb(gpu.memory_free_gb)} free` : "";
  return (
    <section aria-labelledby="gpu-label" className="flex flex-col gap-2.5">
      <SectionLabel id="gpu-label">Graphics card</SectionLabel>
      <Card className="flex flex-col gap-4 px-5 pt-4 pb-[18px]">
        {gpu.name && (
          <p className="text-sm leading-relaxed text-fg-muted">
            <span className="font-medium text-fg">{shortGpu(gpu.name)}</span>
            {gpu.memory_total_gb !== null && ` · ${formatGb(gpu.memory_total_gb)}${free}`}
            {gpu.driver_version && ` · driver ${gpu.driver_version}`}
            {gpu.cuda_version && ` · CUDA ${gpu.cuda_version}`}
          </p>
        )}
        {!gpu.usable ? (
          <p className="max-w-[70ch] text-sm leading-relaxed text-fg-muted">
            {gpu.reason} DocBox's own models read on the processor.
          </p>
        ) : (
          <>
            <p className="max-w-[70ch] text-sm leading-relaxed text-fg-muted">
              PaddleOCR or EasyOCR can read on this card, several times faster for the larger
              models, once its graphics-card build is installed. One engine at a time can use
              it. If the card fails to start or runs out of memory, the model reads on the
              processor and its details say why.
            </p>
            <label className="relative flex flex-wrap items-center gap-3 text-sm">
              <span className="text-fg-muted">Models that read on it</span>
              <select
                value={settings?.device_preference ?? "auto"}
                onChange={(e) => void updateSettings({ device_preference: e.target.value as DevicePreference })}
                className="h-9 appearance-none rounded-xl bg-surface pr-9 pl-3 text-sm ring-1 ring-line ring-inset outline-none focus:ring-secondary"
              >
                {PREFERENCES.map((p) => (
                  <option key={p.value} value={p.value}>
                    {p.label}
                  </option>
                ))}
              </select>
              <ChevronDown aria-hidden="true" className="pointer-events-none absolute right-3 bottom-2.5 h-4 w-4 text-fg-muted" />
            </label>
          </>
        )}
        {(gpu.usable || gpu.engines.some((e) => e.installed === "gpu")) && (
          <div className="flex flex-col gap-3">
            {gpu.engines.map((engine) => (
              <EngineBuildRow key={engine.id} engine={engine} onChanged={onChanged} />
            ))}
          </div>
        )}
      </Card>
    </section>
  );
}

export function DeviceView() {
  const { caps, refreshCaps, revision, bump } = useApp();
  const [loading, setLoading] = useState(false);
  const [gpu, setGpu] = useState<GpuStatus | null>(null);

  const loadGpu = useCallback(async () => {
    try {
      setGpu(await api.gpuStatus());
    } catch {
      setGpu(null);
    }
  }, []);

  useEffect(() => {
    void loadGpu();
  }, [loadGpu, revision]);

  const refresh = async () => {
    setLoading(true);
    await Promise.all([refreshCaps(), loadGpu()]);
    setLoading(false);
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-[64ch] text-sm leading-relaxed text-fg-muted">
          DocBox compares this with what each model needs, so it can tell you which ones will
          run comfortably here.
        </p>
        <Button variant="outline" size="sm" icon={loading ? undefined : RefreshCw} disabled={loading} onClick={() => void refresh()}>
          {loading && <Spinner />}
          Refresh
        </Button>
      </div>

      {!caps ? (
        loading ? null : <Notice>Couldn't reach DocBox's engine to read this computer's hardware.</Notice>
      ) : (
        <>
          <section aria-labelledby="hardware-label" className="flex flex-col gap-2.5">
            <SectionLabel id="hardware-label">Hardware</SectionLabel>
            <div className="grid grid-cols-[repeat(auto-fill,minmax(240px,1fr))] gap-3">
              <StatCard
                tone="secondary-soft"
                label="Free memory"
                value={formatGb(caps.ram_available_gb)}
                sub={`of ${formatGb(caps.ram_total_gb)} total`}
                className="min-h-[124px]"
              />
              <StatCard
                tone="primary-soft"
                label="Processor"
                value={`${caps.cpu_physical_cores} cores`}
                sub={`${caps.cpu_logical_cores} threads`}
                className="min-h-[124px]"
              />
              <StatCard
                tone="primary-muted"
                label="Free disk"
                value={formatGb(caps.disk_free_gb)}
                sub={`of ${formatGb(caps.disk_total_gb)}, for models`}
                className="min-h-[124px]"
              />
              <StatCard
                label="Graphics"
                value={caps.gpu_name ? <span title={caps.gpu_name}>{shortGpu(caps.gpu_name)}</span> : "CPU only"}
                valueSize="sm"
                sub={
                  gpu?.engines.some((e) => e.installed === "gpu")
                    ? `${formatGb(caps.gpu_memory_gb ?? 0)} · reads models`
                    : caps.gpu_memory_gb
                      ? `${formatGb(caps.gpu_memory_gb)} · used by Ollama`
                      : "DocBox's own engines read on the CPU"
                }
                className="min-h-[124px]"
              />
              <StatCard
                label="System"
                value={caps.os_name}
                valueSize="sm"
                sub={caps.arch}
                className="min-h-[124px]"
              />
            </div>
          </section>
          <p className="max-w-[80ch] text-[13px] leading-relaxed text-fg-muted">{speedAdvice(caps, gpu)}</p>
          <GraphicsCard gpu={gpu} onChanged={bump} />
          <RamLimit totalGb={caps.ram_total_gb} />
        </>
      )}
    </div>
  );
}
