// Where the page's links go. Everything lives on GitHub: the app's releases, its README
// (install guide, engine guide) and the repository itself.
const REPO = "https://github.com/docboxai/docbox-app";

export const links = {
  repo: REPO,
  download: `${REPO}/releases/latest`,
  changelog: `${REPO}/releases`,
  docs: `${REPO}#readme`,
  engines: `${REPO}#which-engine-should-i-use`,
  privacy: `${REPO}#privacy`,
} as const;
