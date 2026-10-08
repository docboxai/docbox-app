"use client";

import { useRef, type CSSProperties, type ReactNode } from "react";
import { ArrowUp, EllipsisVertical } from "lucide-react";
import {
  BATCH_FOLDER_BACK,
  BATCH_FOLDER_FRONT,
  BATCH_FOLDER_FRONT_PATH,
  GLASS_FRONT,
  GLASS_FRONT_PATH,
  KEEP_LAYER_FRONT,
  KEEP_LAYER_FRONT_PATH,
  KEEP_LAYER_MID,
  KEEP_LAYER_MID_PATH,
} from "@/lib/shapes";
import { useScrollProgress } from "@/lib/useScrollProgress";
import { ShaderCanvas } from "./shader/ShaderCanvas";
import glassHighlights from "./shader/glsl/glassHighlights";
import glow from "./shader/glsl/glow";
import rays from "./shader/glsl/rays";
import sheen from "./shader/glsl/sheen";

const EASE = "ease-[cubic-bezier(0.2,0,0,1)]";

/** An absolutely placed, rotated element at its design position (rotation about its top-left). */
function place(left: number, top: number, rotate = 0, z = 0): CSSProperties {
  return { left, top, rotate: `${rotate}deg`, transformOrigin: "top left", zIndex: z };
}

// --- 01 Route: the glass folder with score widgets floating out of it ----------------

/** A widget card that drifts by `depth` px across a scroll through the scene. */
function Widget({
  className,
  style,
  depth,
  children,
}: {
  className: string;
  style: CSSProperties;
  depth: number;
  children: ReactNode;
}) {
  return (
    <div
      className={`absolute flex flex-col justify-between gap-1 rounded-xl p-2.5 shadow-[0_10px_20px_#05030f80] ${className}`}
      style={{ ...style, translate: `0 calc((var(--progress, 0.5) - 0.5) * ${depth}px)` }}
    >
      {children}
    </div>
  );
}

const GAUGE_TRACK =
  "M23 0 C35.703 0 46 10.297 46 23 C46 35.703 35.703 46 23 46 C10.297 46 0 35.703 0 23 C0 10.297 10.297 0 23 0 Z M23 5.06 C13.092 5.06 5.06 13.092 5.06 23 C5.06 32.908 13.092 40.94 23 40.94 C32.908 40.94 40.94 32.908 40.94 23 C40.94 13.092 32.908 5.06 23 5.06 Z";
const GAUGE_ARC =
  "M23 0 C35.703 0 46 10.297 46 23 C46 35.703 35.703 46 23 46 C10.297 46 0 35.703 0 23 C0 14.783 4.384 7.19 11.5 3.081 L14.03 7.464 C8.479 10.668 5.06 16.591 5.06 23 C5.06 32.908 13.092 40.94 23 40.94 C32.908 40.94 40.94 32.908 40.94 23 C40.94 13.092 32.908 5.06 23 5.06 L23 0 Z";

function GlassFolder() {
  return (
    <div className="absolute h-[170px] w-[320px]" style={place(158, 232, 0, 8)}>
      <svg aria-hidden="true" viewBox="0 0 320 170" className="absolute inset-0 size-full overflow-visible">
        <defs>
          <filter id="glass-shadow" x="-30%" y="-30%" width="160%" height="190%">
            <feGaussianBlur stdDeviation="20" />
          </filter>
          {/* The shadow falls around the glass, not inside it, so the frost stays clear. */}
          <mask id="glass-shadow-mask" maskUnits="userSpaceOnUse" x="-80" y="-80" width="480" height="350">
            <rect x="-80" y="-80" width="480" height="350" fill="#fff" />
            <path d={GLASS_FRONT_PATH} fill="#000" />
          </mask>
        </defs>
        <g mask="url(#glass-shadow-mask)">
          <path d={GLASS_FRONT_PATH} transform="translate(0 20)" fill="#05030f" opacity="0.5" filter="url(#glass-shadow)" />
        </g>
      </svg>
      {/* Frost: glass.glsl's blur and tint of what's behind (u_blur 9, u_tint #C9C4FF at 0.34). */}
      <div
        className="absolute inset-0 bg-[#c9c4ff]/[0.34] backdrop-blur-[9px]"
        style={{ clipPath: `path("${GLASS_FRONT_PATH}")` }}
      />
      <ShaderCanvas
        source={glassHighlights}
        sdf={GLASS_FRONT}
        uniforms={{ u_tint: "#C9C4FF" }}
        className="absolute inset-0 size-full mix-blend-plus-lighter"
      />
      <svg aria-hidden="true" viewBox="0 0 320 170" className="absolute inset-0 size-full">
        <defs>
          <linearGradient id="glass-rim" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#fff" stopOpacity="0.7" />
            <stop offset="1" stopColor="#fff" stopOpacity="0.1" />
          </linearGradient>
          <clipPath id="glass-clip">
            <path d={GLASS_FRONT_PATH} />
          </clipPath>
        </defs>
        <path d={GLASS_FRONT_PATH} fill="none" stroke="url(#glass-rim)" strokeWidth="3" clipPath="url(#glass-clip)" />
      </svg>
    </div>
  );
}

export function RouteScene() {
  const ref = useRef<HTMLDivElement>(null);
  useScrollProgress(ref);
  return (
    <div ref={ref} aria-hidden="true" className="relative h-[400px] w-full lg:h-[420px]">
      <div className="absolute top-0 left-1/2 h-[420px] w-[636px] -translate-x-1/2 max-[400px]:origin-top max-[400px]:scale-[0.86]">
        <ShaderCanvas
          source={glow}
          uniforms={{ u_color: "#7F76FF", u_strength: 0.7 }}
          maxPixelRatio={1}
          className="absolute size-[500px] rounded-full"
          style={place(68, 20)}
          fallback={
            <div
              className="absolute size-[500px] rounded-full bg-[radial-gradient(circle,#7f76ff66_0%,transparent_60%)]"
              style={place(68, 20)}
            />
          }
        />
        <div
          className="absolute h-[176px] w-[276px] rounded-3xl border border-white/25 bg-[linear-gradient(180deg,#7f76ff_0%,#2806ac_100%)]"
          style={place(186, 214, 3, 1)}
        />
        <ShaderCanvas source={rays} className="absolute h-[270px] w-[260px]" style={place(190, 10, 0, 2)} />

        <Widget className="h-[84px] w-[84px] bg-panel" style={place(196, 58, 8, 3)} depth={36}>
          <span className="text-[9px] text-muted">Mobile</span>
          <span className="relative mx-auto size-[46px]">
            <svg viewBox="0 0 46 46" className="absolute inset-0 size-full">
              <path d={GAUGE_TRACK} fill="#ffffff1f" />
              <path d={GAUGE_ARC} fill="#ffd15c" />
            </svg>
            <span className="absolute inset-0 grid place-items-center font-heading text-[13px] font-bold">97</span>
          </span>
        </Widget>
        <Widget className="h-[70px] w-[92px] bg-sun text-[#3a2a00]" style={place(372, 52, -10, 4)} depth={52}>
          <span className="text-[9px] font-semibold">Seconds / page</span>
          <span className="font-heading text-[22px] leading-none font-bold">0.4</span>
          <span className="h-1 w-full rounded-full bg-[#3a2a00]/20">
            <span className="block h-1 w-5 rounded-full bg-[#3a2a00]" />
          </span>
        </Widget>
        <Widget className="h-[82px] w-32 bg-white" style={place(262, 138, -3, 5)} depth={24}>
          <span className="text-[9px] font-semibold text-[#5e5a75]">PaddleOCR-VL</span>
          <span className="flex items-center gap-1 text-ink">
            <ArrowUp className="size-5" />
            <span className="font-heading text-[26px] leading-none font-bold">99.1%</span>
          </span>
          <span className="text-[9px] font-semibold text-tolopea-600">Best read</span>
        </Widget>
        <Widget className="h-14 w-[70px] bg-tolopea-500" style={place(206, 196, 10, 6)} depth={-28}>
          <span className="font-heading text-xl leading-none font-bold">4</span>
          <span className="text-[9px] text-tolopea-100">models</span>
        </Widget>
        <Widget className="h-[58px] w-[74px] bg-ember" style={place(388, 180, -9, 7)} depth={-44}>
          <span className="font-heading text-xl leading-none font-bold">2</span>
          <span className="text-[9px] text-[#ffe9df]">slips found</span>
        </Widget>

        <GlassFolder />
        <span className="absolute text-[11px] font-medium text-white/80" style={place(418, 374, 0, 9)}>
          Reads
        </span>
      </div>
    </div>
  );
}

// --- Shared bits for the two smaller folder scenes ------------------------------------

/** A sheet of paper with grey text lines; the first line is the heading. */
function Sheet({
  lines,
  color,
  padding,
  gap,
  className,
  style,
}: {
  lines: number[];
  color: string;
  padding: number;
  gap: number;
  className: string;
  style: CSSProperties;
}) {
  return (
    <div
      className={`absolute flex flex-col rounded-lg bg-[linear-gradient(180deg,#ffffff_0%,#eceaff_100%)] shadow-[0_6px_14px_#05030f59] transition-[translate] duration-400 ${EASE} ${className}`}
      style={{ ...style, padding, gap }}
    >
      {lines.map((w, i) => (
        <span
          key={i}
          className="block shrink-0 rounded-full"
          style={{ width: w, height: i === 0 ? 6 : 4, backgroundColor: i === 0 ? color : `${color}66` }}
        />
      ))}
    </div>
  );
}

/** A folder layer drawn by sheen.glsl, with a flat gradient where WebGL isn't available. */
function SheenLayer({
  path,
  viewBox,
  sdf,
  top,
  bottom,
  alpha = 1,
  extra,
  className,
  style,
}: {
  path: string;
  viewBox: string;
  sdf: typeof KEEP_LAYER_MID;
  top: string;
  bottom: string;
  alpha?: number;
  extra?: Record<string, number>;
  className: string;
  style?: CSSProperties;
}) {
  const id = `sheen-${top.slice(1)}-${bottom.slice(1)}`;
  return (
    <ShaderCanvas
      source={sheen}
      sdf={sdf}
      uniforms={{ u_top: top, u_bottom: bottom, u_alpha: alpha, ...extra }}
      className={className}
      style={style}
      fallback={
        <svg aria-hidden="true" viewBox={viewBox} preserveAspectRatio="none" className={className} style={style}>
          <defs>
            <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor={top} />
              <stop offset="1" stopColor={bottom} />
            </linearGradient>
          </defs>
          <path d={path} fill={`url(#${id})`} opacity={alpha} />
        </svg>
      }
    />
  );
}

// --- 02 Batch: a named folder with its pages ------------------------------------------

export function BatchScene() {
  return (
    <div aria-hidden="true" className="relative h-[206px] w-[210px] shrink-0">
      <svg viewBox="0 0 240 230" preserveAspectRatio="none" className="absolute inset-0 size-full">
        <defs>
          <linearGradient id="batch-back" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#c3b5ff" />
            <stop offset="1" stopColor="#8f6bff" />
          </linearGradient>
        </defs>
        <path d={BATCH_FOLDER_BACK} fill="url(#batch-back)" />
      </svg>
      <Sheet
        lines={[32, 64, 51, 64, 38]}
        color="#C59BFF"
        padding={10.08}
        gap={5.88}
        className="h-24 w-[84px] group-hover:-translate-y-2.5"
        style={place(20, 50, -5, 1)}
      />
      <Sheet
        lines={[36, 73, 58, 73, 44]}
        color="#C59BFF"
        padding={11.52}
        gap={6.72}
        className="h-[90px] w-24 delay-75 group-hover:-translate-y-3.5"
        style={place(96, 50, 3, 2)}
      />
      <div className="absolute top-[102px] left-0 z-[3] h-[104px] w-[210px] rounded-[4px_4px_22px_22px] backdrop-blur-[4px]" />
      <SheenLayer
        path={BATCH_FOLDER_FRONT_PATH}
        viewBox="0 0 210 104"
        sdf={BATCH_FOLDER_FRONT}
        top="#7A63FF"
        bottom="#4318FF"
        alpha={0.95}
        className="absolute top-[102px] left-0 z-[3] h-[104px] w-[210px]"
      />
      <span className="absolute top-[116px] left-4 z-[4] font-heading text-lg font-semibold">Invoices</span>
      <span className="absolute top-[141px] left-4 z-[5] text-[11px] text-tolopea-200">56 pages</span>
      <EllipsisVertical className="absolute top-[117px] left-[182px] z-[6] size-4" />
    </div>
  );
}

// --- 03 Keep: everything in one local library -----------------------------------------

function MiniCard({ className, style, value, label }: { className: string; style: CSSProperties; value: string; label: string }) {
  return (
    <div
      className={`absolute flex w-[62px] flex-col gap-px rounded-lg px-2 py-1.5 shadow-[0_6px_12px_#05030f66] transition-[translate] duration-400 ${EASE} group-hover:-translate-y-1.5 ${className}`}
      style={style}
    >
      <span className="font-heading text-[15px] leading-tight font-bold">{value}</span>
      <span className="text-[8px] opacity-70">{label}</span>
    </div>
  );
}

export function KeepScene() {
  return (
    <div
      aria-hidden="true"
      className="relative size-[206px] shrink-0 overflow-hidden rounded-[28px] bg-[linear-gradient(180deg,#4a2be8_0%,#2806ac_100%)]"
    >
      <Sheet
        lines={[27, 55, 44, 55, 33]}
        color="#A9A7FF"
        padding={8.64}
        gap={5.04}
        className="h-[84px] w-[72px] group-hover:-translate-y-3"
        style={place(34, 24, 7, 0)}
      />
      <Sheet
        lines={[38, 76, 61, 76, 46]}
        color="#A9A7FF"
        padding={12}
        gap={7}
        className="h-[74px] w-[100px] delay-75 group-hover:-translate-y-2"
        style={place(82, 16, -4, 1)}
      />
      <SheenLayer
        path={KEEP_LAYER_MID_PATH}
        viewBox="0 0 240 240"
        sdf={KEEP_LAYER_MID}
        top="#9A92FF"
        bottom="#563FFF"
        extra={{ u_offset: 0.4 }}
        className="absolute inset-0 z-[2] size-full"
      />
      <MiniCard className="bg-white text-ink" style={place(62, 108, -8, 3)} value="99.1%" label="best read" />
      <MiniCard className="bg-panel text-white" style={place(118, 112, 7, 4)} value="3.1 s" label="per page" />
      <SheenLayer
        path={KEEP_LAYER_FRONT_PATH}
        viewBox="0 0 240 240"
        sdf={KEEP_LAYER_FRONT}
        top="#FFFFFF"
        bottom="#CECEFF"
        extra={{ u_offset: 0.7, u_sheen: 0.6 }}
        className="absolute inset-0 z-[5] size-full"
      />
      <span className="absolute top-[152px] left-[18px] z-[6] text-[13px] leading-4 font-semibold text-tolopea-600">
        Everything
        <br />
        stays here
      </span>
    </div>
  );
}
