// What the benchmark graph and the ranked bars share: a colour per engine, how a model's
// sizes group into one family, and the number formats.
import { formatMb } from "./format";

export type SeriesKey = "paddle" | "tesseract" | "ollama" | "other";

// Three hues at most. On the graph any two marks can sit side by side, and only three of
// the palette's hues stay distinct for colour-blind readers in every pairing (validated
// all-pairs on the surface); every other engine shares the neutral, and labels name every
// line. Colour follows the engine, never the rank, so filtering never repaints a model.
export const SERIES: Record<SeriesKey, { label: string; color: string }> = {
  paddle: { label: "PaddleOCR", color: "var(--color-series-1)" },
  tesseract: { label: "Tesseract", color: "var(--color-series-2)" },
  ollama: { label: "Ollama", color: "var(--color-series-3)" },
  other: { label: "Other engines", color: "var(--color-series-other)" },
};

export const SERIES_ORDER: SeriesKey[] = ["paddle", "tesseract", "ollama", "other"];

export function seriesOf(engine: string): SeriesKey {
  if (engine === "paddleocr" || engine === "paddleocr-vl") return "paddle";
  if (engine === "tesseract" || engine === "ollama") return engine;
  return "other";
}

// Short names for labels ("PaddleOCR Balanced — Chinese + English" -> "PaddleOCR
// Balanced"); tooltips keep the full name.
const ENGINE_NAMES = new Set(["PaddleOCR", "Tesseract", "EasyOCR", "Ollama", "NVIDIA NIM"]);
export function shortName(name: string): string {
  const [head, tail] = name.split(" — ");
  if (!tail) return name;
  return ENGINE_NAMES.has(head) ? `${head} ${tail}` : head;
}

/** A model's family label ("PaddleOCR English" for every size of it), or its own name. */
export function familyLabel(family: string | null, name: string): string {
  return family ? family.replace(" — ", " ") : shortName(name);
}

/** One entry per family: the variant with the highest `score` (the first, on a tie). */
export function bestPerFamily<T>(items: T[], family: (t: T) => string, score: (t: T) => number | null): T[] {
  const best = new Map<string, T>();
  for (const item of items) {
    const key = family(item);
    const held = best.get(key);
    if (held === undefined || (score(item) ?? -Infinity) > (score(held) ?? -Infinity)) best.set(key, item);
  }
  return items.filter((item) => best.get(family(item)) === item);
}

export const pct = (v: number | null | undefined, digits = 1) => (v == null ? "–" : `${(v * 100).toFixed(digits)}%`);
export const secs = (v: number | null | undefined, digits?: number) =>
  v == null ? "–" : `${v.toFixed(digits ?? (v >= 10 ? 1 : 2))} s`;
export const mb = (v: number | null | undefined) => (v == null ? "–" : formatMb(v));

/** "±2.1" in percentage points; whole points once it's 10 or more. */
export function plusMinus(margin: number | null | undefined): string | null {
  if (margin == null) return null;
  const points = margin * 100;
  return `±${points < 10 ? points.toFixed(1) : Math.round(points)}`;
}
