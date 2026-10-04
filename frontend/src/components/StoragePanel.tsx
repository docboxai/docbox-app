import { useCallback, useState } from "react";
import { Trash2 } from "lucide-react";
import { api, formatBytes, type EngineStorage, type StorageInfo } from "../lib/api";
import { Button, Card, Chip, SectionLabel } from "./ui";

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
    <li className="flex flex-col gap-2 border-b border-line px-4 py-3 last:border-b-0">
      <div className="flex flex-wrap items-center gap-3">
        <span className="min-w-0 flex-1 text-sm font-medium">{engine.name}</span>
        <span className="text-[13px] text-fg-muted tabular-nums">
          {engine.installed
            ? `${formatBytes(engine.package_bytes)} engine · ${formatBytes(engine.model_bytes)} models`
            : "Not installed"}
        </span>
        {engine.removal_pending && <Chip tone="warning">Removed on next restart</Chip>}
        {engine.installed && !engine.removal_pending && !confirm && (
          <Button size="sm" variant="ghost" icon={Trash2} onClick={() => setConfirm(true)}>
            Uninstall
          </Button>
        )}
      </div>
      {confirm && (
        <div className="flex flex-wrap items-center gap-2 rounded-xl bg-line/60 px-3 py-2">
          <span className="min-w-0 flex-1 text-sm">
            Uninstall {engine.name} and its downloaded models? Frees about {formatBytes(total)}.
          </span>
          <Button size="sm" variant="light" disabled={working} onClick={() => void uninstall()}>
            {working ? "Removing…" : "Uninstall"}
          </Button>
          <Button size="sm" variant="outline" onClick={() => setConfirm(false)}>
            Keep
          </Button>
        </div>
      )}
      {note && <p className="text-xs text-fg-muted">{note}</p>}
    </li>
  );
}

export function StoragePanel({ info, onChanged }: { info: StorageInfo; onChanged: () => void }) {
  return (
    <section aria-labelledby="engines-disk-label" className="flex flex-col gap-2.5">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <SectionLabel id="engines-disk-label">Engines on disk</SectionLabel>
        <span className="text-[13px] text-fg-muted" title={info.data_dir}>
          Saved in {shortPath(info.data_dir)}
        </span>
      </div>
      <Card>
        <ul>
          {info.engines.map((e) => (
            <EngineRow key={e.id} engine={e} onChanged={onChanged} />
          ))}
        </ul>
      </Card>
    </section>
  );
}
