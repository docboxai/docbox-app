import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { RotateCcw } from "lucide-react";
import { LogoMark, LogoTile } from "./Logo";
import { Button, ProgressBar, Spinner } from "./ui";

interface BootStatus {
  state: "starting" | "ready" | "failed";
  message: string;
  progress: number;
  base_url: string | null;
  log_path: string | null;
}

const IN_TAURI = "__TAURI_INTERNALS__" in window;

// Shown until the backend is up. On first launch of an installed build that includes
// a one-time Python setup (the Rust shell runs the bundled uv); afterwards it's a
// second or two while the backend starts.
export function BootGate({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<BootStatus | null>(
    IN_TAURI ? null : { state: "ready", message: "", progress: 100, base_url: null, log_path: null },
  );

  useEffect(() => {
    if (!IN_TAURI) return;
    let cancelled = false;
    const poll = async () => {
      while (!cancelled) {
        try {
          const s = await invoke<BootStatus>("backend_status");
          setStatus(s);
          if (s.state === "ready") return;
        } catch {
          // The command is always registered; a failure here is transient.
        }
        await new Promise((r) => setTimeout(r, 500));
      }
    };
    void poll();
    return () => {
      cancelled = true;
    };
  }, []);

  if (status?.state === "ready") return <>{children}</>;

  const failed = status?.state === "failed";
  const progress = status?.progress ?? 0;

  return (
    <div className="flex h-screen flex-col gap-4 bg-ink p-4 text-fg">
      <div className="flex min-h-0 flex-1 flex-col justify-between gap-8 overflow-y-auto rounded-[20px] bg-hero px-7 pt-6 pb-7 text-on-light">
        <div className="flex items-center gap-2.5">
          <LogoTile />
          <span className="font-heading text-xl font-bold">DocBox</span>
        </div>
        <div className="flex flex-wrap items-end justify-between gap-6">
          <div className="flex max-w-xl min-w-0 flex-col gap-2.5">
            <p className="text-[13px] font-medium tracking-[0.3px] text-on-light-muted">WELCOME</p>
            <h1 className="font-heading text-[clamp(44px,5vw,64px)] leading-none font-semibold tracking-[-1.5px]">
              {failed ? "DocBox couldn't start" : "Getting DocBox ready"}
            </h1>
            <p className="leading-relaxed text-on-light-muted">
              {failed
                ? "Something went wrong while starting DocBox's engine."
                : "The first time, DocBox sets up its own tools. It takes a minute or two and needs an internet connection. Your files never leave this computer."}
            </p>
          </div>
          <LogoMark height={120} className="hidden text-ink/90 md:block" />
        </div>
      </div>

      <div className="flex shrink-0 flex-col gap-3 rounded-2xl bg-surface px-5 py-4 ring-1 ring-line ring-inset">
        {failed ? (
          <>
            <pre className="max-h-48 overflow-auto text-xs whitespace-pre-wrap text-fg-muted">{status?.message}</pre>
            {status?.log_path && <p className="text-xs break-all text-fg-muted">Logs: {status.log_path}</p>}
            <div>
              <Button
                variant="light"
                icon={RotateCcw}
                onClick={() => {
                  void invoke("retry_backend");
                  setStatus((s) => (s ? { ...s, state: "starting", progress: 0 } : s));
                }}
              >
                Try again
              </Button>
            </div>
          </>
        ) : (
          <>
            <ProgressBar value={progress} label="Setting up DocBox" />
            <div className="flex items-center gap-2 text-sm">
              <Spinner className="text-secondary" />
              <span className="truncate">{status?.message || "Starting"}</span>
              <span className="ml-auto font-medium tabular-nums">{Math.round(progress)}%</span>
            </div>
            <p className="text-[13px] text-fg-muted">
              Reading engines like PaddleOCR install later, only when you choose one.
            </p>
          </>
        )}
      </div>
    </div>
  );
}
