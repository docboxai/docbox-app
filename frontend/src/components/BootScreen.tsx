import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { AlertTriangle, Loader2, RotateCcw } from "lucide-react";
import { Logo } from "./Logo";
import { CaptionBand } from "./Poster";

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
    <div className="relative flex h-screen flex-col overflow-hidden bg-bg text-text">
      <div
        aria-hidden="true"
        className="absolute inset-x-0 bottom-12 h-56 bg-accent-light"
        style={{
          clipPath:
            "polygon(0 55%, 8% 55%, 8% 30%, 17% 30%, 17% 48%, 26% 48%, 26% 12%, 33% 12%, 33% 40%, 45% 40%, 45% 22%, 58% 22%, 58% 50%, 66% 50%, 66% 8%, 74% 8%, 74% 35%, 86% 35%, 86% 18%, 94% 18%, 94% 45%, 100% 45%, 100% 100%, 0 100%)",
        }}
      />
      <div
        aria-hidden="true"
        className="absolute inset-x-0 bottom-12 h-32 bg-accent-bright"
        style={{
          clipPath:
            "polygon(0 60%, 12% 60%, 12% 25%, 21% 25%, 21% 55%, 37% 55%, 37% 10%, 49% 10%, 49% 45%, 62% 45%, 62% 30%, 79% 30%, 79% 60%, 90% 60%, 90% 20%, 100% 20%, 100% 100%, 0 100%)",
        }}
      />

      <div className="relative flex flex-1 items-start justify-center overflow-y-auto px-6 pt-[12vh] pb-60">
        <div className="flex w-full max-w-xl flex-col gap-5">
          <div className="flex items-center gap-3.5">
            <Logo size={56} />
            <span className="text-5xl leading-none font-extrabold tracking-tighter">DocBox</span>
          </div>

          {failed ? (
            <div className="rounded-[20px] border-2 border-warn bg-panel p-6">
              <div className="mb-2 flex items-center gap-2 text-lg font-extrabold text-warn">
                <AlertTriangle className="h-5 w-5" /> DocBox couldn't start
              </div>
              <pre className="mb-3 max-h-48 overflow-auto font-mono text-xs whitespace-pre-wrap text-text-muted">
                {status?.message}
              </pre>
              {status?.log_path && (
                <p className="mb-4 text-xs break-all text-text-muted">Logs: {status.log_path}</p>
              )}
              <button
                type="button"
                onClick={() => {
                  void invoke("retry_backend");
                  setStatus((s) => (s ? { ...s, state: "starting", progress: 0 } : s));
                }}
                className="flex min-h-11 items-center gap-2 rounded-full bg-ink px-5 font-bold text-white"
              >
                <RotateCcw className="h-4 w-4" /> Try again
              </button>
            </div>
          ) : (
            <div className="flex flex-col gap-4 rounded-[20px] border-2 border-ink bg-panel p-6">
              <div className="text-[22px] font-extrabold">Getting DocBox ready</div>
              <p className="leading-relaxed text-text/80">
                The first time, DocBox sets up its own tools. It takes a minute or two and
                needs an internet connection. Your files never leave this computer.
              </p>
              <div>
                <div
                  className="h-3 overflow-hidden rounded-full bg-accent-pale"
                  role="progressbar"
                  aria-valuenow={Math.round(progress)}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-label="Setting up DocBox"
                >
                  <div
                    className="h-3 rounded-full transition-all"
                    style={{
                      width: `${Math.max(4, progress)}%`,
                      background:
                        "repeating-linear-gradient(-45deg, var(--color-accent-bright) 0 10px, var(--color-accent) 10px 20px)",
                    }}
                  />
                </div>
                <div className="mt-2.5 flex items-center gap-2 text-sm">
                  <Loader2 className="h-4 w-4 shrink-0 animate-spin text-accent" />
                  <span className="truncate">{status?.message || "Starting"}</span>
                  <span className="ml-auto font-mono font-bold">{Math.round(progress)}%</span>
                </div>
              </div>
            </div>
          )}
          <p className="text-sm text-text-muted">
            Reading engines like PaddleOCR install later, only when you choose one.
          </p>
        </div>
      </div>

      <div className="relative">
        <CaptionBand>
          <span>001</span>
          <span>DOCBOX · LOCAL OCR</span>
          <span className="text-accent-light">WELCOME</span>
        </CaptionBand>
      </div>
    </div>
  );
}
