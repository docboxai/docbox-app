// The DocBox mark (a gold two-compartment box on a near-black tile); same geometry as
// src-tauri/icons/logo.svg, the app-icon source.
export function Logo({ size = 32 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 512 512" aria-hidden="true" className="shrink-0">
      <rect x="40" y="40" width="432" height="432" rx="96" fill="#0F0F0F" />
      <rect x="171" y="129" width="170" height="254" rx="12" fill="none" stroke="#C9A24D" strokeWidth="15" />
      <line x1="171" y1="256" x2="341" y2="256" stroke="#C9A24D" strokeWidth="14" />
    </svg>
  );
}
