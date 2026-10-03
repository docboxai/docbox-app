// Small decorative pieces from the poster style. All aria-hidden: pure ornament.

const CHEVRON = "M0 0 H9 L22 14 L9 28 H0 L13 14 Z";

export function Chevrons({ colors, size = 22 }: { colors: string[]; size?: number }) {
  return (
    <div aria-hidden="true" className="flex gap-0.5">
      {colors.map((fill, i) => (
        <svg key={i} width={size} height={(size * 28) / 22} viewBox="0 0 22 28">
          <path d={CHEVRON} fill={fill} />
        </svg>
      ))}
    </div>
  );
}

export function CaptionBand({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-4 bg-ink px-8 py-3 font-mono text-xs font-bold tracking-wider text-white">
      {children}
    </div>
  );
}
