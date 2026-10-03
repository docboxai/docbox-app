// The DocBox mark (a blue two-shelf box on a white tile); same geometry as
// src-tauri/icons/logo.svg, the app-icon source.
export function Logo({ size = 32 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 512 512" aria-hidden="true" className="shrink-0">
      <rect x="44" y="44" width="424" height="424" rx="94" fill="#FFFFFF" stroke="#D6E3F5" strokeWidth="8" />
      <rect x="171" y="129" width="170" height="254" rx="12" fill="none" stroke="#2F7DE1" strokeWidth="15" />
      <line x1="171" y1="256" x2="341" y2="256" stroke="#2F7DE1" strokeWidth="14" />
    </svg>
  );
}
