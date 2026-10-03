import { useCallback, useEffect, useRef, useState } from "react";
import { CheckCircle2, Copy, ExternalLink, Loader2, Play, RefreshCw, Wrench } from "lucide-react";
import { api, type PrerequisiteInfo } from "../lib/api";

// Guided setup for an external program an engine needs (Ollama, Tesseract): one-click
// install on Windows (winget, with its own UAC prompt), copyable commands elsewhere,
// "Start" for an installed-but-stopped Ollama, and "Check again".
export function PrerequisiteCard({ id, onReady }: { id: string; onReady?: () => void }) {
  const [info, setInfo] = useState<PrerequisiteInfo | null>(null);
  const [checking, setChecking] = useState(false);
  const [installing, setInstalling] = useState(false);
  const [progress, setProgress] = useState(0);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);

  // A ref, so a parent passing a fresh callback each render doesn't retrigger the check
  // (which calls onReady, which re-renders the parent...).
  const onReadyRef = useRef(onReady);
  onReadyRef.current = onReady;
  const wasReady = useRef<boolean | null>(null);

  const check = useCallback(async () => {
    setChecking(true);
    try {
      const next = await api.getPrerequisite(id);
      setInfo(next);
      const ready = next.state === "ready";
      // Only announce a *change* to ready (e.g. right after an install), not every check.
      if (ready && wasReady.current === false) onReadyRef.current?.();
      wasReady.current = ready;
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setChecking(false);
    }
  }, [id]);

  useEffect(() => {
    void check();
  }, [check]);

  const install = useCallback(async () => {
    setInstalling(true);
    setError(null);
    setProgress(0);
    try {
      const { job_id } = await api.startPrerequisiteInstall(id);
      // eslint-disable-next-line no-constant-condition
      while (true) {
        const status = await api.prerequisiteInstallStatus(id, job_id);
        setProgress(status.progress_pct ?? 0);
        setMessage(status.message);
        if (status.state === "done") break;
        if (status.state === "error") {
          setError(status.message ?? "Install failed");
          break;
        }
        await new Promise((r) => setTimeout(r, 1000));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setInstalling(false);
      await check();
    }
  }, [id, check]);

  const start = useCallback(async () => {
    setError(null);
    try {
      await api.startOllama();
      // The server takes a moment to accept connections after launch.
      await new Promise((r) => setTimeout(r, 2500));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
    await check();
  }, [check]);

  const copy = useCallback(async (cmd: string) => {
    try {
      await navigator.clipboard.writeText(cmd);
      setCopied(cmd);
      setTimeout(() => setCopied(null), 1500);
    } catch {
      setError("Couldn't copy; select the command and copy it manually.");
    }
  }, []);

  if (!info) {
    return (
      <div className="rounded-xl border border-border bg-panel-2 px-4 py-3 text-sm text-text-muted">
        {error ?? "Checking…"}
      </div>
    );
  }

  if (info.state === "ready") {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-border bg-panel-2 px-4 py-3 text-sm">
        <CheckCircle2 className="h-4 w-4 text-accent" />
        {info.id === "ollama" ? `${info.name} is installed and running.` : `${info.name} is installed.`}
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-ink bg-panel-2 px-4 py-4">
      <div className="mb-1 flex items-center gap-2 font-medium">
        <Wrench className="h-4 w-4 text-accent" />
        {info.state === "installed" ? `${info.name} isn't running` : `${info.name} is needed`}
      </div>
      <p className="mb-3 text-sm text-text-muted">{info.about}</p>

      {installing ? (
        <div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-panel">
            <div
              className="h-full rounded-full bg-accent transition-all"
              style={{ width: `${Math.max(4, progress)}%` }}
            />
          </div>
          <div className="mt-2 flex items-center gap-1.5 text-xs text-text-muted">
            <Loader2 className="h-3 w-3 animate-spin" />
            <span className="truncate">{message ?? "Installing…"}</span>
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {info.can_start && (
            <button
              type="button"
              onClick={() => void start()}
              className="flex w-fit items-center gap-1.5 rounded-full bg-accent px-3 py-1.5 text-sm font-medium text-white"
            >
              <Play className="h-3.5 w-3.5" /> Start {info.name}
            </button>
          )}
          {info.can_auto_install && (
            <button
              type="button"
              onClick={() => void install()}
              className="flex w-fit items-center gap-1.5 rounded-full bg-accent px-3 py-1.5 text-sm font-medium text-white"
            >
              Install {info.name} for me
            </button>
          )}
          {info.state === "missing" && (
            <div className="flex flex-col gap-1.5">
              <span className="text-xs text-text-muted">
                {info.can_auto_install ? "Or run this yourself:" : "Run this in a terminal:"}
              </span>
              {info.commands.map((cmd) => (
                <div key={cmd} className="flex items-center gap-2">
                  <code className="min-w-0 flex-1 overflow-x-auto whitespace-nowrap rounded bg-bg px-2 py-1.5 text-xs">
                    {cmd}
                  </code>
                  <button
                    type="button"
                    onClick={() => void copy(cmd)}
                    aria-label={`Copy command: ${cmd}`}
                    className="flex items-center gap-1 rounded-full border border-border px-2.5 py-1 text-xs text-text-muted hover:bg-panel"
                  >
                    <Copy className="h-3 w-3" /> {copied === cmd ? "Copied" : "Copy"}
                  </button>
                </div>
              ))}
              <a
                href={info.download_url}
                target="_blank"
                rel="noreferrer"
                className="flex w-fit items-center gap-1 text-xs text-text-muted hover:text-text"
              >
                Or download it from the official site <ExternalLink className="h-3 w-3" />
              </a>
            </div>
          )}
          <button
            type="button"
            onClick={() => void check()}
            disabled={checking}
            className="flex w-fit items-center gap-1.5 rounded-full border border-border px-3 py-1.5 text-sm text-text hover:bg-panel disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${checking ? "animate-spin" : ""}`} /> Check again
          </button>
        </div>
      )}
      {error && <p className="mt-2 text-xs text-warn">{error}</p>}
    </div>
  );
}
