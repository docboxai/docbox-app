// The benchmark graph: every model as a point, how well it reads (up) against what it
// costs (left is cheaper), like DeepSWE's score-vs-cost chart. "This run" plots the
// run's own measurements; "OCRBench v1/v2" plots published scores for the vision models
// that have one, against the model's download size, as a reference.
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { ExternalLink } from "lucide-react";
import { api, type BenchRun, type ModelInfo, type ReferenceData } from "../lib/api";
import { formatMb } from "../lib/format";
import { SectionLabel, cx } from "./ui";

type Source = "run" | "v1" | "v2";
type XKey = "speed" | "memory" | "load";
type Family = "paddle" | "tesseract" | "ollama" | "other";

// Three hues at most on a scatter (all pairs must stay distinguishable for colour-blind
// readers); every other engine shares the neutral. Every point is also labelled by name.
const FAMILY: Record<Family, { label: string; color: string }> = {
  paddle: { label: "PaddleOCR", color: "var(--color-series-1)" },
  tesseract: { label: "Tesseract", color: "var(--color-series-2)" },
  ollama: { label: "Ollama vision models", color: "var(--color-series-3)" },
  other: { label: "Other engines", color: "var(--color-series-other)" },
};

function familyOf(modelId: string): Family {
  if (modelId.startsWith("paddleocr")) return "paddle";
  if (modelId.startsWith("tesseract")) return "tesseract";
  if (modelId.startsWith("ollama:")) return "ollama";
  return "other";
}

interface Point {
  id: string;
  // Beside the point; `name` (in full) heads the tooltip.
  label: string;
  name: string;
  family: Family;
  x: number;
  y: number;
  filled: boolean;
  best: boolean;
  rows: [string, string][];
}

// Short names for point labels ("PaddleOCR Balanced — Chinese + English" -> "PaddleOCR
// Balanced"); the tooltip keeps the full name.
const ENGINE_NAMES = new Set(["PaddleOCR", "Tesseract", "EasyOCR", "Ollama", "NVIDIA NIM"]);
export function shortName(name: string): string {
  const [head, tail] = name.split(" — ");
  if (!tail) return name;
  return ENGINE_NAMES.has(head) ? `${head} ${tail}` : head;
}

// Axis ticks in round decimal units (5,000 MB reads "5 GB", not "4.9 GB").
const mbTick = (v: number) => (v >= 1000 ? `${+(v / 1000).toFixed(1)} GB` : `${+v.toFixed(0)} MB`);

const pct = (v: number | null | undefined) => (v == null ? "–" : `${(v * 100).toFixed(1)}%`);
const secs = (v: number | null | undefined, digits = 2) => (v == null ? "–" : `${v.toFixed(digits)} s`);

const X_AXES: Record<XKey, { label: string; short: string; unit: (v: number) => string }> = {
  speed: { label: "Seconds per page", short: "Per page", unit: (v) => `${v < 1 ? v.toFixed(2) : v.toFixed(1)} s` },
  memory: { label: "Peak memory", short: "Peak RAM", unit: mbTick },
  load: { label: "Load time", short: "Load time", unit: (v) => `${v < 1 ? v.toFixed(2) : v.toFixed(1)} s` },
};

// --- scales ---------------------------------------------------------------------------

// 1-2-5 steps: the log axis only ever shows values people read at a glance.
function step125(v: number, dir: "down" | "up"): number {
  const p = 10 ** Math.floor(Math.log10(v));
  const steps = [1, 2, 5, 10].map((m) => m * p);
  return dir === "down" ? [...steps].reverse().find((s) => s <= v) ?? p : steps.find((s) => s >= v) ?? 10 * p;
}

function logDomain(values: number[]): [number, number] {
  const lo = Math.max(1e-3, Math.min(...values));
  const hi = Math.max(...values);
  return [step125(lo / 1.15, "down"), step125(hi * 1.15, "up")];
}

function logTicks([lo, hi]: [number, number]): number[] {
  const ticks: number[] = [];
  for (let p = Math.floor(Math.log10(lo)); p <= Math.ceil(Math.log10(hi)); p++) {
    for (const m of [1, 2, 5]) {
      const t = m * 10 ** p;
      if (t >= lo * 0.999 && t <= hi * 1.001) ticks.push(t);
    }
  }
  return ticks.length > 7 ? ticks.filter((t) => Math.abs(Math.log10(t) % 1) < 1e-9 || t === lo || t === hi) : ticks;
}

function linearDomain(values: number[], cap: number): { domain: [number, number]; ticks: number[] } {
  let lo = Math.min(...values);
  let hi = Math.max(...values);
  const pad = Math.max((hi - lo) * 0.18, cap * 0.02);
  lo = Math.max(0, lo - pad);
  hi = Math.min(cap, hi + pad);
  const span = hi - lo;
  const step = [1, 2, 5, 10, 20, 25, 50, 100, 200].map((s) => (s * cap) / 100).find((s) => span / s <= 5) ?? cap / 5;
  const d0 = Math.floor(lo / step) * step;
  const d1 = Math.min(cap, Math.ceil(hi / step) * step);
  const ticks: number[] = [];
  for (let t = d0; t <= d1 + step / 1000; t += step) ticks.push(Number(t.toFixed(6)));
  return { domain: [d0, d1], ticks };
}

// The points nothing else beats on both counts: cheaper-or-equal and better.
function frontier(points: Point[]): Point[] {
  const out: Point[] = [];
  let bestY = -Infinity;
  for (const p of [...points].sort((a, b) => a.x - b.x || b.y - a.y)) {
    if (p.y > bestY) {
      out.push(p);
      bestY = p.y;
    }
  }
  return out;
}

// --- controls -------------------------------------------------------------------------

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

// --- the plot -------------------------------------------------------------------------

const HEIGHT = 360;
const M = { top: 30, right: 28, bottom: 50, left: 58 };
const LABEL_PX = 6.7; // average glyph width at 12px, for placing labels before they render

function Plot({
  points,
  xLabel,
  xFormat,
  yLabel,
  yFormat,
  yCap,
  showFrontier,
}: {
  points: Point[];
  showFrontier: boolean;
  xLabel: string;
  xFormat: (v: number) => string;
  yLabel: string;
  yFormat: (v: number) => string;
  yCap: number;
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(760);
  const [active, setActive] = useState<string | null>(null);

  useLayoutEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setWidth(Math.max(320, Math.floor(entry.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const xDomain = logDomain(points.map((p) => p.x));
  const xTicks = logTicks(xDomain);
  const { domain: yDomain, ticks: yTicks } = linearDomain(points.map((p) => p.y), yCap);
  const plotW = width - M.left - M.right;
  const plotH = HEIGHT - M.top - M.bottom;
  const sx = (v: number) =>
    M.left + ((Math.log10(v) - Math.log10(xDomain[0])) / (Math.log10(xDomain[1]) - Math.log10(xDomain[0]))) * plotW;
  const sy = (v: number) => M.top + (1 - (v - yDomain[0]) / (yDomain[1] - yDomain[0] || 1)) * plotH;

  const front = showFrontier ? frontier(points) : [];

  // Direct labels beside each point; nudged down when they would overlap one already
  // placed, with a hairline back to the point when nudged.
  const labels = (() => {
    const placed: { x1: number; x2: number; y: number }[] = [];
    return [...points]
      .sort((a, b) => sy(a.y) - sy(b.y))
      .map((p) => {
        const px = sx(p.x);
        const py = sy(p.y);
        const w = p.label.length * LABEL_PX;
        const right = px + 12 + w <= width - 6;
        const x1 = right ? px + 12 : px - 12 - w;
        let y = py + 4;
        for (let guard = 0; guard < 20; guard++) {
          const hit = placed.find((b) => Math.abs(b.y - y) < 15 && x1 < b.x2 && x1 + w > b.x1);
          if (!hit) break;
          y = hit.y + 15;
        }
        placed.push({ x1, x2: x1 + w, y });
        return { id: p.id, x: right ? px + 12 : px - 12, y, anchor: right ? "start" : "end", moved: Math.abs(y - (py + 4)) > 3, px, py };
      });
  })();

  const activePoint = points.find((p) => p.id === active);

  return (
    <div ref={wrapRef} className="relative w-full">
      <svg width={width} height={HEIGHT} role="img" aria-label={`${yLabel} against ${xLabel} for ${points.length} models`} className="block">
        {/* grid and axes: hairlines, one step off the surface */}
        {yTicks.map((t) => (
          <g key={`y${t}`}>
            <line x1={M.left} x2={width - M.right} y1={sy(t)} y2={sy(t)} stroke="var(--color-line)" strokeWidth={1} />
            <text x={M.left - 10} y={sy(t) + 4} textAnchor="end" fontSize={11} fill="var(--color-fg-muted)" className="tabular-nums">
              {yFormat(t)}
            </text>
          </g>
        ))}
        {xTicks.map((t) => (
          <g key={`x${t}`}>
            <line x1={sx(t)} x2={sx(t)} y1={M.top} y2={HEIGHT - M.bottom} stroke="var(--color-line)" strokeWidth={1} opacity={0.6} />
            <text x={sx(t)} y={HEIGHT - M.bottom + 18} textAnchor="middle" fontSize={11} fill="var(--color-fg-muted)" className="tabular-nums">
              {xFormat(t)}
            </text>
          </g>
        ))}
        <line x1={M.left} x2={width - M.right} y1={HEIGHT - M.bottom} y2={HEIGHT - M.bottom} stroke="var(--color-fg-muted)" strokeOpacity={0.5} strokeWidth={1} />
        <text x={M.left + plotW / 2} y={HEIGHT - 10} textAnchor="middle" fontSize={12} fill="var(--color-fg-muted)">
          {xLabel} · log scale, less is better
        </text>
        <text x={16} y={M.top + plotH / 2} textAnchor="middle" fontSize={12} fill="var(--color-fg-muted)" transform={`rotate(-90 16 ${M.top + plotH / 2})`}>
          {yLabel}
        </text>
        {showFrontier && (
          <text x={M.left + 8} y={M.top - 10} fontSize={12} fontWeight={600} fill="var(--color-fg)">
            ↖ most efficient
          </text>
        )}

        {/* best trade-offs: the frontier no other model beats on both axes */}
        {front.length > 1 && (
          <polyline
            points={front.map((p) => `${sx(p.x)},${sy(p.y)}`).join(" ")}
            fill="none"
            stroke="var(--color-fg-muted)"
            strokeWidth={1.5}
            strokeDasharray="5 5"
          />
        )}

        {labels.map((l) =>
          l.moved ? <line key={`lead${l.id}`} x1={l.px} y1={l.py} x2={l.x} y2={l.y - 4} stroke="var(--color-fg-muted)" strokeWidth={1} opacity={0.6} /> : null,
        )}

        {points.map((p) => {
          const color = FAMILY[p.family].color;
          const r = p.best ? 7 : 6;
          return (
            <g
              key={p.id}
              tabIndex={0}
              role="img"
              aria-label={`${p.name}: ${p.rows.map(([k, v]) => `${k} ${v}`).join(", ")}`}
              onMouseEnter={() => setActive(p.id)}
              onMouseLeave={() => setActive((a) => (a === p.id ? null : a))}
              onFocus={() => setActive(p.id)}
              onBlur={() => setActive((a) => (a === p.id ? null : a))}
              className="cursor-default outline-none [&:focus-visible>circle:last-child]:stroke-secondary"
            >
              {/* the hit target is bigger than the mark */}
              <circle cx={sx(p.x)} cy={sy(p.y)} r={14} fill="transparent" />
              <circle
                cx={sx(p.x)}
                cy={sy(p.y)}
                r={active === p.id ? r + 1.5 : r}
                fill={p.filled ? color : "var(--color-surface)"}
                stroke={p.filled ? "var(--color-surface)" : color}
                strokeWidth={2}
              />
            </g>
          );
        })}

        {labels.map((l) => {
          const p = points.find((q) => q.id === l.id)!;
          return (
            <text key={`label${l.id}`} x={l.x} y={l.y} textAnchor={l.anchor as "start" | "end"} fontSize={12} fontWeight={p.best ? 600 : 400} fill={p.best ? "var(--color-fg)" : "var(--color-fg-muted)"} stroke="var(--color-surface)" strokeWidth={4} strokeLinejoin="round" paintOrder="stroke" pointerEvents="none">
              {p.label}
            </text>
          );
        })}
      </svg>

      {activePoint && (
        <div
          role="tooltip"
          className="pointer-events-none absolute z-10 w-60 rounded-xl bg-ink px-3 py-2.5 text-[13px] shadow-[0_8px_24px_#00000066] ring-1 ring-line"
          style={{
            left: Math.min(Math.max(8, sx(activePoint.x) + 16), width - 248),
            top: Math.max(4, sy(activePoint.y) - 20),
          }}
        >
          <p className="flex items-center gap-2 pb-1.5 font-medium text-fg">
            <span aria-hidden="true" className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: FAMILY[activePoint.family].color }} />
            {activePoint.name}
          </p>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
            {activePoint.rows.map(([k, v]) => (
              <div key={k} className="contents">
                <dt className="text-fg-muted">{k}</dt>
                <dd className="text-right text-fg tabular-nums">{v}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </div>
  );
}

function Legend({ families, hollow, frontier: withFrontier }: { families: Family[]; hollow: boolean; frontier: boolean }) {
  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[13px] text-fg-muted" aria-label="Legend">
      {families.map((f) => (
        <li key={f} className="flex items-center gap-1.5">
          <span aria-hidden="true" className="h-2.5 w-2.5 rounded-full" style={{ background: FAMILY[f].color }} />
          {FAMILY[f].label}
        </li>
      ))}
      {hollow && (
        <li className="flex items-center gap-1.5">
          <span aria-hidden="true" className="h-2.5 w-2.5 rounded-full ring-2 ring-fg-muted ring-inset" />
          not installed here
        </li>
      )}
      {withFrontier && (
      <li className="flex items-center gap-1.5">
        <svg aria-hidden="true" width="18" height="6">
          <line x1="0" x2="18" y1="3" y2="3" stroke="var(--color-fg-muted)" strokeWidth="1.5" strokeDasharray="4 3" />
        </svg>
        best trade-offs
      </li>
      )}
    </ul>
  );
}

// --- the section ----------------------------------------------------------------------

export function BenchmarkChart({ run }: { run: BenchRun }) {
  const [source, setSource] = useState<Source>("run");
  const [xKey, setXKey] = useState<XKey>("speed");
  const [split, setSplit] = useState<"en" | "zh">("en");
  const [reference, setReference] = useState<ReferenceData | null>(null);
  const [catalog, setCatalog] = useState<ModelInfo[] | null>(null);

  useEffect(() => {
    if (source === "run" || (reference && catalog)) return;
    api.benchmarkReference().then(setReference, () => setReference(null));
    api.listModels().then(setCatalog, () => setCatalog([]));
  }, [source, reference, catalog]);

  const scored = run.summary?.ranked_by === "cer";
  const rows = run.summary?.leaderboard ?? [];

  const runPoints = useMemo<Point[]>(() => {
    const value = (r: (typeof rows)[number]) =>
      xKey === "speed" ? r.seconds_per_page : xKey === "memory" ? r.peak_memory_mb : r.load_seconds;
    return rows
      .filter((r) => r.pages_read > 0 && value(r) != null && (scored ? r.accuracy != null : r.mean_confidence != null))
      .map((r) => ({
        id: r.model_id,
        label: shortName(r.name),
        name: r.name,
        family: familyOf(r.model_id),
        x: Math.max(0.01, value(r)!),
        y: (scored ? r.accuracy! : r.mean_confidence!) * 100,
        filled: true,
        best: r.model_id === run.summary?.best_model_id,
        rows: [
          ["Accuracy", pct(r.accuracy)],
          ["WER", pct(r.wer)],
          ["Per page", secs(r.seconds_per_page)],
          ["Load", secs(r.load_seconds, 1)],
          ["Peak RAM", r.peak_memory_mb == null ? "–" : formatMb(r.peak_memory_mb)],
          ["Confidence", pct(r.mean_confidence)],
          ["Pages failed", String(r.pages_failed)],
        ],
      }));
  }, [rows, xKey, scored, run.summary?.best_model_id]);

  const refPoints = useMemo<Point[]>(() => {
    if (!reference || !catalog || source === "run") return [];
    const inRun = new Set(run.models.map((m) => m.model_id));
    const max = reference.benchmarks[source === "v1" ? "ocrbench_v1" : "ocrbench_v2"].max;
    const out: Point[] = [];
    for (const m of reference.models) {
      const info = catalog.find((c) => c.id === m.model_id);
      const score = source === "v1" ? m.scores.ocrbench_v1 : m.scores.ocrbench_v2;
      const y = source === "v1" ? m.scores.ocrbench_v1?.value : m.scores.ocrbench_v2?.[split];
      if (!info || !score || y == null) continue;
      out.push({
        id: m.model_id,
        label: `${m.label}${score.self_reported ? " *" : ""}`,
        name: m.label,
        family: familyOf(m.model_id),
        x: info.approx_download_mb,
        y,
        filled: info.status === "ready" || inRun.has(m.model_id),
        best: false,
        rows: [
          [source === "v1" ? "OCRBench v1" : `OCRBench v2 ${split.toUpperCase()}`, `${source === "v1" ? y : y.toFixed(1)} / ${max}`],
          ["Download", formatMb(info.approx_download_mb)],
          ["Reported by", score.self_reported ? "the model's makers" : "OCRBench leaderboard"],
          ["Here", info.status === "ready" ? "installed" : "not installed"],
        ],
      });
    }
    // No "best" and no frontier here: these scores come from different sources (makers'
    // own reports, the official leaderboard), so ranking them against each other misleads.
    return out;
  }, [reference, catalog, source, split, run.models]);

  const points = source === "run" ? runPoints : refPoints;
  const families = (["paddle", "tesseract", "ollama", "other"] as Family[]).filter((f) => points.some((p) => p.family === f));
  const refMax = source === "v1" ? 1000 : 100;

  // Models in this run that OCRBench can't place (classic engines, unscored models).
  const unplaced =
    source === "run" || !reference
      ? []
      : run.models.filter((m) => !refPoints.some((p) => p.id === m.model_id)).map((m) => m.name);
  const refTableModels = reference?.models.filter((m) => (source === "v1" ? m.scores.ocrbench_v1 : m.scores.ocrbench_v2?.[split] != null)) ?? [];

  return (
    <section aria-labelledby="graph-label" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <SectionLabel id="graph-label">Accuracy against cost</SectionLabel>
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
            <Segmented
              label="Cost axis"
              value={xKey}
              onChange={setXKey}
              options={(Object.keys(X_AXES) as XKey[]).map((k) => ({ value: k, label: X_AXES[k].short }))}
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
        </div>
      </div>

      <div className="flex flex-col gap-3 rounded-2xl p-4 ring-1 ring-line ring-inset">
        {points.length === 0 ? (
          <p className="py-10 text-center text-sm text-fg-muted">
            {source === "run"
              ? run.state === "running" || run.state === "queued"
                ? "Models appear here as they finish reading."
                : "No model finished reading, so there's nothing to plot."
              : reference && catalog
                ? "No model in DocBox's catalog has a published score on this benchmark."
                : "Loading the published scores…"}
          </p>
        ) : (
          <>
            <Legend families={families} hollow={source !== "run" && points.some((p) => !p.filled)} frontier={source === "run"} />
            <Plot
              points={points}
              xLabel={source === "run" ? X_AXES[xKey].label : "Download size"}
              xFormat={source === "run" ? X_AXES[xKey].unit : mbTick}
              yLabel={
                source === "run"
                  ? scored
                    ? "Accuracy (1 − character error rate)"
                    : "Mean confidence (no reference text)"
                  : source === "v1"
                    ? "OCRBench v1 score (of 1,000)"
                    : `OCRBench v2 ${split === "en" ? "English" : "Chinese"} (of 100)`
              }
              yFormat={source === "run" ? (v) => `${v}%` : (v) => String(v)}
              yCap={source === "run" ? 100 : refMax}
              showFrontier={source === "run"}
            />
          </>
        )}

        {source === "run" && !scored && points.length > 0 && (
          <p className="text-[13px] text-fg-muted">
            Without reference text the height is each model's own confidence, which isn't accuracy. Add <code className="text-fg">name.gt.txt</code> files to plot accuracy.
          </p>
        )}

        {source !== "run" && reference && (
          <div className="flex flex-col gap-3 border-t border-line pt-3 text-[13px] text-fg-muted">
            <p>
              Published scores for reference, not measured on your files. {reference.benchmarks[source === "v1" ? "ocrbench_v1" : "ocrbench_v2"].about}{" "}
              * Reported by the model's makers.
            </p>
            {unplaced.length > 0 && <p>Not on {source === "v1" ? "OCRBench v1" : "OCRBench v2"}: {unplaced.join(", ")}.</p>}
            <div className="overflow-x-auto">
              <table className="w-full min-w-[560px] text-left">
                <caption className="sr-only">Published scores and their sources</caption>
                <thead>
                  <tr className="text-xs tracking-[0.3px] uppercase">
                    <th scope="col" className="py-1.5 pr-3 font-medium">Model</th>
                    <th scope="col" className="py-1.5 pr-3 text-right font-medium">Score</th>
                    <th scope="col" className="py-1.5 font-medium">Source</th>
                  </tr>
                </thead>
                <tbody>
                  {refTableModels.map((m) => {
                    const s = source === "v1" ? m.scores.ocrbench_v1! : m.scores.ocrbench_v2!;
                    const value = source === "v1" ? m.scores.ocrbench_v1!.value : m.scores.ocrbench_v2![split];
                    return (
                      <tr key={m.model_id} className="border-t border-line/70">
                        <th scope="row" className="py-1.5 pr-3 font-medium text-fg">{m.label}</th>
                        <td className="py-1.5 pr-3 text-right text-fg tabular-nums">{source === "v1" ? value : value?.toFixed(1)}</td>
                        <td className="py-1.5">
                          <a href={s.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-secondary hover:underline">
                            {s.source}
                            <ExternalLink aria-hidden="true" className="h-3 w-3" />
                          </a>
                          {s.self_reported ? " · self-reported" : ""}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <ul className="flex list-disc flex-col gap-1 pl-4">
              {reference.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
            <p>Scores checked {reference.checked}.</p>
          </div>
        )}
      </div>
    </section>
  );
}
