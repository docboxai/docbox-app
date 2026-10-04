import { useState } from "react";
import { RefreshCw } from "lucide-react";
import { useApp } from "../lib/app";
import { formatGb, shortGpu } from "../lib/format";
import { Button, Notice, SectionLabel, Spinner, StatCard } from "./ui";

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
                sub="DocBox's own engines read on the CPU"
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
          <p className="text-[13px] text-fg-muted">
            Ollama models use a graphics card by themselves when one is available.
          </p>
        </>
      )}
    </div>
  );
}
