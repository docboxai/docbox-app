import { useEffect, useState } from "react";
import { getVersion } from "@tauri-apps/api/app";
import { invoke } from "@tauri-apps/api/core";
import { relaunch } from "@tauri-apps/plugin-process";
import { check, type Update } from "@tauri-apps/plugin-updater";
import { Download, X } from "lucide-react";
import { openExternal } from "../lib/external";
import { Button, Spinner } from "./ui";

const LATEST_RELEASE_API = "https://api.github.com/repos/docboxai/docbox-app/releases/latest";
// Allowed by the opener capability (src-tauri/capabilities/default.json).
const RELEASES_PAGE = "https://github.com/docboxai/docbox-app/releases/latest";

/** "1.2.3" or "v1.2.3" as numbers; null for anything else. */
function parseVersion(version: string) {
  const m = /^v?(\d+)\.(\d+)\.(\d+)$/.exec(version);
  return m ? m.slice(1).map(Number) : null;
}

export function isNewer(latest: string, current: string) {
  const a = parseVersion(latest);
  const b = parseVersion(current);
  if (!a || !b) return false;
  const i = a.findIndex((n, k) => n !== b[k]);
  return i !== -1 && a[i] > b[i];
}

/** A signed update the app installs itself, or only a version to download by hand. */
type Available = { kind: "install"; update: Update } | { kind: "download"; version: string };

// Checks once per launch. A release's signed latest.json lets the app download, verify and
// install the update itself (on Linux .deb/.rpm installs the system asks for a password);
// if that check finds nothing usable, GitHub's latest release still shows the notice, with
// a link to download it. Engines, models and settings live in the data dir, so they're kept.
async function findUpdate(): Promise<Available | null> {
  try {
    const update = await check();
    if (update) return { kind: "install", update };
  } catch {
    // No latest.json, a bad signature, offline: try the plain check below.
  }
  const [current, release] = await Promise.all([
    getVersion(),
    fetch(LATEST_RELEASE_API).then((r) => (r.ok ? r.json() : null)),
  ]);
  const tag: unknown = release?.tag_name;
  return typeof tag === "string" && isNewer(tag, current) ? { kind: "download", version: tag.replace(/^v/, "") } : null;
}

export function UpdateBanner() {
  const [available, setAvailable] = useState<Available | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [phase, setPhase] = useState<"idle" | "downloading" | "installing">("idle");
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  // After a failed in-app install, Download is offered as well.
  const [offerDownload, setOfferDownload] = useState(false);

  useEffect(() => {
    if (!("__TAURI_INTERNALS__" in window)) return;
    findUpdate().then(setAvailable, () => {
      // Offline or rate-limited: just don't show a banner.
    });
  }, []);

  if (!available || dismissed) return null;

  const version = available.kind === "install" ? available.update.version : available.version;

  const install = async (update: Update) => {
    setError(null);
    setPhase("downloading");
    try {
      let total = 0;
      let received = 0;
      await update.download((event) => {
        if (event.event === "Started") total = event.data.contentLength ?? 0;
        if (event.event === "Progress") {
          received += event.data.chunkLength;
          if (total) setProgress(Math.round((100 * received) / total));
        }
      });
      setPhase("installing");
      // Stop the backend first: on Windows the installer replaces files it holds open,
      // and the updater exits the app without the usual close handling.
      await invoke("prepare_restart");
      await update.install();
      await relaunch();
    } catch (err) {
      setError(`Couldn't install it: ${err instanceof Error ? err.message : String(err)}`);
      setOfferDownload(true);
      setPhase("idle");
    }
  };

  const download = () => openExternal(RELEASES_PAGE).catch((err) => setError(String(err)));

  return (
    <div role="status" className="flex shrink-0 flex-wrap items-center gap-3 rounded-2xl bg-secondary-soft px-5 py-2 text-sm text-on-light">
      <span className="flex-1 font-medium">
        DocBox {version} is available.
        {error && <span className="ml-2 font-normal">{error}</span>}
      </span>
      {phase === "idle" ? (
        <>
          {available.kind === "install" && (
            <Button size="sm" variant="ink" icon={Download} onClick={() => void install(available.update)}>
              Install &amp; restart
            </Button>
          )}
          {(available.kind === "download" || offerDownload) && (
            <Button size="sm" variant={available.kind === "download" ? "ink" : "ghost"} icon={Download} onClick={() => void download()}>
              Download
            </Button>
          )}
          <button
            type="button"
            onClick={() => setDismissed(true)}
            aria-label="Dismiss update notice"
            className="rounded-full p-1.5 hover:bg-ink/10"
          >
            <X aria-hidden="true" className="h-4 w-4" />
          </button>
        </>
      ) : (
        <span className="flex items-center gap-1.5">
          <Spinner />
          {phase === "downloading" ? `Downloading ${progress}%` : "Installing…"}
        </span>
      )}
    </div>
  );
}
