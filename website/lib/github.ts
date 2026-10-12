// The repository's real star count for the "Star on GitHub" button, and the latest
// release's installers for the download button. The page is regenerated at most hourly
// (app/page.tsx), so these two calls stay well inside GitHub's unauthenticated rate limit.
const API = "https://api.github.com/repos/docboxai/docbox-app";
const DOWNLOADS = "https://github.com/docboxai/docbox-app/releases/download/";

export async function getStarCount(): Promise<number | null> {
  try {
    const res = await fetch(API, {
      headers: { Accept: "application/vnd.github+json" },
      next: { revalidate: 3600 },
    });
    if (!res.ok) return null;
    const { stargazers_count } = (await res.json()) as { stargazers_count?: unknown };
    return typeof stargazers_count === "number" ? stargazers_count : null;
  } catch {
    // Offline build or GitHub down: the button shows without a count.
    return null;
  }
}

/** Direct links to the installer for each system, where one file fits everyone on it.
 * Linux has none: an AppImage, a .deb and an .rpm, and a browser can't tell which suits. */
export interface Installers {
  windows?: string;
  macos?: string;
}

// The release workflow names installers DocBox-<version>-<os>-<arch>.<ext>.
const INSTALLER_NAMES: Record<keyof Installers, RegExp> = {
  windows: /^DocBox-[\d.]+-windows-x86-64\.exe$/,
  macos: /^DocBox-[\d.]+-macos-arm-64\.dmg$/,
};

export async function getInstallers(): Promise<Installers> {
  try {
    const res = await fetch(`${API}/releases/latest`, {
      headers: { Accept: "application/vnd.github+json" },
      next: { revalidate: 3600 },
    });
    if (!res.ok) return {};
    const { assets } = (await res.json()) as { assets?: { name?: unknown; browser_download_url?: unknown }[] };
    const installers: Installers = {};
    for (const os of Object.keys(INSTALLER_NAMES) as (keyof Installers)[]) {
      const url = assets?.find((a) => typeof a.name === "string" && INSTALLER_NAMES[os].test(a.name))
        ?.browser_download_url;
      if (typeof url === "string" && url.startsWith(DOWNLOADS)) installers[os] = url;
    }
    return installers;
  } catch {
    // Offline build or GitHub down: the download button opens the releases page.
    return {};
  }
}

// 6 -> "6", 1234 -> "1.2k", 2000 -> "2k"
export function formatCount(n: number): string {
  if (n < 1000) return String(n);
  return `${(n / 1000).toFixed(1).replace(/\.0$/, "")}k`;
}
