// A benchmark's leaderboard: one row of controls scoping both views below it, the graph
// (accuracy against cost, each model's sizes joined by a line) and the ranked bars (the
// score with its 95% interval, beside what each model costs). "This run" shows the run's
// own measurements; "OCRBench v1/v2" shows published scores for catalog models, against
// download size, for reference.
import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, ExternalLink } from "lucide-react";
import { api, type BenchRun, type LeaderboardRow, type ModelInfo, type ReferenceData } from "../lib/api";
import { useApp } from "../lib/app";
import {
  SERIES,
  SERIES_ORDER,
  bestPerFamily,
  familyLabel,
  mb,
  pct,
  plusMinus,
  secs,
  seriesOf,
  shortName,
  type SeriesKey,
} from "../lib/benchmarkSeries";
import { openInBrowser } from "../lib/external";
import { formatMb, plural } from "../lib/format";
import { BenchmarkBars, type BarRow } from "./BenchmarkBars";
import { BenchmarkChart, type ChartPoint } from "./BenchmarkChart";
import { Button, Chip, SectionLabel, cx } from "./ui";

type Source = "run" | "v1" | "v2";
type XKey = "speed" | "memory" | "load";
type Sizes = "all" | "best";

// Axis ticks in round decimal units (5,000 MB reads "5 GB", not "4.9 GB").
const mbTick = (v: number) => (v >= 1000 ? `${+(v / 1000).toFixed(1)} GB` : `${+v.toFixed(0)} MB`);
const secTick = (v: number) => `${v < 1 ? +v.toFixed(2) : +v.toFixed(1)} s`;

const X_AXES: Record<XKey, { label: string; short: string; format: (v: number) => string; of: (r: LeaderboardRow) => number | null }> = {
  speed: { label: "Seconds per page", short: "Per page", format: secTick, of: (r) => r.seconds_per_page },
  memory: { label: "Peak memory", short: "Peak RAM", format: mbTick, of: (r) => r.peak_memory_mb },
  load: { label: "Load time", short: "Load time", format: secTick, of: (r) => r.load_seconds },
};

function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="flex h-8 gap-0.5 rounded-3xl bg-line p-[3px]">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={o.value === value}
          onClick={() => onChange(o.value)}
          className={cx(
            "rounded-3xl px-3 text-[13px] font-medium whitespace-nowrap transition-colors",
            o.value === value ? "bg-fg text-ink" : "text-fg-muted hover:text-fg",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

interface FilterItem {
  id: string;
  label: string;
  series: SeriesKey;
}

function ModelFilter({ items, hidden, onChange }: { items: FilterItem[]; hidden: Set<string>; onChange: (next: Set<string>) => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onPointer = (e: PointerEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  const shown = items.filter((i) => !hidden.has(i.id)).length;
  const toggle = (id: string) => {
    const next = new Set(hidden);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    onChange(next);
  };
  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-expanded={open}
        aria-haspopup="true"
        onClick={() => setOpen((o) => !o)}
        className="flex h-8 items-center gap-1.5 rounded-3xl px-3 text-[13px] font-medium ring-1 ring-line ring-inset transition-colors hover:bg-line/60"
      >
        Models <span className="text-fg-muted tabular-nums">({shown}/{items.length})</span>
        <ChevronDown aria-hidden="true" className={cx("h-3.5 w-3.5 text-fg-muted transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div className="absolute right-0 z-20 mt-1.5 flex w-72 flex-col rounded-xl bg-ink p-1.5 shadow-[0_8px_24px_#00000066] ring-1 ring-line">
          <fieldset className="flex max-h-72 flex-col overflow-y-auto">
            <legend className="sr-only">Models to show</legend>
            {items.map((i) => (
              <label key={i.id} className="flex cursor-pointer items-center gap-2.5 rounded-lg px-2 py-1.5 text-[13px] hover:bg-line/50">
                <input type="checkbox" checked={!hidden.has(i.id)} onChange={() => toggle(i.id)} className="h-3.5 w-3.5 accent-secondary" />
                <span aria-hidden="true" className="h-2 w-2 shrink-0 rounded-full" style={{ background: SERIES[i.series].color }} />
                <span className="truncate">{i.label}</span>
              </label>
            ))}
          </fieldset>
          <div className="mt-1 flex justify-between border-t border-line px-2 pt-1.5">
            <button type="button" className="text-[13px] text-secondary hover:underline" onClick={() => onChange(new Set())}>
              Show all
            </button>
            <button type="button" className="text-[13px] text-fg-muted hover:text-fg" onClick={() => setOpen(false)}>
              Done
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function Legend({ series }: { series: SeriesKey[] }) {
  if (series.length < 2) return null;
  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[13px] text-fg-muted" aria-label="Legend">
      {series.map((s) => (
        <li key={s} className="flex items-center gap-1.5">
          <svg aria-hidden="true" width="16" height="8">
            <line x1="1" x2="15" y1="4" y2="4" stroke={SERIES[s].color} strokeWidth="2" strokeLinecap="round" />
            <circle cx="8" cy="4" r="3" fill={SERIES[s].color} />
          </svg>
          {SERIES[s].label}
        </li>
      ))}
    </ul>
  );
}

// --- this run -------------------------------------------------------------------------

function runDetails(r: LeaderboardRow, scored: boolean): [string, string][] {
  const accuracy = scored ? [pct(r.accuracy), plusMinus(r.accuracy_margin)].filter(Boolean).join(" ") : "–";
  return [
    ["Accuracy", accuracy],
    ["Per page", secs(r.seconds_per_page)],
    ["Load", secs(r.load_seconds, 1)],
    ["Peak RAM", r.peak_memory_mb == null && r.memory_note ? "not measured" : mb(r.peak_memory_mb)],
    ["Word errors", pct(r.wer)],
    ["Confidence", pct(r.mean_confidence)],
    ["Pages failed", String(r.pages_failed)],
    ...(scored && r.scored_units ? [["Scored on", plural(r.scored_units, "reference")] as [string, string]] : []),
  ];
}

// --- the section ----------------------------------------------------------------------

export function BenchmarkLeaderboard({ run }: { run: BenchRun }) {
  const { settings, updateSettings } = useApp();
  const [source, setSource] = useState<Source>("run");
  const [xKey, setXKey] = useState<XKey>("speed");
  const [split, setSplit] = useState<"en" | "zh">("en");
  const [sizes, setSizes] = useState<Sizes>("all");
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [reference, setReference] = useState<ReferenceData | null>(null);
  const [catalog, setCatalog] = useState<ModelInfo[] | null>(null);

  useEffect(() => {
    if (source === "run" || (reference && catalog)) return;
    api.benchmarkReference().then(setReference, () => setReference(null));
    api.listModels().then(setCatalog, () => setCatalog([]));
  }, [source, reference, catalog]);

  const scored = run.summary?.ranked_by === "cer";
  const rows = useMemo(() => run.summary?.leaderboard ?? [], [run.summary]);
  const yOf = (r: LeaderboardRow) => (scored ? r.accuracy : r.mean_confidence);
  const familyOf = (r: LeaderboardRow) => r.family ?? r.model_id;
  const hasSizes = rows.some((r, i) => r.family && rows.findIndex((q) => q.family === r.family) !== i);

  // --- this run: graph points and bars
  const read = rows.filter((r) => r.pages_read > 0);
  const visible = read.filter((r) => !hidden.has(r.model_id));
  const shownRows = sizes === "best" ? bestPerFamily(visible, familyOf, yOf) : visible;
  const x = X_AXES[xKey];
  const runPoints: ChartPoint[] = shownRows
    .filter((r) => x.of(r) != null && yOf(r) != null)
    .map((r) => ({
      id: r.model_id,
      name: r.name,
      family: familyOf(r),
      label: familyLabel(r.family, r.name),
      variant: r.variant,
      series: seriesOf(r.engine),
      x: Math.max(0.001, x.of(r)!),
      y: yOf(r)! * 100,
      rows: runDetails(r, scored),
    }));
  const unplotted = shownRows.filter((r) => x.of(r) == null || yOf(r) == null);
  const runBars: BarRow[] = [...shownRows]
    .sort((a, b) => (yOf(b) ?? -1) - (yOf(a) ?? -1))
    .map((r) => {
      const y = yOf(r);
      const m = scored ? r.accuracy_margin : null;
      const isDefault = settings?.default_model_id === r.model_id;
      return {
        id: r.model_id,
        name: r.name,
        label: familyLabel(r.family, r.name),
        variant: r.variant,
        engine: r.engine,
        series: seriesOf(r.engine),
        value: y,
        low: y != null && m != null ? y - m : null,
        high: y != null && m != null ? y + m : null,
        display: (
          <>
            <span className="font-medium text-fg">{pct(y)}</span>
            {m != null && <span className="ml-1 text-xs text-fg-muted">{plusMinus(m)}</span>}
          </>
        ),
        cells: [
          secs(r.seconds_per_page),
          r.peak_memory_mb == null && r.memory_note ? <span title={r.memory_note}>not measured</span> : mb(r.peak_memory_mb),
          secs(r.load_seconds, 1),
        ],
        details: runDetails(r, scored),
        note: r.pages_failed > 0 ? <span className="text-danger">{plural(r.pages_failed, "page")} failed</span> : undefined,
        action: isDefault ? (
          <Chip tone="success">Default</Chip>
        ) : (
          <Button size="sm" variant="outline" onClick={() => void updateSettings({ default_model_id: r.model_id })}>
            Set as default
          </Button>
        ),
      };
    });

  // --- published scores: graph points and bars
  const bench = source === "v1" ? "ocrbench_v1" : "ocrbench_v2";
  const refMax = reference?.benchmarks[bench].max ?? (source === "v1" ? 1000 : 100);
  const refItems = useMemo(() => {
    if (!reference || !catalog || source === "run") return [];
    const inRun = new Set(run.models.map((m) => m.model_id));
    return reference.models.flatMap((m) => {
      const info = catalog.find((c) => c.id === m.model_id);
      const score = source === "v1" ? m.scores.ocrbench_v1 : m.scores.ocrbench_v2;
      const value = source === "v1" ? m.scores.ocrbench_v1?.value : m.scores.ocrbench_v2?.[split];
      if (!info || !score || value == null) return [];
      return [{ m, info, score, value, installed: info.status === "ready" || inRun.has(m.model_id) }];
    });
  }, [reference, catalog, source, split, run.models]);
  const refShown = refItems.filter((i) => !hidden.has(i.m.model_id));
  const refPoints: ChartPoint[] = refShown.map(({ m, info, score, value, installed }) => ({
    id: m.model_id,
    name: m.label,
    family: m.model_id,
    label: `${m.label}${score.self_reported ? " *" : ""}`,
    variant: null,
    series: seriesOf(info.engine),
    x: Math.max(1, info.approx_download_mb),
    y: value,
    hollow: !installed,
    rows: [
      [source === "v1" ? "OCRBench v1" : `OCRBench v2 ${split.toUpperCase()}`, `${source === "v1" ? value : value.toFixed(1)} / ${refMax}`],
      ["Download", formatMb(info.approx_download_mb)],
      ["Reported by", score.self_reported ? "the model's makers" : "OCRBench leaderboard"],
      ["Here", installed ? "installed" : "not installed"],
    ],
  }));
  const refBars: BarRow[] = [...refShown]
    .sort((a, b) => b.value - a.value)
    .map(({ m, info, score, value, installed }) => ({
      id: m.model_id,
      name: m.label,
      label: m.label,
      variant: null,
      engine: info.engine,
      series: seriesOf(info.engine),
      value: value / refMax,
      display: <span className="font-medium text-fg">{source === "v1" ? value : value.toFixed(1)}</span>,
      cells: [
        formatMb(info.approx_download_mb),
        <a key="src" href={score.url} target="_blank" rel="noreferrer" onClick={openInBrowser} className="inline-flex items-center gap-1 text-secondary hover:underline">
          {score.source}
          {score.self_reported ? " *" : ""}
          <ExternalLink aria-hidden="true" className="h-3 w-3" />
        </a>,
      ],
      details: [
        ["Score", `${source === "v1" ? value : value.toFixed(1)} / ${refMax}`],
        ["Download", formatMb(info.approx_download_mb)],
        ["Reported by", score.self_reported ? "the model's makers" : "OCRBench leaderboard"],
        ["Here", installed ? "installed" : "not installed"],
      ],
    }));

  const points = source === "run" ? runPoints : refPoints;
  const series = SERIES_ORDER.filter((s) => points.some((p) => p.series === s));
  const filterItems: FilterItem[] =
    source === "run"
      ? read.map((r) => ({ id: r.model_id, label: r.variant ? `${familyLabel(r.family, r.name)} [${r.variant.toLowerCase()}]` : shortName(r.name), series: seriesOf(r.engine) }))
      : refItems.map(({ m, info }) => ({ id: m.model_id, label: m.label, series: seriesOf(info.engine) }));
  const busy = run.state === "running" || run.state === "queued";
  const unplaced = source === "run" || !reference ? [] : run.models.filter((m) => !refItems.some((i) => i.m.model_id === m.model_id)).map((m) => m.name);

  const empty =
    source === "run"
      ? read.length === 0
        ? busy
          ? "Models appear here as they finish reading."
          : "No model finished reading, so there's nothing to rank."
        : visible.length === 0
          ? "No models selected."
          : null
      : !reference || !catalog
        ? "Loading the published scores…"
        : refItems.length === 0
          ? "No model in DocBox's catalog has a published score on this benchmark."
          : refShown.length === 0
            ? "No models selected."
            : null;

  return (
    <section aria-labelledby="leaderboard-label" className="flex flex-col gap-3">
      <SectionLabel id="leaderboard-label">Leaderboard</SectionLabel>
      <div className="flex flex-wrap items-center gap-2">
        <Segmented
          label="Scores from"
          value={source}
          onChange={setSource}
          options={[
            { value: "run", label: "This run" },
            { value: "v1", label: "OCRBench v1" },
            { value: "v2", label: "OCRBench v2" },
          ]}
        />
        {source === "run" && (
          <Segmented label="Cost" value={xKey} onChange={setXKey} options={(Object.keys(X_AXES) as XKey[]).map((k) => ({ value: k, label: X_AXES[k].short }))} />
        )}
        {source === "run" && hasSizes && (
          <Segmented
            label="Sizes of a model"
            value={sizes}
            onChange={setSizes}
            options={[
              { value: "all", label: "Every size" },
              { value: "best", label: "Best size" },
            ]}
          />
        )}
        {source === "v2" && (
          <Segmented
            label="OCRBench v2 track"
            value={split}
            onChange={setSplit}
            options={[
              { value: "en", label: "English" },
              { value: "zh", label: "Chinese" },
            ]}
          />
        )}
        <div className="ml-auto">{filterItems.length > 1 && <ModelFilter items={filterItems} hidden={hidden} onChange={setHidden} />}</div>
      </div>

      <div className="flex flex-col gap-3 rounded-2xl p-4 ring-1 ring-line ring-inset">
        {empty ? (
          <div className="flex flex-col items-center gap-2 py-10 text-center text-sm text-fg-muted">
            <p>{empty}</p>
            {empty === "No models selected." && (
              <Button size="sm" variant="outline" onClick={() => setHidden(new Set())}>
                Show all
              </Button>
            )}
          </div>
        ) : (
          <>
            <Legend series={series} />
            {points.length > 0 ? (
              <BenchmarkChart
                points={points}
                title={
                  source === "run"
                    ? scored
                      ? "Accuracy (1 − character error rate)"
                      : "Mean confidence (no reference text)"
                    : source === "v1"
                      ? "OCRBench v1 score (of 1,000)"
                      : `OCRBench v2 ${split === "en" ? "English" : "Chinese"} (of 100)`
                }
                xLabel={source === "run" ? x.label : "Download size"}
                xFormat={source === "run" ? x.format : mbTick}
                yFormat={source === "run" ? (v) => `${v}%` : (v) => String(v)}
                yCap={source === "run" ? 100 : refMax}
                ariaLabel={`${source === "run" ? (scored ? "Accuracy" : "Mean confidence") : "Published score"} against ${source === "run" ? x.label.toLowerCase() : "download size"} for ${plural(points.length, "model")}; the table below lists every value.`}
              />
            ) : (
              <p className="py-6 text-center text-sm text-fg-muted">No model has a {x.short.toLowerCase()} figure to plot.</p>
            )}
            {source === "run" && unplotted.length > 0 && (
              <p className="text-[13px] text-fg-muted">
                Not on the graph:{" "}
                {unplotted
                  .map((r) => `${shortName(r.name)} (${x.of(r) == null ? (xKey === "memory" && r.memory_note ? r.memory_note.charAt(0).toLowerCase() + r.memory_note.slice(1) : `no ${x.short.toLowerCase()} figure`) : "no score yet"})`)
                  .join("; ")}
                .
              </p>
            )}
            {source === "run" && !scored && (
              <p className="text-[13px] text-fg-muted">
                Without reference text the height is each model's own confidence, which isn't accuracy. Add <code className="text-fg">name.gt.txt</code> files to rank by accuracy.
              </p>
            )}
            <div className="border-t border-line pt-3">
              {source === "run" ? (
                <BenchmarkBars
                  rows={runBars}
                  caption={`Models ranked by ${scored ? "accuracy against the reference text, with 95% intervals" : "their own confidence (no reference text)"}`}
                  valueHeader={scored ? "Accuracy" : "Confidence"}
                  headers={["Per page", "Peak RAM", "Load"]}
                  tickFormat={(t) => `${Math.round(t * 100)}%`}
                  actions
                />
              ) : (
                <BenchmarkBars
                  rows={refBars}
                  caption="Published scores and their sources"
                  valueHeader="Score"
                  headers={["Download", "Source"]}
                  tickFormat={(t) => String(Math.round(t * refMax))}
                />
              )}
            </div>
            {source === "run" && scored && runBars.some((r) => r.low != null) && (
              <p className="text-[13px] text-fg-muted">
                ± is a 95% interval: how much accuracy varies between the pages or documents with reference text. Fewer of them means a wider interval.
              </p>
            )}
            {source !== "run" && reference && (
              <div className="flex flex-col gap-2 text-[13px] text-fg-muted">
                <p>
                  Published scores for reference, not measured on your files. {reference.benchmarks[bench].about} * Reported by the model's makers. Hollow points
                  aren't installed here.
                </p>
                {unplaced.length > 0 && <p>Not on {source === "v1" ? "OCRBench v1" : "OCRBench v2"}: {unplaced.join(", ")}.</p>}
                <ul className="flex list-disc flex-col gap-1 pl-4">
                  {reference.notes.map((n) => (
                    <li key={n}>{n}</li>
                  ))}
                </ul>
                <p>Scores checked {reference.checked}.</p>
              </div>
            )}
          </>
        )}
      </div>
    </section>
  );
}
