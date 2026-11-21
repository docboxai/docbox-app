import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import type { DeviceCapabilities } from "../lib/api";
import { useApp } from "../lib/app";
import { formatGb, shortGpu } from "../lib/format";
import { Button, Card, Notice, SectionLabel, Spinner, StatCard, Switch } from "./ui";

// What reads fastest on this computer, from its hardware.
function speedAdvice(caps: DeviceCapabilities): string {
  if (caps.gpu_memory_gb) {
    return (
      `Ollama models read on your ${shortGpu(caps.gpu_name ?? "graphics card")} (${formatGb(caps.gpu_memory_gb)}), ` +
      "the fastest way to run the large vision models here. DocBox's own models read on the " +
      `${caps.cpu_physical_cores}-core processor: PaddleOCR Mobile is quickest on it, and the ` +
      "larger PaddleOCR models would read several times faster on a graphics card."
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

export function DeviceView() {
  const { caps, refreshCaps } = useApp();
  const [loading, setLoading] = useState(false);

  const refresh = async () => {
    setLoading(true);
    await refreshCaps();
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
                sub={caps.gpu_memory_gb ? `${formatGb(caps.gpu_memory_gb)} · used by Ollama` : "DocBox's own engines read on the CPU"}
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
          <p className="max-w-[80ch] text-[13px] leading-relaxed text-fg-muted">{speedAdvice(caps)}</p>
          <RamLimit totalGb={caps.ram_total_gb} />
        </>
      )}
    </div>
  );
}
