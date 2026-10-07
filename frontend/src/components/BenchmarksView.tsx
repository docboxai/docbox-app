// Benchmarks: the "local OCR test bench" from the design. Drop documents (a folder is one
// batch), pick models, and every model reads every page; each run is a card under
// Batches, and opening one shows the leaderboard and the page-by-page Compare.
// Runs started from the CLI or by an AI agent (MCP) appear here too.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, ArrowRight, ArrowUpRight, Ban, FileUp, FolderOpen, FolderUp, Gauge, Loader, X } from "lucide-react";
import { api, type BenchRun, type ModelInfo } from "../lib/api";
import { useApp } from "../lib/app";
import { plural } from "../lib/format";
import { BenchmarkRun } from "./BenchmarkRun";
import { Button, Card, IconAction, Notice, ProgressBar, SectionLabel, Spinner, StatCard, cx, type CardTone } from "./ui";

const POLL_MS = 1000;
const BATCH_COUNT = 8;

// A document to read, or a reference text next to one (invoice.gt.txt, invoice.p2.gt.txt).
interface Picked {
  file: File;
  path: string;
}

const isReference = (path: string) => /\.gt\.txt$/i.test(path);
const isDocument = (path: string) => /\.(pdf|png|jpe?g|tiff?|bmp|webp|gif)$/i.test(path);

// Files from a drop, walking into dropped folders (the browser only lists their files
// through the entries API). Paths keep the folder, so references stay next to documents.
async function filesFromDrop(items: DataTransferItemList): Promise<Picked[]> {
  const out: Picked[] = [];
  const walk = async (entry: FileSystemEntry, prefix: string): Promise<void> => {
    if (entry.isFile) {
      const file = await new Promise<File>((resolve, reject) => (entry as FileSystemFileEntry).file(resolve, reject));
      out.push({ file, path: prefix + file.name });
    } else if (entry.isDirectory) {
      const reader = (entry as FileSystemDirectoryEntry).createReader();
      // readEntries returns at most ~100 entries per call: keep reading until empty.
      for (;;) {
        const batch = await new Promise<FileSystemEntry[]>((resolve, reject) => reader.readEntries(resolve, reject));
        if (!batch.length) break;
        for (const child of batch) await walk(child, `${prefix}${entry.name}/`);
      }
    }
  };
  const entries = Array.from(items)
    .map((item) => item.webkitGetAsEntry?.())
    .filter((e): e is FileSystemEntry => !!e);
  for (const entry of entries) await walk(entry, "");
  return out;
}

function stateLabel(run: BenchRun): string {
  const total = run.pages_total * run.models.length;
  switch (run.state) {
    case "queued":
      return "Starting";
    case "running": {
      const current = run.models.find((m) => m.model_id === run.current_model_id);
      const doing = current?.state === "installing" ? `installing ${current.name}` : `${run.pages_done} of ${total} pages`;
      return `Running · ${doing}`;
    }
    case "done":
      return `Done · ${plural(run.files.length, "file")} · ${plural(run.pages_total, "page")}`;
    case "cancelled":
      return "Stopped";
    case "interrupted":
      return "Interrupted";
    default:
      return "Failed";
  }
}

function bestLine(run: BenchRun): string | null {
  const s = run.summary;
  const best = s?.leaderboard.find((r) => r.model_id === s.best_model_id);
  if (!s || !best) return null;
  if (s.ranked_by === "cer" && best.accuracy != null) return `Best read: ${best.name} · ${(best.accuracy * 100).toFixed(1)}%`;
  if (best.seconds_per_page != null) return `Fastest: ${best.name} · ${best.seconds_per_page.toFixed(1)} s/page`;
  return null;
}

const SOURCE: Record<string, string> = { cli: "from the command line", mcp: "from an AI agent" };

// The design's batch card: one card, one action (open the run below).
function BatchCard({ run, index, selected, onSelect }: { run: BenchRun; index: number; selected: boolean; onSelect: () => void }) {
  const busy = run.state === "running" || run.state === "queued";
  const done = run.state === "done";
  const tone: CardTone = done ? (index % 2 === 0 ? "primary-soft" : "primary-muted") : "surface";
  let icon;
  if (done) icon = <IconAction icon={ArrowUpRight} label="" />;
  else if (busy) icon = <IconAction icon={Loader} label="" tone="hero" spin />;
  else if (run.state === "cancelled") icon = <IconAction icon={Ban} label="" tone="light" />;
  else icon = <IconAction icon={AlertTriangle} label="" tone="light" />;
  const total = run.pages_total * run.models.length;
  const sub = busy ? null : (bestLine(run) ?? SOURCE[run.source] ?? plural(run.models.length, "model"));

  return (
    <div className={cx("group relative min-w-0 rounded-2xl", selected && "ring-2 ring-secondary ring-offset-2 ring-offset-ink")}>
      <StatCard
        tone={tone}
        label={stateLabel(run)}
        value={run.name}
        valueTitle={run.name}
        valueSize="sm"
        action={icon}
        sub={sub}
        className={cx("min-h-[140px] transition-[filter] group-hover:brightness-110", busy && "pb-10")}
      />
      {busy && (
        <div className="pointer-events-none absolute inset-x-4 bottom-4">
          <ProgressBar value={total ? (100 * run.pages_done) / total : 0} label={`${run.name} progress`} />
        </div>
      )}
      <button
        type="button"
        onClick={onSelect}
        aria-pressed={selected}
        aria-label={`Open ${run.name}: ${stateLabel(run)}`}
        title={run.error ?? undefined}
        className="absolute inset-0 cursor-pointer rounded-2xl hover:bg-fg/5"
      />
    </div>
  );
}

function ModelPicker({
  models,
  chosen,
  onToggle,
  defaultId,
}: {
  models: ModelInfo[];
  chosen: Set<string>;
  onToggle: (id: string) => void;
  defaultId: string | null | undefined;
}) {
  return (
    <fieldset className="flex min-h-0 flex-col gap-1.5">
      <legend className="mb-1.5 text-[13px] font-medium text-on-light">Models to compare</legend>
      <ul className="flex max-h-[176px] flex-col gap-1 overflow-y-auto pr-1">
        {models.map((m) => (
          <li key={m.id}>
            <label
              className={cx(
                "flex min-h-10 cursor-pointer items-center gap-3 rounded-xl px-3 py-1.5 text-sm transition-colors",
                "has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-secondary has-[:focus-visible]:outline-solid",
                chosen.has(m.id) ? "bg-ink text-fg" : "bg-ink/10 text-on-light hover:bg-ink/15",
              )}
            >
              <input type="checkbox" checked={chosen.has(m.id)} onChange={() => onToggle(m.id)} className="h-4 w-4 accent-secondary" />
              <span className="min-w-0 flex-1 truncate font-medium" title={m.name}>
                {m.name}
              </span>
              <span className={cx("shrink-0 text-xs", chosen.has(m.id) ? "text-fg-muted" : "text-on-light-muted")}>
                {m.id === defaultId ? "default · " : ""}
                {m.engine === "nvidia-nim" ? "cloud" : m.fit.summary}
              </span>
            </label>
          </li>
        ))}
      </ul>
    </fieldset>
  );
}

export function BenchmarksView() {
  const { settings, navigate, bump } = useApp();
  const [models, setModels] = useState<ModelInfo[] | null>(null);
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [picked, setPicked] = useState<Picked[]>([]);
  const [name, setName] = useState("");
  const [runs, setRuns] = useState<BenchRun[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const filesRef = useRef<HTMLInputElement>(null);
  const folderRef = useRef<HTMLInputElement>(null);

  // React has no prop for it: let the second input pick a whole folder.
  useEffect(() => {
    folderRef.current?.setAttribute("webkitdirectory", "");
  }, []);

  useEffect(() => {
    api.listModels().then(
      (list) => {
        const ready = list.filter((m) => m.status === "ready");
        setModels(ready);
        setChosen(new Set(ready.map((m) => m.id)));
      },
      (err) => {
        setError(err instanceof Error ? err.message : String(err));
        setModels([]);
      },
    );
  }, []);

  const loadRuns = useCallback(async () => {
    try {
      setRuns(await api.listBenchmarks());
    } catch {
      // The model list above already reports an unreachable backend.
    }
  }, []);

  useEffect(() => {
    void loadRuns();
  }, [loadRuns]);

  const working = runs.some((r) => r.state === "running" || r.state === "queued");
  const wasWorking = useRef(false);
  useEffect(() => {
    // Tell the rest of the app (the hero's count) when a run finishes.
    if (wasWorking.current && !working) bump();
    wasWorking.current = working;
    if (!working) return;
    const timer = setInterval(() => void loadRuns(), POLL_MS);
    return () => clearInterval(timer);
  }, [working, loadRuns, bump]);

  const add = (incoming: Picked[]) => {
    const useful = incoming.filter((p) => isDocument(p.path) || isReference(p.path));
    setPicked((prev) => {
      const seen = new Set(prev.map((p) => p.path));
      return [...prev, ...useful.filter((p) => !seen.has(p.path))];
    });
  };

  const documents = picked.filter((p) => isDocument(p.path));
  const references = picked.filter((p) => isReference(p.path));
  const ready = models ?? [];

  const start = async () => {
    setStarting(true);
    setError(null);
    try {
      const run = await api.startBenchmark(picked, [...chosen], name.trim());
      setPicked([]);
      setName("");
      setSelectedId(run.id);
      await loadRuns();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setStarting(false);
    }
  };

  const hint = useMemo(() => {
    if (!documents.length) return "Nothing selected yet";
    const refs = references.length ? ` · ${references.length} with reference text` : " · no reference text: ranked by speed";
    return `${plural(documents.length, "document")}${refs}`;
  }, [documents.length, references.length]);

  const visible = showAll ? runs : runs.slice(0, BATCH_COUNT);
  const selected = runs.find((r) => r.id === selectedId) ?? null;

  return (
    <div className="flex flex-col gap-4">
      {error && <Notice>{error}</Notice>}

      {/* Stretched, so both headings line up whatever the model list's height. */}
      <div className="flex flex-wrap items-stretch gap-4">
        <section aria-labelledby="bench-add-label" className="flex min-w-0 flex-[1_1_440px] flex-col gap-2.5">
          <SectionLabel id="bench-add-label">New benchmark</SectionLabel>
          <div
            onClick={(e) => {
              if (!(e.target as HTMLElement).closest("button, a, input")) folderRef.current?.click();
            }}
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              void filesFromDrop(e.dataTransfer.items).then(add, () => setError("Couldn't read the dropped folder."));
            }}
            className={cx(
              "flex min-h-[290px] flex-1 cursor-pointer flex-col items-center justify-center gap-3.5 rounded-2xl p-6 text-center ring-inset transition-colors",
              dragging ? "bg-line/70 ring-2 ring-secondary" : "bg-surface ring-1 ring-line hover:bg-line/40",
            )}
          >
            <span aria-hidden="true" className="flex h-[52px] w-[52px] items-center justify-center rounded-full bg-primary">
              <FolderUp className="h-[22px] w-[22px] text-fg" />
            </span>
            <div className="flex flex-col items-center gap-1">
              <p className="font-heading text-[28px] leading-tight font-semibold tracking-[-0.4px]">
                {documents.length ? `${plural(documents.length, "document")} in this batch` : "Drop a folder of documents"}
              </p>
              <p className="max-w-[460px] text-[13px] text-fg-muted">
                Every page goes to every model you pick. Add <code className="text-fg">invoice.gt.txt</code> next to{" "}
                <code className="text-fg">invoice.pdf</code> with the correct text to score accuracy.
              </p>
            </div>
            {picked.length > 0 && (
              <ul aria-label="Selected files" className="flex max-h-[84px] max-w-full flex-wrap justify-center gap-1.5 overflow-y-auto">
                {picked.map((p) => (
                  <li
                    key={p.path}
                    className={cx(
                      "flex max-w-[240px] items-center gap-1 rounded-2xl py-0.5 pr-1 pl-2.5 text-xs",
                      isReference(p.path) ? "bg-success/15 text-success" : "bg-line",
                    )}
                  >
                    <span className="truncate" title={p.path}>
                      {p.path}
                    </span>
                    <button
                      type="button"
                      aria-label={`Remove ${p.path}`}
                      onClick={() => setPicked((prev) => prev.filter((q) => q.path !== p.path))}
                      className="rounded-full p-0.5 text-fg-muted hover:bg-ink hover:text-fg"
                    >
                      <X aria-hidden="true" className="h-3 w-3" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <div className="flex flex-wrap items-center justify-center gap-2">
              <Button icon={FolderOpen} onClick={() => folderRef.current?.click()}>
                Choose a folder
              </Button>
              <Button variant="outline" icon={FileUp} onClick={() => filesRef.current?.click()}>
                Choose files
              </Button>
              {picked.length > 0 && (
                <Button variant="ghost" onClick={() => setPicked([])}>
                  Clear
                </Button>
              )}
            </div>
            <input
              ref={folderRef}
              type="file"
              multiple
              className="hidden"
              onChange={(e) => {
                add(Array.from(e.target.files ?? []).map((file) => ({ file, path: file.webkitRelativePath || file.name })));
                e.target.value = "";
              }}
            />
            <input
              ref={filesRef}
              type="file"
              multiple
              accept="image/*,.pdf,.tif,.tiff,.txt"
              className="hidden"
              onChange={(e) => {
                add(Array.from(e.target.files ?? []).map((file) => ({ file, path: file.name })));
                e.target.value = "";
              }}
            />
          </div>
        </section>

        <section aria-labelledby="bench-run-label" className="flex min-w-0 flex-[0_1_580px] flex-col gap-2.5 max-[1180px]:flex-[1_1_440px]">
          <SectionLabel id="bench-run-label">Compare with</SectionLabel>
          <Card tone="secondary-soft" className="flex min-h-[290px] flex-1 flex-col justify-between gap-4 p-5">
            {models !== null && ready.length === 0 ? (
              <div className="flex flex-1 flex-col items-start justify-center gap-3">
                <p className="font-heading text-2xl font-semibold">No models are ready yet</p>
                <p className="text-sm text-on-light-muted">A benchmark compares the models you have installed. Set up two or more.</p>
                <Button variant="ink" size="sm" icon={ArrowRight} onClick={() => navigate("setup")}>
                  Go to Setup
                </Button>
              </div>
            ) : (
              <>
                <ModelPicker
                  models={ready}
                  chosen={chosen}
                  defaultId={settings?.default_model_id}
                  onToggle={(id) =>
                    setChosen((prev) => {
                      const next = new Set(prev);
                      if (next.has(id)) next.delete(id);
                      else next.add(id);
                      return next;
                    })
                  }
                />
                <div className="flex flex-col gap-1">
                  <label htmlFor="bench-name" className="text-[13px] font-medium text-on-light">
                    Name <span className="font-normal text-on-light-muted">(optional)</span>
                  </label>
                  <input
                    id="bench-name"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="Named after the folder"
                    className="h-10 rounded-xl bg-ink px-3 text-sm font-medium text-fg placeholder:text-fg-muted outline-none focus-visible:ring-2 focus-visible:ring-fg"
                  />
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="min-w-0 truncate text-[13px] text-on-light-muted">{hint}</span>
                  <Button
                    variant="ink"
                    size="lg"
                    icon={starting ? undefined : Gauge}
                    disabled={!documents.length || chosen.size === 0 || starting}
                    onClick={() => void start()}
                  >
                    {starting && <Spinner />}
                    Start benchmark
                  </Button>
                </div>
              </>
            )}
          </Card>
        </section>
      </div>

      <section aria-labelledby="batches-label" className="flex flex-col gap-2.5">
        <div className="flex items-center justify-between gap-3">
          <SectionLabel id="batches-label">Batches</SectionLabel>
          {runs.length > BATCH_COUNT && (
            <Button size="sm" variant="ghost" onClick={() => setShowAll((s) => !s)}>
              {showAll ? "Show fewer" : `Show all ${runs.length}`}
            </Button>
          )}
        </div>
        {runs.length === 0 ? (
          <Card className="flex min-h-[140px] items-center justify-center px-5 text-center text-sm text-fg-muted">
            Each benchmark becomes a batch here, ready to re-run. Runs from the command line and from AI agents show up too.
          </Card>
        ) : (
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {visible.map((r, i) => (
              <BatchCard key={r.id} run={r} index={i} selected={r.id === selectedId} onSelect={() => setSelectedId(r.id === selectedId ? null : r.id)} />
            ))}
          </div>
        )}
      </section>

      {selected && (
        <BenchmarkRun
          key={selected.id}
          summary={selected}
          onClose={() => setSelectedId(null)}
          onChanged={(next) => {
            if (next) setSelectedId(next);
            void loadRuns();
          }}
          onDeleted={() => {
            setSelectedId(null);
            void loadRuns();
            bump();
          }}
        />
      )}
    </div>
  );
}
