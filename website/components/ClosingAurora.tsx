"use client";

import { useCallback, useRef } from "react";
import { scrollProgress } from "@/lib/useScrollProgress";
import { useReducedMotion } from "@/lib/useReducedMotion";
import { ShaderCanvas } from "./shader/ShaderCanvas";
import aurora from "./shader/glsl/aurora";

// The design sets aurora.glsl's "Scroll progress" to 0.3. Here it follows the page: 0.3
// with the panel centred in the window, ±0.3 as it scrolls in and out.
const AT_CENTRE = 0.3;
const RANGE = 0.6;

const UNIFORMS = {
  u_base: "#0A0626",
  u_colA: "#4318FF",
  u_colB: "#A9A7FF",
  u_intensity: 1.4,
  u_grid: 0.6,
};

export function ClosingAurora() {
  const ref = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();
  const live = useCallback(() => {
    const p = ref.current && !reduced ? scrollProgress(ref.current) : 0.5;
    return { u_scroll: Math.min(1, Math.max(0, AT_CENTRE + (p - 0.5) * RANGE)) };
  }, [reduced]);

  return (
    <div ref={ref} aria-hidden="true" className="absolute inset-0">
      <ShaderCanvas
        source={aurora}
        uniforms={UNIFORMS}
        live={live}
        maxPixelRatio={1.25}
        className="absolute inset-0 size-full"
        fallback={
          <div className="absolute inset-0 bg-[radial-gradient(60%_80%_at_15%_30%,#4318ff55,transparent),radial-gradient(50%_70%_at_90%_80%,#a9a7ff33,transparent),#0a0626]" />
        }
      />
    </div>
  );
}
