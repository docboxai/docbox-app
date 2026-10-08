// The benchmark graph: how well each model reads (up) against what it costs, cheapest on
// the right, so the most efficient models sit in the top-right corner. One model's sizes
// (PaddleOCR Mobile and Large, an Ollama model's tags) are joined by a line in their
// engine's colour and labelled once, at the best of them.
import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { SERIES, type SeriesKey } from "../lib/benchmarkSeries";

export interface ChartPoint {
  id: string;
  /** In full; heads the tooltip. */
  name: string;
  /** Points of one family are joined by a line. */
  family: string;
  /** The family's direct label. */
  label: string;
  /** Which size of the family this point is. */
  variant: string | null;
  series: SeriesKey;
  x: number;
  y: number;
  /** Drawn as a ring: e.g. a published score for a model that isn't installed here. */
  hollow?: boolean;
  /** Tooltip rows: [label, value]. */
  rows: [string, string][];
}

const HEIGHT = 420;
const M = { top: 52, right: 28, bottom: 54, left: 54 };
// Average glyph widths, to place labels before they render (12px semibold, 10px caps).
const LABEL_PX = 7.1;
const VARIANT_PX = 7.2;
const DOT_R = 4.5;

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

// --- labels ---------------------------------------------------------------------------

interface Box {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

interface Placed {
  point: ChartPoint;
  box: Box;
  /** Pushed away from its point: drawn with a hairline back to it. */
  leader: boolean;
}

// One label per family, at its best point. Spots are tried nearest first (above, right,
// left, below, then the diagonals, at growing distances), keeping clear of the plot's
// edges, every point and the labels already placed; with no clear spot, the one that
// overlaps least is used. A label away from its point is tied back by a leader line.
const RINGS = [11, 30, 52, 76];

function placeLabels(
  points: ChartPoint[],
  lines: ChartPoint[][],
  sx: (v: number) => number,
  sy: (v: number) => number,
  bounds: Box,
): Placed[] {
  const anchors = [...new Map(points.map((p) => [p.family, p])).keys()].map((family) => {
    const members = points.filter((p) => p.family === family);
    return members.reduce((a, b) => (b.y > a.y || (b.y === a.y && sx(b.x) > sx(a.x)) ? b : a));
  });
  const dots: Box[] = points.map((p) => ({ x1: sx(p.x) - 7, y1: sy(p.y) - 7, x2: sx(p.x) + 7, y2: sy(p.y) + 7 }));
  // The family lines too, as small boxes every 6px along them, so text doesn't sit on one.
  for (const members of lines) {
    for (let i = 1; i < members.length; i++) {
      const [ax, ay, bx, by] = [sx(members[i - 1].x), sy(members[i - 1].y), sx(members[i].x), sy(members[i].y)];
      const steps = Math.max(1, Math.ceil(Math.hypot(bx - ax, by - ay) / 6));
      for (let k = 0; k <= steps; k++) {
        const x = ax + ((bx - ax) * k) / steps;
        const y = ay + ((by - ay) * k) / steps;
        dots.push({ x1: x - 2, y1: y - 2, x2: x + 2, y2: y + 2 });
      }
    }
  }
  const placed: Placed[] = [];
  const area = (a: Box, b: Box) =>
    Math.max(0, Math.min(a.x2, b.x2) - Math.max(a.x1, b.x1)) * Math.max(0, Math.min(a.y2, b.y2) - Math.max(a.y1, b.y1));
  const clash = (b: Box) =>
    placed.reduce((sum, q) => sum + area(q.box, b), 0) + dots.reduce((sum, d) => sum + area(d, b), 0);

  for (const p of [...anchors].sort((a, b) => sy(a.y) - sy(b.y))) {
    const w = Math.max(p.label.length * LABEL_PX, (p.variant?.length ?? 0) * VARIANT_PX);
    const h = p.variant ? 27 : 15;
    const px = sx(p.x);
    const py = sy(p.y);
    const spots: { box: Box; near: boolean }[] = [];
    for (const d of RINGS) {
      const at = (x: number, y: number) => ({ box: { x1: x, y1: y, x2: x + w, y2: y + h }, near: d === RINGS[0] });
      spots.push(
        at(px - w / 2, py - d - h),
        at(px + d, py - h / 2),
        at(px - d - w, py - h / 2),
        at(px - w / 2, py + d),
        at(px + d * 0.7, py - d * 0.7 - h),
        at(px - d * 0.7 - w, py - d * 0.7 - h),
        at(px + d * 0.7, py + d * 0.7),
        at(px - d * 0.7 - w, py + d * 0.7),
      );
    }
    const inside = spots.filter(({ box: b }) => b.x1 >= bounds.x1 && b.x2 <= bounds.x2 && b.y1 >= bounds.y1 && b.y2 <= bounds.y2);
    const pick = inside.find((s) => clash(s.box) === 0) ?? [...inside].sort((a, b) => clash(a.box) - clash(b.box))[0] ?? spots[0];
    placed.push({ point: p, box: pick.box, leader: !pick.near });
  }
  return placed;
}

// --- the plot -------------------------------------------------------------------------

export function BenchmarkChart({
  points,
  title,
  xLabel,
  xFormat,
  yFormat,
  yCap,
  ariaLabel,
}: {
  points: ChartPoint[];
  /** What the height measures, written above the plot. */
  title: string;
  xLabel: string;
  xFormat: (v: number) => string;
  yFormat: (v: number) => string;
  /** Highest possible y (100 for a percentage). */
  yCap: number;
  ariaLabel: string;
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

  const plotW = width - M.left - M.right;
  const plotH = HEIGHT - M.top - M.bottom;
  const xDomain = logDomain(points.map((p) => p.x));
  const xTicks = logTicks(xDomain);
  const { domain: yDomain, ticks: yTicks } = linearDomain(points.map((p) => p.y), yCap);
  const logSpan = Math.log10(xDomain[1]) - Math.log10(xDomain[0]);
  // Reversed: the cheapest end of the axis is on the right.
  const sx = (v: number) => M.left + (1 - (Math.log10(v) - Math.log10(xDomain[0])) / logSpan) * plotW;
  const sy = (v: number) => M.top + (1 - (v - yDomain[0]) / (yDomain[1] - yDomain[0] || 1)) * plotH;

  const families = useMemo(() => {
    const byFamily = new Map<string, ChartPoint[]>();
    for (const p of points) byFamily.set(p.family, [...(byFamily.get(p.family) ?? []), p]);
    return [...byFamily.values()].map((members) => [...members].sort((a, b) => b.x - a.x));
  }, [points]);

  const labels = placeLabels(points, families.filter((m) => m.length > 1), sx, sy, {
    x1: M.left - 8,
    y1: M.top - 4,
    x2: width - 4,
    y2: HEIGHT - M.bottom - 2,
  });
  const activePoint = points.find((p) => p.id === active);
  const activeFamily = activePoint?.family ?? null;
  const dim = (family: string) => (activeFamily !== null && family !== activeFamily ? 0.28 : 1);

  return (
    <div ref={wrapRef} className="relative w-full">
      <svg width={width} height={HEIGHT} role="img" aria-label={ariaLabel} className="block">
        <text x={M.left - 6} y={24} fontSize={14} fontWeight={600} fill="var(--color-fg)">
          {title}
        </text>
        <text x={width - M.right} y={24} textAnchor="end" fontSize={12} fontStyle="italic" fill="var(--color-fg-muted)">
          most efficient ↗
        </text>

        {/* grid and axes: solid hairlines, one step off the surface */}
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
        <text x={M.left + plotW / 2} y={HEIGHT - 12} textAnchor="middle" fontSize={12} fill="var(--color-fg-muted)">
          {xLabel} · log scale, cheaper to the right
        </text>

        {/* one line per family, through its sizes */}
        {families
          .filter((members) => members.length > 1)
          .map((members) => (
            <polyline
              key={`line${members[0].family}`}
              points={members.map((p) => `${sx(p.x)},${sy(p.y)}`).join(" ")}
              fill="none"
              stroke={SERIES[members[0].series].color}
              strokeWidth={activeFamily === members[0].family ? 3 : 2}
              strokeLinejoin="round"
              strokeLinecap="round"
              opacity={dim(members[0].family)}
            />
          ))}

        {labels.map((l) => {
          if (!l.leader) return null;
          const px = sx(l.point.x);
          const py = sy(l.point.y);
          const ex = Math.min(Math.max(px, l.box.x1), l.box.x2);
          const ey = Math.min(Math.max(py, l.box.y1), l.box.y2);
          return (
            <line
              key={`lead${l.point.id}`}
              x1={px}
              y1={py}
              x2={ex}
              y2={ey}
              stroke={SERIES[l.point.series].color}
              strokeWidth={1}
              opacity={0.7 * dim(l.point.family)}
            />
          );
        })}

        {points.map((p) => {
          const color = SERIES[p.series].color;
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
              opacity={dim(p.family)}
              className="cursor-default outline-none [&:focus-visible>circle:last-child]:stroke-secondary"
            >
              {/* the hit target is bigger than the mark */}
              <circle cx={sx(p.x)} cy={sy(p.y)} r={12} fill="transparent" />
              <circle
                cx={sx(p.x)}
                cy={sy(p.y)}
                r={active === p.id ? DOT_R + 1.5 : DOT_R}
                fill={p.hollow ? "var(--color-surface)" : color}
                stroke={p.hollow ? color : "var(--color-surface)"}
                strokeWidth={2}
              />
            </g>
          );
        })}

        {labels.map(({ point: p, box }) => (
          <g key={`label${p.family}`} opacity={dim(p.family)} pointerEvents="none">
            <text x={box.x1} y={box.y1 + 11.5} fontSize={12} fontWeight={600} fill="var(--color-fg)" stroke="var(--color-surface)" strokeWidth={4} strokeLinejoin="round" paintOrder="stroke">
              {p.label}
            </text>
            {p.variant && (
              <text x={box.x1} y={box.y1 + 24} fontSize={10} letterSpacing={0.6} fill="var(--color-fg-muted)" stroke="var(--color-surface)" strokeWidth={4} strokeLinejoin="round" paintOrder="stroke">
                {p.variant.toUpperCase()}
              </text>
            )}
          </g>
        ))}
      </svg>

      {activePoint && (
        <div
          role="tooltip"
          className="pointer-events-none absolute z-10 w-64 rounded-xl bg-ink px-3 py-2.5 text-[13px] shadow-[0_8px_24px_#00000066] ring-1 ring-line"
          style={{
            left: Math.min(Math.max(8, sx(activePoint.x) + 16), width - 264),
            top: Math.min(Math.max(4, sy(activePoint.y) - 20), HEIGHT - 150),
          }}
        >
          <p className="flex items-center gap-2 pb-1.5 font-medium text-fg">
            <svg aria-hidden="true" width="14" height="4" className="shrink-0">
              <line x1="0" x2="14" y1="2" y2="2" stroke={SERIES[activePoint.series].color} strokeWidth="2.5" strokeLinecap="round" />
            </svg>
            {activePoint.name}
          </p>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
            {activePoint.rows.map(([k, v]) => (
              <div key={k} className="contents">
                <dt className="text-fg-muted">{k}</dt>
                <dd className="text-right font-medium text-fg tabular-nums">{v}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </div>
  );
}
