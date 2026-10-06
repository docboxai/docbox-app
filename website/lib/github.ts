// The repository's real star count for the "Star on GitHub" button. The page is
// regenerated at most hourly (app/page.tsx), so this stays well inside GitHub's
// unauthenticated rate limit.
export async function getStarCount(): Promise<number | null> {
  try {
    const res = await fetch("https://api.github.com/repos/docboxai/docbox-app", {
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

// 6 -> "6", 1234 -> "1.2k", 2000 -> "2k"
export function formatCount(n: number): string {
  if (n < 1000) return String(n);
  return `${(n / 1000).toFixed(1).replace(/\.0$/, "")}k`;
}
