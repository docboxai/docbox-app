import { openUrl } from "@tauri-apps/plugin-opener";

// Web pages the app links to. The opener capability (src-tauri/capabilities/default.json)
// allows exactly these, plus the benchmark score sources in benchmark/ocrbench.json; add
// new ones in both places (tests/backend/test_external_links.py checks they agree).
export const RELEASES_PAGE = "https://github.com/docboxai/docbox-app/releases/latest";
export const NVIDIA_KEYS_PAGE = "https://build.nvidia.com/";

// A plain `target="_blank"` link doesn't open the browser from the Tauri webview on macOS
// or Linux, so web pages go through the opener plugin there. The plugin compares URLs
// as exact strings, so they're sent the way a browser normalises them (a bare domain gets
// a trailing "/", as an anchor's `href` property does): the capability lists that form.
export function openExternal(url: string): Promise<void> {
  const normalised = new URL(url).href;
  if ("__TAURI_INTERNALS__" in window) return openUrl(normalised);
  window.open(normalised, "_blank", "noopener,noreferrer");
  return Promise.resolve();
}

/** onClick for an `<a href target="_blank">` that should open in the default browser. */
export function openInBrowser(event: React.MouseEvent<HTMLAnchorElement>) {
  event.preventDefault();
  void openExternal(event.currentTarget.href);
}
