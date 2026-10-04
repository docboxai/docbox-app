import { useCallback, useEffect, useRef, useState } from "react";
import { Check, Copy, Download, ExternalLink, Play, RefreshCw, Wrench } from "lucide-react";
import { api, type PrerequisiteInfo } from "../lib/api";
import { Button, Card, ProgressBar, Spinner } from "./ui";

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
      <Card className="flex items-center gap-2 px-4 py-3 text-sm text-fg-muted">
        {error ?? (
          <>
            <Spinner /> Checking…
          </>
        )}
      </Card>
    );
  }

  if (info.state === "ready") {
    return (
      <Card className="flex items-center gap-2 px-4 py-3 text-sm">
        <Check aria-hidden="true" className="h-4 w-4 text-secondary" />
        {info.id === "ollama" ? `${info.name} is installed and running.` : `${info.name} is installed.`}
      </Card>
    );
  }

  return (
    <Card className="flex flex-col gap-3 px-4 py-4">
      <div>
        <div className="mb-1 flex items-center gap-2 font-medium">
          <Wrench aria-hidden="true" className="h-4 w-4 text-warning" />
          {info.state === "installed" ? `${info.name} isn't running` : `${info.name} is needed`}
        </div>
        <p className="text-sm leading-relaxed text-fg-muted">{info.about}</p>
      </div>

      {installing ? (
        <div className="flex flex-col gap-1.5">
          <ProgressBar value={progress} label={`Installing ${info.name}`} />
          <div className="flex items-center gap-1.5 text-xs text-fg-muted">
            <Spinner />
            <span className="truncate">{message ?? "Installing…"}</span>
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap gap-2">
            {info.can_start && (
              <Button size="sm" icon={Play} onClick={() => void start()}>
                Start {info.name}
              </Button>
            )}
            {info.can_auto_install && (
              <Button size="sm" icon={Download} onClick={() => void install()}>
                Install {info.name} for me
              </Button>
            )}
            <Button
              size="sm"
              variant="outline"
              icon={checking ? undefined : RefreshCw}
              disabled={checking}
              onClick={() => void check()}
            >
              {checking && <Spinner />}
              Check again
            </Button>
          </div>
          {info.state === "missing" && (
            <div className="flex flex-col gap-1.5">
              <span className="text-xs text-fg-muted">
                {info.can_auto_install ? "Or run this yourself:" : "Run this in a terminal:"}
              </span>
              {info.commands.map((cmd) => (
                <div key={cmd} className="flex items-center gap-2">
                  <code className="min-w-0 flex-1 overflow-x-auto rounded-lg bg-ink px-2.5 py-1.5 text-xs whitespace-nowrap">
                    {cmd}
                  </code>
                  <Button size="sm" variant="ghost" icon={Copy} aria-label={`Copy command: ${cmd}`} onClick={() => void copy(cmd)}>
                    {copied === cmd ? "Copied" : "Copy"}
                  </Button>
                </div>
              ))}
              <a
                href={info.download_url}
                target="_blank"
                rel="noreferrer"
                className="flex w-fit items-center gap-1 text-xs text-fg-muted underline-offset-2 hover:text-fg hover:underline"
              >
                Or download it from the official site <ExternalLink aria-hidden="true" className="h-3 w-3" />
              </a>
            </div>
          )}
        </div>
      )}
      {error && <p className="text-xs text-danger">{error}</p>}
    </Card>
  );
}
