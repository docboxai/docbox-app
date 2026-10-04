import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { check, type Update } from "@tauri-apps/plugin-updater";
import { relaunch } from "@tauri-apps/plugin-process";
import { Download, X } from "lucide-react";
import { Button, Spinner } from "./ui";

// Checks GitHub Releases once per launch; offers a one-click install when there's a
// newer signed release. Installed engines and models live in the data dir, so they
// survive the update.
export function UpdateBanner() {
  const [update, setUpdate] = useState<Update | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [phase, setPhase] = useState<"idle" | "downloading" | "installing">("idle");
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!("__TAURI_INTERNALS__" in window)) return;
    check()
      .then((u) => setUpdate(u))
      .catch(() => {
        // Offline, rate-limited, or no release yet: just don't show a banner.
      });
  }, []);

  if (!update || dismissed) return null;

  const install = async () => {
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
      setError(err instanceof Error ? err.message : String(err));
      setPhase("idle");
    }
  };

  return (
    <div role="status" className="flex shrink-0 flex-wrap items-center gap-3 rounded-2xl bg-secondary-soft px-5 py-2 text-sm text-on-light">
      <span className="flex-1 font-medium">
        DocBox {update.version} is available.
        {error && <span className="ml-2 font-normal">{error}</span>}
      </span>
      {phase === "idle" ? (
        <>
          <Button size="sm" variant="ink" icon={Download} onClick={() => void install()}>
            Install &amp; restart
          </Button>
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
