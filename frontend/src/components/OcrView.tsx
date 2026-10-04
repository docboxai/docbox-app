import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowRight,
  ArrowUpRight,
  ChevronDown,
  Clipboard,
  Copy,
  ExternalLink,
  FileUp,
  FolderOpen,
  Loader,
  Play,
  Trash2,
  X,
} from "lucide-react";
import {
  api,
  type ModelInfo,
  type OutputFormat,
  type ReadDetail,
  type ReadSummary,
} from "../lib/api";
import { useApp } from "../lib/app";
import { formatSeconds, plural } from "../lib/format";
import {
  Button,
  Card,
  IconAction,
  Notice,
  SectionLabel,
  Spinner,
  StatCard,
  Tabs,
  cx,
  type CardTone,
} from "./ui";

const FORMATS: { value: OutputFormat; label: string }[] = [
  { value: "txt", label: "Plain text" },
  { value: "md", label: "Markdown" },
  { value: "pdf", label: "Searchable PDF" },
  { value: "json", label: "JSON" },
];

const ACCEPT = "image/*,.pdf,.tif,.tiff";
const RECENT_COUNT = 4;
const POLL_MS = 1000;

function isAccepted(file: File): boolean {
  const name = file.name.toLowerCase();
  return file.type.startsWith("image/") || file.type === "application/pdf" || /\.(pdf|tiff?)$/.test(name);
}

function shortPath(path: string): string {
  const sep = path.includes("\\") ? "\\" : "/";
  const parts = path.split(sep).filter(Boolean);
  return parts.length > 2 ? `…${sep}${parts.slice(-2).join(sep)}` : path;
}

function readLabel(r: ReadSummary): string {
  switch (r.state) {
    case "queued":
      return "Waiting to start";
    case "reading":
      return r.pages_total
        ? `Reading · page ${Math.min(r.pages_done + 1, r.pages_total)} of ${r.pages_total}`
        : "Reading";
    case "done":
      return [
        "Done",
        r.pages_total != null ? plural(r.pages_total, "page") : null,
        r.seconds != null ? formatSeconds(r.seconds) : null,
      ]
        .filter(Boolean)
        .join(" · ");
    case "cancelled":
      return "Stopped";
    default:
      return "Failed";
  }
}

function RecentCard({
  read,
  index,
  selected,
  onSelect,
  onError,
}: {
  read: ReadSummary;
  index: number;
  selected: boolean;
  onSelect: () => void;
  onError: (message: string) => void;
}) {
  const done = read.state === "done";
  const busy = read.state === "reading" || read.state === "queued";
  const tone: CardTone = done ? (index % 2 === 0 ? "primary-soft" : "primary-muted") : "surface";

  const openFile = async () => {
    try {
      await api.openRead(read.id, "file");
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    }
  };

  let action;
  if (done && read.output_path) {
    action = <IconAction icon={ArrowUpRight} label={`Open ${read.file_name}`} onClick={() => void openFile()} />;
  } else if (busy) {
    action = <IconAction icon={Loader} label="" tone="hero" spin />;
  } else {
    action = <IconAction icon={X} label="" tone="light" />;
  }

  return (
    <div className={cx("relative min-w-0 rounded-2xl", selected && "ring-2 ring-secondary ring-offset-2 ring-offset-ink")}>
      <StatCard
        tone={tone}
        label={read.state === "error" ? <span title={read.error ?? undefined}>{readLabel(read)}</span> : readLabel(read)}
        value={read.file_name}
        valueSize="sm"
        action={<span className="relative z-10">{action}</span>}
        className="min-h-[124px]"
      />
      <button
        type="button"
        onClick={onSelect}
        aria-pressed={selected}
        aria-label={`Show the text of ${read.file_name}: ${readLabel(read)}`}
        className="absolute inset-0 rounded-2xl"
      />
    </div>
  );
}

function ResultPanel({
  read,
  onClose,
  onDeleted,
}: {
  read: ReadDetail;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const act = async (fn: () => Promise<void>) => {
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const copy = () =>
    act(async () => {
      await navigator.clipboard.writeText(read.text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });

  const meta = [
    read.model_name,
    read.pages_total != null ? plural(read.pages_total, "page") : null,
    read.seconds != null ? formatSeconds(read.seconds) : null,
    read.output_path ? `saved as ${shortPath(read.output_path)}` : null,
  ].filter(Boolean);
  const lineCount = read.pages.reduce((n, p) => n + p.lines.length, 0);

  return (
    <Card as="section" aria-label={`Text of ${read.file_name}`} className="flex flex-col">
      <div className="flex flex-wrap items-start gap-3 border-b border-line px-5 py-4">
        <div className="min-w-0 flex-1">
          <h3 className="truncate font-heading text-[22px] leading-[1.15] font-semibold tracking-[-0.5px]">
            {read.file_name}
          </h3>
          <p className="truncate text-[13px] text-fg-muted" title={read.output_path ?? undefined}>
            {meta.join(" · ")}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {read.state === "done" && (
            <>
              <Button size="sm" variant="outline" icon={Copy} onClick={() => void copy()}>
                {copied ? "Copied" : "Copy text"}
              </Button>
              {read.output_path && (
                <>
                  <Button size="sm" variant="outline" icon={ExternalLink} onClick={() => void act(() => api.openRead(read.id, "file"))}>
                    Open file
                  </Button>
                  <Button size="sm" variant="outline" icon={FolderOpen} onClick={() => void act(() => api.openRead(read.id, "folder"))}>
                    Show in folder
                  </Button>
                </>
              )}
            </>
          )}
          {confirmDelete ? (
            <span className="flex items-center gap-1.5 rounded-3xl bg-line/60 py-0.5 pr-0.5 pl-3 text-[13px]">
              {read.state === "reading" || read.state === "queued" ? "Stop and forget it?" : "Forget it? The saved file stays."}
              <Button size="sm" variant="light" onClick={() => void act(async () => { await api.deleteRead(read.id); onDeleted(); })}>
                {read.state === "reading" || read.state === "queued" ? "Stop" : "Forget"}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setConfirmDelete(false)}>
                Keep
              </Button>
            </span>
          ) : (
            <Button
              size="sm"
              variant="ghost"
              icon={Trash2}
              aria-label="Remove from recent files"
              title="Remove from recent files"
              onClick={() => setConfirmDelete(true)}
            />
          )}
          <Button size="sm" variant="ghost" icon={X} aria-label="Close" title="Close" onClick={onClose} />
        </div>
      </div>

      {error && (
        <div className="px-5 pt-4">
          <Notice>{error}</Notice>
        </div>
      )}

      <div className="px-5 py-3">
        {read.state === "error" || read.state === "cancelled" ? (
          <p className="py-4 text-sm text-fg-muted">
            {read.state === "cancelled" ? "This read was stopped." : `This file couldn't be read: ${read.error ?? "unknown error"}`}
          </p>
        ) : read.state !== "done" ? (
          <p className="flex items-center gap-2 py-4 text-sm text-fg-muted">
            <Spinner className="text-secondary" /> {readLabel(read)}
          </p>
        ) : lineCount === 0 ? (
          <p className="py-4 text-sm text-fg-muted">No text was found in this file.</p>
        ) : (
          read.pages.map((page, p) => (
            <div key={p} className="py-1">
              {read.pages.length > 1 && (
                <h4 className="pt-3 pb-1 text-xs font-medium tracking-[0.3px] text-fg-muted uppercase">Page {p + 1}</h4>
              )}
              <ol>
                {page.lines.map((line, i) => (
                  <li key={i} className="flex min-h-10 items-center gap-3.5 border-b border-line/70 last:border-b-0">
                    <span aria-hidden="true" className="w-6 text-xs text-fg-muted tabular-nums">
                      {String(i + 1).padStart(2, "0")}
                    </span>
                    <span className="min-w-0 flex-1 text-sm select-text">{line.text}</span>
                    {line.confidence != null && (
                      <>
                        <span aria-hidden="true" className="h-1.5 w-20 rounded-full bg-line">
                          <span
                            className="block h-1.5 rounded-full bg-secondary"
                            style={{ width: `${Math.round(line.confidence * 100)}%` }}
                          />
                        </span>
                        <span className="w-10 text-right text-xs font-medium tabular-nums" title="Confidence">
                          {Math.round(line.confidence * 100)}%
                        </span>
                      </>
                    )}
                  </li>
                ))}
              </ol>
            </div>
          ))
        )}
      </div>
    </Card>
  );
}

export function OcrView() {
  const { settings, navigate, bump } = useApp();
  const [models, setModels] = useState<ModelInfo[] | null>(null);
  const [modelId, setModelId] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [format, setFormat] = useState<OutputFormat>("txt");
  const [reads, setReads] = useState<ReadSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ReadDetail | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hint, setHint] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const finishedRef = useRef<Set<string> | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        // "ready" rather than "downloaded": a model whose engine was uninstalled, or whose
        // Ollama isn't running, has files on disk but can't run.
        setModels((await api.listModels()).filter((m) => m.status === "ready"));
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
        setModels([]);
      }
    })();
  }, []);

  // Start on the default model once both it and the list are known.
  useEffect(() => {
    if (!models || modelId) return;
    const preferred = models.find((m) => m.id === settings?.default_model_id) ?? models[0];
    if (preferred) setModelId(preferred.id);
  }, [models, settings?.default_model_id, modelId]);

  const loadReads = useCallback(async () => {
    try {
      const list = await api.listReads();
      setReads(list);
      const finished = new Set(list.filter((r) => r.state === "done").map((r) => r.id));
      // Tell the rest of the app (the hero's count) when a read finishes.
      if (finishedRef.current && [...finished].some((id) => !finishedRef.current!.has(id))) bump();
      finishedRef.current = finished;
    } catch {
      // The model list above already reports an unreachable backend.
    }
  }, [bump]);

  useEffect(() => {
    void loadReads();
  }, [loadReads]);

  const working = reads.some((r) => r.state === "queued" || r.state === "reading");
  useEffect(() => {
    if (!working) return;
    const timer = setInterval(() => void loadReads(), POLL_MS);
    return () => clearInterval(timer);
  }, [working, loadReads]);

  const selectedSummary = reads.find((r) => r.id === selectedId);
  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    api.getRead(selectedId).then(
      (d) => !cancelled && setDetail(d),
      () => !cancelled && setDetail(null),
    );
    return () => {
      cancelled = true;
    };
    // Refetch as the selected read progresses.
  }, [selectedId, selectedSummary?.state, selectedSummary?.pages_done]);

  const addFiles = useCallback((incoming: File[]) => {
    const accepted = incoming.filter(isAccepted);
    setHint(accepted.length < incoming.length ? "Only PDFs and images can be read; the rest were skipped." : null);
    if (accepted.length) setFiles((prev) => [...prev, ...accepted]);
  }, []);

  // Ctrl+V anywhere on this view pastes an image or files.
  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      const pasted = Array.from(e.clipboardData?.files ?? []);
      if (pasted.length) {
        e.preventDefault();
        addFiles(pasted.map((f, i) => (f.name ? f : new File([f], `pasted-${Date.now()}-${i}.png`, { type: f.type }))));
      }
    };
    document.addEventListener("paste", onPaste);
    return () => document.removeEventListener("paste", onPaste);
  }, [addFiles]);

  const pasteFromClipboard = async () => {
    setHint(null);
    try {
      const items = await navigator.clipboard.read();
      const pasted: File[] = [];
      for (const item of items) {
        const type = item.types.find((t) => t.startsWith("image/"));
        if (!type) continue;
        const blob = await item.getType(type);
        const ext = type.split("/")[1]?.replace("jpeg", "jpg") ?? "png";
        pasted.push(new File([blob], `pasted-${new Date().toISOString().slice(0, 19).replace(/:/g, "-")}.${ext}`, { type }));
      }
      if (pasted.length) addFiles(pasted);
      else setHint("There's no image on the clipboard. Copy a screenshot or picture first.");
    } catch {
      setHint("Couldn't read the clipboard here. Press Ctrl+V to paste instead.");
    }
  };

  const run = async () => {
    if (!modelId || files.length === 0) return;
    setStarting(true);
    setError(null);
    try {
      const { reads: started } = await api.startReads(modelId, files, format);
      setFiles([]);
      setSelectedId(started[0]?.id ?? null);
      await loadReads();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setStarting(false);
    }
  };

  const visibleReads = showAll ? reads : reads.slice(0, RECENT_COUNT);
  const ready = models ?? [];
  const runHint = useMemo(() => {
    if (files.length === 0) return "Nothing selected yet";
    const where = settings?.output_dir ? ` · saves to ${shortPath(settings.output_dir)}` : "";
    return `${plural(files.length, "file")} selected${where}`;
  }, [files.length, settings?.output_dir]);

  return (
    <div className="flex flex-col gap-4">
      {error && <Notice>{error}</Notice>}

      <div className="flex flex-wrap items-end gap-4">
        <section aria-labelledby="add-label" className="flex min-w-0 flex-[1_1_440px] flex-col gap-2.5">
          <SectionLabel id="add-label">Add documents</SectionLabel>
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              addFiles(Array.from(e.dataTransfer.files ?? []));
            }}
            className={cx(
              "flex min-h-[262px] flex-col items-center justify-center gap-3.5 rounded-2xl p-6 text-center ring-inset transition-colors",
              dragging ? "bg-line/70 ring-2 ring-secondary" : "bg-surface ring-1 ring-line",
            )}
          >
            <span aria-hidden="true" className="flex h-[52px] w-[52px] items-center justify-center rounded-full bg-primary">
              <FileUp className="h-[22px] w-[22px] text-fg" />
            </span>
            <div className="flex flex-col items-center gap-1">
              <p className="font-heading text-[28px] leading-tight font-semibold tracking-[-0.4px]">
                {files.length ? `${plural(files.length, "file")} ready to read` : "Drop a PDF or image here"}
              </p>
              <p className="text-[13px] text-fg-muted">PDF, PNG, JPG, TIFF · every page is read</p>
            </div>
            {files.length > 0 && (
              <ul aria-label="Selected files" className="flex max-w-full flex-wrap justify-center gap-1.5">
                {files.map((f, i) => (
                  <li key={`${f.name}-${i}`} className="flex max-w-[220px] items-center gap-1 rounded-2xl bg-line py-0.5 pr-1 pl-2.5 text-xs">
                    <span className="truncate">{f.name}</span>
                    <button
                      type="button"
                      aria-label={`Remove ${f.name}`}
                      onClick={() => setFiles((prev) => prev.filter((_, j) => j !== i))}
                      className="rounded-full p-0.5 text-fg-muted hover:bg-ink hover:text-fg"
                    >
                      <X aria-hidden="true" className="h-3 w-3" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <div className="flex flex-wrap items-center justify-center gap-2">
              <Button icon={FolderOpen} onClick={() => fileInputRef.current?.click()}>
                {files.length ? "Add more" : "Choose files"}
              </Button>
              <Button variant="outline" icon={Clipboard} onClick={() => void pasteFromClipboard()}>
                Paste from clipboard
              </Button>
            </div>
            {hint && <p className="text-xs text-warning">{hint}</p>}
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept={ACCEPT}
              className="hidden"
              onChange={(e) => {
                addFiles(Array.from(e.target.files ?? []));
                e.target.value = "";
              }}
            />
          </div>
        </section>

        <section aria-labelledby="run-label" className="flex min-w-0 flex-[0_1_580px] flex-col gap-2.5 max-[1180px]:flex-[1_1_440px]">
          <SectionLabel id="run-label">Run with</SectionLabel>
          <Card tone="secondary-soft" className="flex min-h-[262px] flex-col justify-between gap-4 p-5">
            {models !== null && ready.length === 0 ? (
              <div className="flex flex-1 flex-col items-start justify-center gap-3">
                <p className="font-heading text-2xl font-semibold">No models are ready yet</p>
                <p className="text-sm text-on-light-muted">Set one up first; it takes one click.</p>
                <Button variant="ink" size="sm" icon={ArrowRight} onClick={() => navigate("setup")}>
                  Go to Setup
                </Button>
              </div>
            ) : (
              <>
                <div className="flex flex-col gap-1">
                  <label htmlFor="ocr-model" className="text-[13px] font-medium text-on-light">
                    Engine and model
                  </label>
                  <div className="relative">
                    <select
                      id="ocr-model"
                      value={modelId}
                      disabled={!models}
                      onChange={(e) => setModelId(e.target.value)}
                      className="h-10 w-full appearance-none rounded-xl bg-ink pr-10 pl-3 text-sm font-medium text-fg outline-none focus-visible:ring-2 focus-visible:ring-fg"
                    >
                      {!models && <option>Loading…</option>}
                      {ready.map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.name} · {m.engine === "nvidia-nim" ? "cloud" : "installed"}
                          {m.id === settings?.default_model_id ? " · default" : ""}
                        </option>
                      ))}
                    </select>
                    <ChevronDown aria-hidden="true" className="pointer-events-none absolute top-3 right-3 h-4 w-4 text-fg" />
                  </div>
                </div>
                <div className="flex flex-col gap-1.5">
                  <span className="text-[13px] font-medium text-on-light">Save the text as</span>
                  <Tabs label="Save the text as" value={format} options={FORMATS} onChange={setFormat} />
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="min-w-0 truncate text-[13px] text-on-light-muted" title={settings?.output_dir}>
                    {runHint}
                  </span>
                  <Button
                    variant="ink"
                    size="lg"
                    icon={starting ? undefined : Play}
                    disabled={!modelId || files.length === 0 || starting}
                    onClick={() => void run()}
                  >
                    {starting && <Spinner />}
                    Read text
                  </Button>
                </div>
              </>
            )}
          </Card>
        </section>
      </div>

      <section aria-labelledby="recent-label" className="flex flex-col gap-2.5">
        <div className="flex items-center justify-between gap-3">
          <SectionLabel id="recent-label">Recent files</SectionLabel>
          {reads.length > RECENT_COUNT && (
            <Button size="sm" variant="ghost" onClick={() => setShowAll((s) => !s)}>
              {showAll ? "Show fewer" : `Show all ${reads.length}`}
            </Button>
          )}
        </div>
        {reads.length === 0 ? (
          <Card className="flex min-h-[124px] items-center justify-center px-5 text-sm text-fg-muted">
            Files you read show up here. Their text stays on this computer.
          </Card>
        ) : (
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {visibleReads.map((r, i) => (
              <RecentCard
                key={r.id}
                read={r}
                index={i}
                selected={r.id === selectedId}
                onSelect={() => setSelectedId(r.id === selectedId ? null : r.id)}
                onError={setError}
              />
            ))}
          </div>
        )}
      </section>

      {detail && (
        <ResultPanel
          read={detail}
          onClose={() => setSelectedId(null)}
          onDeleted={() => {
            setSelectedId(null);
            void loadReads();
            bump();
          }}
        />
      )}
    </div>
  );
}
