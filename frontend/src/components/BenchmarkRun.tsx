// One benchmark run: its leaderboard, and the design's Compare card (the page beside
// every model's reading of it, mistakes against the reference marked as slips).
import { useEffect, useMemo, useState } from "react";
import { ChevronLeft, ChevronRight, Download, RotateCw, Square, Trash2, X } from "lucide-react";
import { api, type BenchRun, type DiffSpan, type LeaderboardRow, type PageView } from "../lib/api";
import { useApp } from "../lib/app";
import { formatMb, plural } from "../lib/format";
import { BenchmarkChart } from "./BenchmarkChart";
import { Button, Card, Chip, Notice, ProgressBar, SectionLabel, Spinner, cx } from "./ui";

const POLL_MS = 1000;

const pct = (v: number | null) => (v == null ? "–" : `${(v * 100).toFixed(1)}%`);
const secs = (v: number | null, digits = 2) => (v == null ? "–" : `${v.toFixed(digits)} s`);

const SOURCE: Record<string, string> = { app: "started here", cli: "from the command line", mcp: "from an AI agent" };

function useRun(summary: BenchRun): BenchRun {
  // The list's copy has no live leaderboard while running; follow the run itself.
  const [run, setRun] = useState<BenchRun>(summary);
  const busy = run.state === "running" || run.state === "queued";
  useEffect(() => {
    let alive = true;
    const load = () => api.getBenchmark(summary.id).then((r) => alive && setRun(r), () => undefined);
    void load();
    if (!busy) return () => void (alive = false);
    const timer = setInterval(load, POLL_MS);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [summary.id, summary.state, busy]);
  return run;
}

// The best value in each column, so the table can point it out.
function bests(rows: LeaderboardRow[]) {
  const ranked = rows.filter((r) => r.pages_read > 0);
  const min = (f: (r: LeaderboardRow) => number | null) => {
    const vals = ranked.map(f).filter((v): v is number => v != null);
    return vals.length > 1 ? Math.min(...vals) : null;
  };
  const max = (f: (r: LeaderboardRow) => number | null) => {
    const vals = ranked.map(f).filter((v): v is number => v != null);
    return vals.length > 1 ? Math.max(...vals) : null;
  };
  return {
    accuracy: max((r) => r.accuracy),
    wer: min((r) => r.wer),
    speed: min((r) => r.seconds_per_page),
    load: min((r) => r.load_seconds),
    memory: min((r) => r.peak_memory_mb),
    confidence: max((r) => r.mean_confidence),
  };
}

// Highlighted only when there is a value and it's the column's best.
const isBest = (value: number | null, best: number | null) => value != null && value === best;

function Cell({ best, children, className }: { best?: boolean; children: React.ReactNode; className?: string }) {
  return (
    <td className={cx("px-3 py-2.5 text-right tabular-nums whitespace-nowrap", best && "font-semibold text-success", className)}>
      {children}
    </td>
  );
}

function Leaderboard({ run }: { run: BenchRun }) {
  const { settings, updateSettings } = useApp();
  const rows = run.summary?.leaderboard ?? [];
  const b = bests(rows);
  const scored = run.summary?.ranked_by === "cer";
  if (!rows.length) return null;
  return (
    <section aria-label="Leaderboard" className="overflow-x-auto">
      <table className="w-full min-w-[820px] border-collapse text-sm">
        <caption className="sr-only">
          Models ranked by {scored ? "accuracy against the reference text" : "speed (no reference text)"}
        </caption>
        <thead>
          <tr className="text-xs font-medium tracking-[0.3px] text-fg-muted uppercase">
            <th scope="col" className="w-10 px-3 py-2 text-left">#</th>
            <th scope="col" className="px-3 py-2 text-left">Model</th>
            <th scope="col" className="px-3 py-2 text-right" title="1 − character error rate">Accuracy</th>
            <th scope="col" className="px-3 py-2 text-right" title="Word error rate">WER</th>
            <th scope="col" className="px-3 py-2 text-right">Per page</th>
            <th scope="col" className="px-3 py-2 text-right">Load</th>
            <th scope="col" className="px-3 py-2 text-right">Peak RAM</th>
            <th scope="col" className="px-3 py-2 text-right">Confidence</th>
            <th scope="col" className="px-3 py-2 text-right">Failed</th>
            <th scope="col" className="px-3 py-2"><span className="sr-only">Actions</span></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const isDefault = settings?.default_model_id === r.model_id;
            return (
              <tr key={r.model_id} className="border-t border-line/70">
                <td className="px-3 py-2.5 font-heading text-base font-semibold tabular-nums">{r.rank ?? "–"}</td>
                <th scope="row" className="max-w-[280px] px-3 py-2.5 text-left font-medium">
                  <span className="block truncate" title={`${r.name} (${r.model_id})`}>{r.name}</span>
                </th>
                <Cell best={scored && isBest(r.accuracy, b.accuracy)}>{pct(r.accuracy)}</Cell>
                <Cell best={scored && isBest(r.wer, b.wer)}>{pct(r.wer)}</Cell>
                <Cell best={isBest(r.seconds_per_page, b.speed)}>{secs(r.seconds_per_page)}</Cell>
                <Cell best={isBest(r.load_seconds, b.load)}>{secs(r.load_seconds, 1)}</Cell>
                <Cell best={isBest(r.peak_memory_mb, b.memory)}>{r.peak_memory_mb == null ? "–" : formatMb(r.peak_memory_mb)}</Cell>
                <Cell best={isBest(r.mean_confidence, b.confidence)}>{pct(r.mean_confidence)}</Cell>
                <Cell className={r.pages_failed ? "text-danger" : "text-fg-muted"}>{r.pages_failed}</Cell>
                <td className="px-3 py-2 text-right">
                  {isDefault ? (
                    <Chip tone="success">Default</Chip>
                  ) : (
                    r.pages_read > 0 && (
                      <Button size="sm" variant="outline" onClick={() => void updateSettings({ default_model_id: r.model_id })}>
                        Set as default
                      </Button>
                    )
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}

// A model's reading with its slips marked: changed or added text highlighted (hover shows
// what the reference has), missed reference text struck through.
function DiffText({ spans }: { spans: DiffSpan[] }) {
  return (
    <p className="text-sm leading-relaxed whitespace-pre-wrap select-text">
      {spans.map((s, i) =>
        s.op === "equal" ? (
          <span key={i}>{s.text}</span>
        ) : s.op === "delete" ? (
          <del key={i} title={`Missed: ${s.reference}`} className="rounded bg-danger/10 px-0.5 text-danger/70 decoration-danger">
            {s.reference}
          </del>
        ) : (
          <mark
            key={i}
            title={s.op === "insert" ? "Not in the reference" : `Reference: ${s.reference}`}
            className="rounded bg-danger/20 px-0.5 text-danger"
          >
            {s.text}
          </mark>
        ),
      )}
    </p>
  );
}

function SlipChip({ slips }: { slips: number | null }) {
  if (slips == null) return null;
  return slips === 0 ? <Chip tone="success">Exact</Chip> : <Chip tone="warning">{plural(slips, "slip")}</Chip>;
}

function Compare({ run }: { run: BenchRun }) {
  const { settings, updateSettings } = useApp();
  // Start where there's something to compare: the first file with reference text.
  const [fileId, setFileId] = useState(() => (run.files.find((f) => f.has_reference) ?? run.files[0])?.id ?? "");
  const [page, setPage] = useState(1);
  const [against, setAgainst] = useState<string>("");
  const [view, setView] = useState<PageView | null>(null);
  const [image, setImage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const file = run.files.find((f) => f.id === fileId);
  const progressKey = run.state === "done" ? "done" : run.pages_done;

  useEffect(() => {
    if (!fileId) return;
    let alive = true;
    setError(null);
    api.benchmarkPage(run.id, fileId, page, against || undefined).then(
      (v) => alive && setView(v),
      (err) => alive && setError(err instanceof Error ? err.message : String(err)),
    );
    void api.benchmarkImageUrl(run.id, fileId, page).then((u) => alive && setImage(u));
    return () => void (alive = false);
  }, [run.id, fileId, page, against, progressKey]);

  if (!file) return null;
  const best = run.summary?.leaderboard.find((r) => r.model_id === run.summary?.best_model_id);
  const lines = view?.reference?.split("\n").filter((l) => l.trim()).length ?? 0;

  return (
    <section aria-labelledby="compare-label" className="flex flex-col gap-2.5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <SectionLabel id="compare-label">Compare</SectionLabel>
        <div className="flex flex-wrap items-center gap-2">
          <label className="sr-only" htmlFor="compare-file">File</label>
          <select
            id="compare-file"
            value={fileId}
            onChange={(e) => {
              setFileId(e.target.value);
              setPage(1);
            }}
            className="h-8 max-w-[320px] rounded-3xl bg-line px-3 text-[13px] font-medium text-fg outline-none focus-visible:ring-2 focus-visible:ring-secondary"
          >
            {run.files.map((f) => (
              <option key={f.id} value={f.id}>
                {f.id}
                {f.has_reference ? " · reference" : ""}
              </option>
            ))}
          </select>
          {file.pages > 1 && (
            <span className="flex items-center gap-1 text-[13px] text-fg-muted">
              <Button size="sm" variant="ghost" icon={ChevronLeft} aria-label="Previous page" disabled={page <= 1} onClick={() => setPage((p) => p - 1)} />
              <span className="tabular-nums">Page {page} of {file.pages}</span>
              <Button size="sm" variant="ghost" icon={ChevronRight} aria-label="Next page" disabled={page >= file.pages} onClick={() => setPage((p) => p + 1)} />
            </span>
          )}
        </div>
      </div>

      {error && <Notice>{error}</Notice>}

      <Card className="grid gap-5 p-5 md:grid-cols-[minmax(220px,340px)_1fr]">
        <figure className="flex flex-col gap-2">
          <div className="flex min-h-[200px] items-start justify-center overflow-hidden rounded-xl bg-gradient-to-b from-white to-[#ecebff] p-3">
            {image && <img src={image} alt={`Page ${page} of ${file.id}`} className="max-h-[520px] w-full object-contain" />}
          </div>
          <figcaption className="truncate text-xs text-fg-muted" title={file.path}>
            {file.id}
          </figcaption>
        </figure>

        <div className="flex min-w-0 flex-col gap-3">
          {view?.reference_kind === "reference" ? (
            <div className="rounded-xl bg-line/50 px-4 py-3">
              <p className="pb-1 text-xs font-medium tracking-[0.3px] text-fg-muted uppercase">Reference text</p>
              <p className="text-sm whitespace-pre-wrap">{view.reference?.trim()}</p>
            </div>
          ) : (
            <div className="flex flex-wrap items-center gap-2 rounded-xl bg-line/50 px-4 py-3 text-sm text-fg-muted">
              <span>No reference text for this page. Compare against</span>
              <label className="sr-only" htmlFor="compare-against">Model to compare against</label>
              <select
                id="compare-against"
                value={against}
                onChange={(e) => setAgainst(e.target.value)}
                className="h-8 rounded-3xl bg-ink px-3 text-[13px] font-medium text-fg outline-none focus-visible:ring-2 focus-visible:ring-secondary"
              >
                <option value="">nothing</option>
                {run.models.map((m) => (
                  <option key={m.model_id} value={m.model_id}>
                    {m.name}
                  </option>
                ))}
              </select>
            </div>
          )}

          {!view ? (
            <p className="flex items-center gap-2 py-6 text-sm text-fg-muted">
              <Spinner className="text-secondary" /> Loading the readings
            </p>
          ) : view.reads.length === 0 ? (
            <p className="py-6 text-sm text-fg-muted">No model has read this page yet.</p>
          ) : (
            <ol className="flex flex-col gap-2">
              {view.reads.map((r) => (
                <li key={r.model_id} className="rounded-xl px-4 py-3 ring-1 ring-line ring-inset">
                  <div className="flex flex-wrap items-center gap-2 pb-1.5">
                    <span className="min-w-0 flex-1 truncate font-medium">{r.name}</span>
                    {r.error ? <Chip tone="danger">Failed</Chip> : <SlipChip slips={r.slips} />}
                    {r.seconds != null && <span className="text-xs text-fg-muted tabular-nums">{r.seconds.toFixed(2)} s</span>}
                  </div>
                  {r.error ? (
                    <p className="text-sm text-danger">{r.error}</p>
                  ) : r.diff.length ? (
                    <DiffText spans={r.diff} />
                  ) : (
                    <p className="text-sm whitespace-pre-wrap text-fg select-text">{r.text.trim() || "No text found."}</p>
                  )}
                </li>
              ))}
            </ol>
          )}

          {view && view.reads.length > 0 && (
          <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
            <span className="text-[13px] text-fg-muted">
              {plural(view?.reads.length ?? 0, "model")}
              {lines ? ` · ${plural(lines, "line")} compared` : ""}
            </span>
            {best && best.model_id !== settings?.default_model_id && (
              <Button size="sm" variant="light" onClick={() => void updateSettings({ default_model_id: best.model_id })}>
                Set {best.name} as default
              </Button>
            )}
          </div>
          )}
        </div>
      </Card>
    </section>
  );
}

export function BenchmarkRun({
  summary,
  onClose,
  onChanged,
  onDeleted,
}: {
  summary: BenchRun;
  onClose: () => void;
  onChanged: (selectId?: string) => void;
  onDeleted: () => void;
}) {
  const run = useRun(summary);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [reportUrl, setReportUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const busy = run.state === "running" || run.state === "queued";
  const total = run.pages_total * run.models.length;
  const current = run.models.find((m) => m.model_id === run.current_model_id);
  const problems = run.models.filter((m) => m.error && m.error !== "Cancelled");

  useEffect(() => {
    void api.benchmarkReportUrl(run.id, "md").then(setReportUrl);
  }, [run.id]);

  const act = async (fn: () => Promise<void>) => {
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const meta = useMemo(
    () =>
      [
        plural(run.files.length, "file"),
        plural(run.pages_total, "page"),
        plural(run.models.length, "model"),
        new Date(run.created_at * 1000).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }),
        SOURCE[run.source],
      ]
        .filter(Boolean)
        .join(" · "),
    [run],
  );

  return (
    <Card as="section" aria-label={`Benchmark ${run.name}`} className="flex flex-col">
      <div className="flex flex-wrap items-start gap-3 border-b border-line px-5 py-4">
        <div className="min-w-0 flex-1">
          <h3 className="font-heading text-[22px] leading-[1.15] font-semibold tracking-[-0.5px] break-words">{run.name}</h3>
          <p className="truncate text-[13px] text-fg-muted">{meta}</p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {busy ? (
            <Button size="sm" variant="outline" icon={Square} onClick={() => void act(async () => { await api.cancelBenchmark(run.id); onChanged(); })}>
              Stop
            </Button>
          ) : (
            <Button size="sm" variant="outline" icon={RotateCw} onClick={() => void act(async () => { const next = await api.rerunBenchmark(run.id); onChanged(next.id); })}>
              Run again
            </Button>
          )}
          {reportUrl && !busy && (
            <a
              href={reportUrl}
              download
              className="inline-flex h-8 items-center gap-[5px] rounded-3xl px-3 text-[13px] font-medium whitespace-nowrap text-fg ring-1 ring-line ring-inset transition-colors hover:bg-line/60"
            >
              <Download aria-hidden="true" className="h-3.5 w-3.5 shrink-0" />
              Report
            </a>
          )}
          {confirmDelete ? (
            <span className="flex items-center gap-1.5 rounded-3xl bg-line/60 py-0.5 pr-0.5 pl-3 text-[13px]">
              Delete this benchmark and its results?
              <Button size="sm" variant="light" onClick={() => void act(async () => { await api.deleteBenchmark(run.id); onDeleted(); })}>
                Delete
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setConfirmDelete(false)}>
                Keep
              </Button>
            </span>
          ) : (
            !busy && (
              <Button size="sm" variant="ghost" icon={Trash2} aria-label="Delete benchmark" title="Delete benchmark" onClick={() => setConfirmDelete(true)} />
            )
          )}
          <Button size="sm" variant="ghost" icon={X} aria-label="Close" title="Close" onClick={onClose} />
        </div>
      </div>

      <div className="flex flex-col gap-5 px-5 py-4">
        {error && <Notice>{error}</Notice>}
        {busy && (
          <div className="flex flex-col gap-2">
            <p className="flex items-center gap-2 text-sm text-fg-muted">
              <Spinner className="text-secondary" />
              {current
                ? current.state === "installing"
                  ? `Installing ${current.name}`
                  : `${current.name} is reading · ${run.pages_done} of ${total} pages`
                : "Starting"}
            </p>
            <ProgressBar value={total ? (100 * run.pages_done) / total : 0} label="Benchmark progress" />
          </div>
        )}
        {run.state === "error" && <Notice>{run.error ?? "The benchmark failed."}</Notice>}
        {run.state === "interrupted" && <Notice tone="warning">DocBox stopped before this benchmark finished. Run it again to finish it.</Notice>}
        {problems.length > 0 && (
          <Notice tone="warning">
            <ul className="flex flex-col gap-0.5">
              {problems.map((m) => (
                <li key={m.model_id}>
                  <span className="font-medium">{m.name}</span>: {m.error?.split("\n")[0]}
                </li>
              ))}
            </ul>
          </Notice>
        )}
        {run.summary && run.summary.ranked_by === "speed" && (
          <p className="text-[13px] text-fg-muted">
            No reference text, so models are ranked by speed. Add <code className="text-fg">name.gt.txt</code> files with the correct text to rank by accuracy.
          </p>
        )}
        <BenchmarkChart run={run} />
        <Leaderboard run={run} />
        <Compare run={run} />
      </div>
    </Card>
  );
}
