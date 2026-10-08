import type { CSSProperties } from "react";

/** Props that fade an element in as it scrolls into view (RevealObserver), after `delay` ms
 * so a group of elements arrives in sequence. */
export function reveal(delay = 0): { "data-reveal": ""; style: CSSProperties } {
  return { "data-reveal": "", style: { "--reveal-delay": `${delay}ms` } as CSSProperties };
}

/** Props for the hero's entrance on page load: the same fade and rise as `reveal`, but a
 * CSS animation that needs no JavaScript, so above-the-fold content never waits on it. */
export function enter(delay = 0): { "data-enter": ""; style: CSSProperties } {
  return { "data-enter": "", style: { "--reveal-delay": `${delay}ms` } as CSSProperties };
}
