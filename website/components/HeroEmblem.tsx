"use client";

import { useEffect, useRef } from "react";
import { EMBLEM, EMBLEM_SIZE, LOGO_BODY, LOGO_CORNER } from "@/lib/shapes";
import { useReducedMotion } from "@/lib/useReducedMotion";
import { ShaderCanvas } from "./shader/ShaderCanvas";
import ascii from "./shader/glsl/ascii";

// Most a pointer can tilt the emblem, in degrees, and how much slower than the page it
// moves as you scroll away from the hero. The lag only applies side by side with the
// copy (lg); stacked above it on narrow screens, drifting down would cover the text.
const MAX_TILT = 8;
const SCROLL_LAG = 0.12;
const SIDE_BY_SIDE = "(min-width: 1024px)";

export function HeroEmblem() {
  const driftRef = useRef<HTMLDivElement>(null);
  const tiltRef = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();

  // Two layers: the scroll drift follows the page exactly (no transition), while the
  // pointer tilt eases toward the cursor (a transition, so it retargets mid-move).
  useEffect(() => {
    const drift = driftRef.current;
    const tilt = tiltRef.current;
    if (!drift || !tilt || reduced) return;
    let frame = 0;
    let rx = 0;
    let ry = 0;
    let y = 0;
    const apply = () => {
      frame = 0;
      drift.style.transform = `translate3d(0, ${y.toFixed(1)}px, 0)`;
      tilt.style.transform = `perspective(900px) rotateX(${rx.toFixed(2)}deg) rotateY(${ry.toFixed(2)}deg)`;
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(apply);
    };
    const wide = window.matchMedia(SIDE_BY_SIDE);
    const onScroll = () => {
      y = wide.matches ? Math.min(window.scrollY, window.innerHeight) * SCROLL_LAG : 0;
      schedule();
    };
    const clamp = (v: number) => Math.max(-MAX_TILT, Math.min(MAX_TILT, v));
    const onPointer = (event: PointerEvent) => {
      if (event.pointerType !== "mouse" || window.scrollY > window.innerHeight) return;
      const r = tilt.getBoundingClientRect();
      ry = clamp(((event.clientX - (r.left + r.width / 2)) / window.innerWidth) * 2 * MAX_TILT);
      rx = clamp(-((event.clientY - (r.top + r.height / 2)) / window.innerHeight) * 2 * MAX_TILT);
      schedule();
    };
    const onLeave = () => {
      rx = 0;
      ry = 0;
      schedule();
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    wide.addEventListener("change", onScroll);
    window.addEventListener("pointermove", onPointer, { passive: true });
    document.documentElement.addEventListener("pointerleave", onLeave);
    onScroll();
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("scroll", onScroll);
      wide.removeEventListener("change", onScroll);
      window.removeEventListener("pointermove", onPointer);
      document.documentElement.removeEventListener("pointerleave", onLeave);
      drift.style.transform = "";
      tilt.style.transform = "";
    };
  }, [reduced]);

  return (
    <div ref={driftRef} className="will-change-transform">
      <div
        ref={tiltRef}
        className="relative aspect-[330/346] w-[190px] shrink-0 transition-transform duration-500 ease-[cubic-bezier(0.2,0,0,1)] sm:w-[240px] lg:w-[330px]"
      >
        <ShaderCanvas
          source={ascii}
          sdf={EMBLEM}
          sdfSize={EMBLEM_SIZE}
          className="absolute inset-0 size-full"
          fallback={
            <svg aria-hidden="true" viewBox="0 0 330 346" className="absolute inset-0 size-full opacity-40">
              <svg x="0" y="0" width="321.195" height="342.7" viewBox="0 0 279.3 298" preserveAspectRatio="none">
                <path d={LOGO_BODY} fill="#D6D2FF" />
              </svg>
              <svg x="214.065" y="0.46" width="93.33" height="94.019" viewBox="0 0 81.157 81.756" preserveAspectRatio="none">
                <path d={LOGO_CORNER} fill="#D6D2FF" />
              </svg>
            </svg>
          }
        />
      </div>
    </div>
  );
}
