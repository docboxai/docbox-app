"use client";

import { useEffect, type RefObject } from "react";
import { useReducedMotion } from "./useReducedMotion";

/** How far an element has travelled through the viewport: 0 as its top enters at the
 * bottom, 1 as its bottom leaves at the top. */
export function scrollProgress(el: Element): number {
  const rect = el.getBoundingClientRect();
  const vh = window.innerHeight;
  return Math.min(1, Math.max(0, (vh - rect.top) / (vh + rect.height)));
}

/** Keeps the element's `--progress` CSS variable at its scrollProgress. Lenis scrolls the
 * window itself, so the native scroll event fires with or without it. Left at the
 * stylesheet's default when the visitor prefers reduced motion. */
export function useScrollProgress(ref: RefObject<HTMLElement | null>) {
  const reduced = useReducedMotion();
  useEffect(() => {
    const el = ref.current;
    if (!el || reduced) return;
    let frame = 0;
    const update = () => {
      frame = 0;
      el.style.setProperty("--progress", scrollProgress(el).toFixed(4));
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(update);
    };
    update();
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      el.style.removeProperty("--progress");
    };
  }, [ref, reduced]);
}
