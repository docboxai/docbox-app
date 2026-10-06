import { useEffect, useState } from "react";
import { getVersion } from "@tauri-apps/api/app";
import { openUrl } from "@tauri-apps/plugin-opener";
import { Download, X } from "lucide-react";
import { Button } from "./ui";

const LATEST_RELEASE_API = "https://api.github.com/repos/docboxai/docbox-app/releases/latest";
// The one URL the opener capability allows (src-tauri/capabilities/default.json).
const RELEASES_PAGE = "https://github.com/docboxai/docbox-app/releases/latest";

/** "1.2.3" or "v1.2.3" as numbers; null for anything else. */
function parseVersion(version: string) {
  const m = /^v?(\d+)\.(\d+)\.(\d+)$/.exec(version);
  return m ? m.slice(1).map(Number) : null;
}

function isNewer(latest: string, current: string) {
  const a = parseVersion(latest);
  const b = parseVersion(current);
  if (!a || !b) return false;
  const i = a.findIndex((n, k) => n !== b[k]);
  return i !== -1 && a[i] > b[i];
}

// Checks GitHub once per launch for a newer release and links to its download page.
// Updating means running the new installer; engines, models and settings live in the
// data dir, so they're kept.
export function UpdateBanner() {
  const [latest, setLatest] = useState<string | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!("__TAURI_INTERNALS__" in window)) return;
    Promise.all([getVersion(), fetch(LATEST_RELEASE_API).then((r) => (r.ok ? r.json() : null))])
      .then(([current, release]) => {
        const tag: unknown = release?.tag_name;
        if (typeof tag === "string" && isNewer(tag, current)) setLatest(tag.replace(/^v/, ""));
      })
      .catch(() => {
        // Offline or rate-limited: just don't show a banner.
      });
  }, []);

  if (!latest || dismissed) return null;

  return (
    <div role="status" className="flex shrink-0 flex-wrap items-center gap-3 rounded-2xl bg-secondary-soft px-5 py-2 text-sm text-on-light">
      <span className="flex-1 font-medium">
        DocBox {latest} is available.
        {error && <span className="ml-2 font-normal">{error}</span>}
      </span>
      <Button
        size="sm"
        variant="ink"
        icon={Download}
        onClick={() => openUrl(RELEASES_PAGE).catch((err) => setError(String(err)))}
      >
        Download
      </Button>
      <button
        type="button"
        onClick={() => setDismissed(true)}
        aria-label="Dismiss update notice"
        className="rounded-full p-1.5 hover:bg-ink/10"
      >
        <X aria-hidden="true" className="h-4 w-4" />
      </button>
    </div>
  );
}
