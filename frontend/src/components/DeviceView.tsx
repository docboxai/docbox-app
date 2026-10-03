import { useEffect, useState, useCallback } from "react";
import { RefreshCw, MemoryStick, Cpu, HardDrive, AlertTriangle } from "lucide-react";
import { api, type DeviceCapabilities } from "../lib/api";

function StatCard({
  icon: Icon,
  label,
  value,
  sub,
}: {
  icon: typeof Cpu;
  label: string;
  value: string;
  sub: string;
}) {
  return (
    <div className="relative overflow-hidden rounded-2xl border border-border bg-panel p-6">
      <div aria-hidden="true" className="halftone absolute -top-2 -right-2 h-20 w-20 opacity-30" />
      <div className="relative mb-4 flex h-11 w-11 items-center justify-center rounded-full bg-accent-bright">
        <Icon className="h-5 w-5 text-white" strokeWidth={2} />
      </div>
      <div className="font-mono text-xs font-bold tracking-widest text-accent uppercase">{label}</div>
      <div className="mt-1.5 text-3xl font-extrabold tracking-tight">{value}</div>
      <div className="mt-1 text-sm text-text-muted">{sub}</div>
    </div>
  );
}

export function DeviceView() {
  const [caps, setCaps] = useState<DeviceCapabilities | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setCaps(await api.deviceCapabilities());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <p className="max-w-[56ch] leading-relaxed text-text-muted">
          DocBox compares this with what each model needs, so it can tell you which ones
          will run comfortably here.
        </p>
        <button
          type="button"
          onClick={() => void refresh()}
          disabled={loading}
          className="flex min-h-11 items-center gap-2 rounded-full border border-border px-4 text-sm font-semibold text-text hover:bg-accent-pale disabled:opacity-50"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      {error && (
        <div className="mb-6 flex items-center gap-2 rounded-xl border border-warn/30 bg-warn-bg px-4 py-3 text-sm text-warn">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          Couldn't reach DocBox's engine: {error}
        </div>
      )}

      {caps && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <StatCard
            icon={MemoryStick}
            label="Memory"
            value={`${caps.ram_available_gb.toFixed(1)} GB free`}
            sub={`of ${caps.ram_total_gb.toFixed(1)} GB total`}
          />
          <StatCard
            icon={Cpu}
            label="Processor"
            value={`${caps.cpu_physical_cores} cores`}
            sub={`${caps.cpu_logical_cores} logical threads`}
          />
          <StatCard
            icon={HardDrive}
            label="Disk"
            value={`${caps.disk_free_gb.toFixed(1)} GB free`}
            sub="available for model storage"
          />
        </div>
      )}
    </div>
  );
}
