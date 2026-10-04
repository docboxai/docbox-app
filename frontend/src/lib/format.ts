// Sizes as the design writes them: "16 GB", "1.2 TB", "386 MB".
export function formatGb(gb: number): string {
  if (gb >= 1000) return `${(gb / 1024).toFixed(1)} TB`;
  if (gb >= 10) return `${Math.round(gb)} GB`;
  return `${gb.toFixed(1)} GB`;
}

export function formatMb(mb: number): string {
  return mb >= 1000 ? `${(mb / 1024).toFixed(1)} GB` : `${Math.round(mb)} MB`;
}

export function formatSeconds(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  const m = Math.floor(seconds / 60);
  return `${m} min ${Math.round(seconds - m * 60)} s`;
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

// "NVIDIA GeForce GTX 1660 Ti" -> "GTX 1660 Ti", for narrow cards.
export function shortGpu(name: string): string {
  return name.replace(/^(NVIDIA|AMD|Intel\(R\)|Intel)\s+/i, "").replace(/^(GeForce|Radeon)\s+/i, "");
}
