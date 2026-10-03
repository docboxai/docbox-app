import { useCallback, useEffect, useState } from "react";
import { HardDrive } from "lucide-react";
import { api, formatBytes, type EngineStorage, type StorageInfo } from "../lib/api";

// The full path starts with the user's profile folder, which is long and personal; the
// last three folders are enough to find it (the full path shows on hover).
function shortPath(path: string): string {
  const sep = path.includes("\\") ? "\\" : "/";
  const parts = path.split(sep).filter(Boolean);
  return parts.length > 3 ? `…${sep}${parts.slice(-3).join(sep)}` : path;
}

function EngineRow({ engine, onChanged }: { engine: EngineStorage; onChanged: () => void }) {
  const [confirm, setConfirm] = useState(false);
  const [working, setWorking] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  const uninstall = useCallback(async () => {
    setWorking(true);
    setNote(null);
    try {
      const result = await api.uninstallEngine(engine.id);
      setNote(result.detail);
      setConfirm(false);
      onChanged();
    } catch (err) {
      setNote(err instanceof Error ? err.message : String(err));
    } finally {
      setWorking(false);
    }
  }, [engine.id, onChanged]);

  const total = engine.package_bytes + engine.model_bytes;

  return (
    <li className="flex flex-col gap-2 border-t border-border py-3 first:border-t-0">
      <div className="flex flex-wrap items-center gap-3">
        <span className="min-w-0 flex-1 text-sm font-medium">{engine.name}</span>
        <span className="text-xs tabular-nums text-text-muted">
          {engine.installed
            ? `${formatBytes(engine.package_bytes)} engine · ${formatBytes(engine.model_bytes)} models`
            : "not installed"}
        </span>
        {engine.removal_pending && (
          <span className="text-xs text-warn">removed on next restart</span>
        )}
        {engine.installed && !engine.removal_pending && !confirm && (
          <button
            type="button"
            onClick={() => setConfirm(true)}
            className="rounded-full border border-border px-2.5 py-1 text-xs text-text-muted hover:bg-panel-2 hover:text-text"
          >
            Uninstall
          </button>
        )}
      </div>
      {confirm && (
        <div className="flex flex-wrap items-center gap-2 rounded-xl border border-ink px-3 py-2">
          <span className="flex-1 text-sm">
            Uninstall {engine.name} and its downloaded models? Frees about {formatBytes(total)}.
          </span>
          <button
            type="button"
            onClick={() => void uninstall()}
            disabled={working}
            className="rounded-full bg-accent px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
          >
            {working ? "Removing…" : "Uninstall"}
          </button>
          <button
            type="button"
            onClick={() => setConfirm(false)}
            className="rounded-full border border-border px-3 py-1.5 text-sm text-text hover:bg-panel-2"
          >
            Keep
          </button>
        </div>
      )}
      {note && <p className="text-xs text-text-muted">{note}</p>}
    </li>
  );
}

export function StoragePanel({ refreshKey, onChanged }: { refreshKey: number; onChanged: () => void }) {
  const [info, setInfo] = useState<StorageInfo | null>(null);

  const load = useCallback(async () => {
    try {
      setInfo(await api.engineStorage());
    } catch {
      setInfo(null);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  if (!info) return null;

  return (
    <section aria-label="Storage" className="rounded-2xl border border-border bg-panel p-5">
      <div className="mb-2 flex items-center gap-2 font-medium">
        <HardDrive className="h-4 w-4 text-accent" /> Storage
      </div>
      <p className="mb-2 text-xs text-text-muted" title={info.data_dir}>
        Saved in {shortPath(info.data_dir)}
      </p>
      <ul>
        {info.engines.map((e) => (
          <EngineRow
            key={e.id}
            engine={e}
            onChanged={() => {
              void load();
              onChanged();
            }}
          />
        ))}
      </ul>
    </section>
  );
}
