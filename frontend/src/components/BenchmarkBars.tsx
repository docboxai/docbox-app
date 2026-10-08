// The ranked bars: every model's score as a bar with its 95% interval, beside what it
// costs. It is also the graph's table view: every value the graph plots is written here,
// and the rest (word error rate, confidence, failed pages) is in each row's tooltip.
import { useState, type ReactNode } from "react";
import { ScanText } from "lucide-react";
import { ENGINE_ICONS } from "../lib/engineMeta";
import { SERIES, type SeriesKey } from "../lib/benchmarkSeries";
import { cx } from "./ui";

export interface BarRow {
  id: string;
  /** In full: heads the tooltip. */
  name: string;
  /** Short: the family's name, or the model's own. */
  label: string;
  variant: string | null;
  /** For its icon. */
  engine: string;
  series: SeriesKey;
  /** The bar, as a fraction of the axis; null draws none. */
  value: number | null;
  /** Ends of the 95% interval, as fractions of the axis. */
  low?: number | null;
  high?: number | null;
  /** The score as written in its column. */
  display: ReactNode;
  /** The other columns, in `headers` order. */
  cells: ReactNode[];
  /** Tooltip rows: [label, value]. */
  details: [string, string][];
  /** A short line under the name, e.g. failed pages. */
  note?: ReactNode;
  action?: ReactNode;
}

const TICKS = [0, 0.25, 0.5, 0.75, 1];

function Bar({ row, active }: { row: BarRow; active: boolean }) {
  const color = SERIES[row.series].color;
  const clamp = (v: number) => Math.min(1, Math.max(0, v));
  return (
    <div className="relative h-2.5 w-full">
      <div className="absolute inset-0 rounded-[4px] bg-line/45" />
      {row.value != null && (
        <div
          className="absolute inset-y-0 left-0 rounded-r-[4px] transition-[filter]"
          style={{ width: `${clamp(row.value) * 100}%`, background: color, filter: active ? "brightness(1.15)" : undefined }}
        />
      )}
      {row.low != null && row.high != null && (
        <div
          aria-hidden="true"
          className="absolute top-1/2 h-[9px] -translate-y-1/2 border-x-[1.5px] border-fg/80"
          style={{ left: `${clamp(row.low) * 100}%`, width: `${Math.max(0, clamp(row.high) - clamp(row.low)) * 100}%` }}
        >
          <div className="absolute top-1/2 right-0 left-0 h-[1.5px] -translate-y-1/2 bg-fg/80" />
        </div>
      )}
    </div>
  );
}

export function BenchmarkBars({
  rows,
  caption,
  valueHeader,
  headers,
  tickFormat,
  actions,
}: {
  rows: BarRow[];
  caption: string;
  valueHeader: string;
  headers: string[];
  /** Axis labels under the bars (fractions of the axis). */
  tickFormat: (fraction: number) => string;
  /** Leave room for each row's action (e.g. "Set as default"). */
  actions?: boolean;
}) {
  const [active, setActive] = useState<string | null>(null);
  const activeRow = rows.find((r) => r.id === active);

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[760px] border-collapse text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="text-[11px] font-medium tracking-[0.4px] text-fg-muted uppercase">
            <th scope="col" className="w-[30%] min-w-[180px] py-2 pr-3 text-left font-medium">Model</th>
            <th scope="col" className="py-2 pr-4">
              <span className="sr-only">{valueHeader} as a bar</span>
            </th>
            <th scope="col" className="py-2 pr-3 text-right font-medium whitespace-nowrap">{valueHeader}</th>
            {headers.map((h) => (
              <th key={h} scope="col" className="py-2 pr-3 text-right font-medium whitespace-nowrap">{h}</th>
            ))}
            {actions && (
              <th scope="col" className="py-2">
                <span className="sr-only">Actions</span>
              </th>
            )}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const Icon = ENGINE_ICONS[r.engine] ?? ScanText;
            return (
              <tr
                key={r.id}
                className={cx("border-t border-line/70 transition-colors", active === r.id && "bg-line/25")}
                onMouseEnter={() => setActive(r.id)}
                onMouseLeave={() => setActive((a) => (a === r.id ? null : a))}
              >
                <th scope="row" className="py-2.5 pr-3 text-left font-normal">
                  <span className="flex min-w-0 items-start gap-2">
                    <Icon aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-fg-muted" />
                    {/* Wraps rather than truncating: a cut-off name could hide which size it is. */}
                    <span className="min-w-0" title={r.name}>
                      <span className="font-medium text-fg">{r.label}</span>
                      {r.variant && <span className="ml-1.5 whitespace-nowrap text-fg-muted">[{r.variant.toLowerCase()}]</span>}
                    </span>
                  </span>
                  {r.note && <span className="mt-0.5 block pl-6 text-xs">{r.note}</span>}
                </th>
                <td className="relative w-[34%] min-w-[160px] py-2.5 pr-4">
                  <div
                    tabIndex={0}
                    aria-label={`${r.name}: ${r.details.map(([k, v]) => `${k} ${v}`).join(", ")}`}
                    onFocus={() => setActive(r.id)}
                    onBlur={() => setActive((a) => (a === r.id ? null : a))}
                    className="rounded-sm py-1.5 outline-none focus-visible:ring-2 focus-visible:ring-secondary"
                  >
                    <Bar row={r} active={active === r.id} />
                  </div>
                  {activeRow?.id === r.id && (
                    <div
                      role="tooltip"
                      className="pointer-events-none absolute top-full left-0 z-10 mt-1 w-64 rounded-xl bg-ink px-3 py-2.5 text-[13px] shadow-[0_8px_24px_#00000066] ring-1 ring-line"
                    >
                      <p className="flex items-center gap-2 pb-1.5 font-medium text-fg">
                        <svg aria-hidden="true" width="14" height="4" className="shrink-0">
                          <line x1="0" x2="14" y1="2" y2="2" stroke={SERIES[r.series].color} strokeWidth="2.5" strokeLinecap="round" />
                        </svg>
                        {r.name}
                      </p>
                      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
                        {r.details.map(([k, v]) => (
                          <div key={k} className="contents">
                            <dt className="text-fg-muted">{k}</dt>
                            <dd className="text-right font-medium text-fg tabular-nums">{v}</dd>
                          </div>
                        ))}
                      </dl>
                    </div>
                  )}
                </td>
                <td className="py-2.5 pr-3 text-right whitespace-nowrap tabular-nums">{r.display}</td>
                {r.cells.map((c, i) => (
                  <td key={headers[i]} className="py-2.5 pr-3 text-right whitespace-nowrap text-fg-muted tabular-nums">
                    {c}
                  </td>
                ))}
                {actions && <td className="py-2 text-right">{r.action}</td>}
              </tr>
            );
          })}
        </tbody>
        <tfoot>
          <tr>
            <td />
            <td className="pt-1 pr-4">
              <div aria-hidden="true" className="relative h-4 text-[11px] text-fg-muted tabular-nums">
                {TICKS.map((t) => (
                  <span key={t} className="absolute -translate-x-1/2 first:translate-x-0 last:-translate-x-full" style={{ left: `${t * 100}%` }}>
                    {tickFormat(t)}
                  </span>
                ))}
              </div>
            </td>
            <td colSpan={1 + headers.length + (actions ? 1 : 0)} />
          </tr>
        </tfoot>
      </table>
    </div>
  );
}
