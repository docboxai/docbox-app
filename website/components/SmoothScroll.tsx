"use client";

import { ReactLenis } from "lenis/react";
import "lenis/dist/lenis.css";
import { useReducedMotion } from "@/lib/useReducedMotion";

// Lenis smooths the page's own scrolling (root), and `anchors` lets in-page links such as
// "See the models" glide to their section. Visitors who ask for reduced motion keep the
// browser's native scrolling.
export function SmoothScroll() {
  const reduced = useReducedMotion();
  if (reduced) return null;
  return <ReactLenis root options={{ anchors: true, lerp: 0.1 }} />;
}
