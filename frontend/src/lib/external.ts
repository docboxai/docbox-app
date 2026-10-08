import { openUrl } from "@tauri-apps/plugin-opener";

// A plain `target="_blank"` link doesn't open the browser from the Tauri webview on macOS
// or Linux, so web pages go through the opener plugin there. Its capability
// (src-tauri/capabilities/default.json) lists every URL the app may open: add new ones there.
export function openExternal(url: string): Promise<void> {
  if ("__TAURI_INTERNALS__" in window) return openUrl(url);
  window.open(url, "_blank", "noopener,noreferrer");
  return Promise.resolve();
}

/** onClick for an `<a href target="_blank">` that should open in the default browser. */
export function openInBrowser(event: React.MouseEvent<HTMLAnchorElement>) {
  event.preventDefault();
  void openExternal(event.currentTarget.href);
}
