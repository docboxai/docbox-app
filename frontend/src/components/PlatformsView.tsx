import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, XCircle, KeyRound, Cloud, Server, ExternalLink, Type } from "lucide-react";
import { api, type PlatformStatus } from "../lib/api";
import { PrerequisiteCard } from "./PrerequisiteCard";

function PlatformCard({
  icon: Icon,
  title,
  status,
  children,
}: {
  icon: typeof Cloud;
  title: string;
  status: PlatformStatus | undefined;
  children?: React.ReactNode;
}) {
  return (
    <div className="rounded-2xl border border-border bg-panel p-5">
      <div className="mb-3 flex items-center gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-accent-pale">
          <Icon className="h-5 w-5 text-accent" strokeWidth={2} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="font-medium">{title}</div>
        </div>
        {status &&
          (status.available ? (
            <span className="flex items-center gap-1 rounded-full bg-accent-pale px-2 py-0.5 text-xs text-accent">
              <CheckCircle2 className="h-3 w-3" /> Connected
            </span>
          ) : (
            <span className="flex items-center gap-1 rounded-full bg-panel-2 px-2 py-0.5 text-xs text-text-muted">
              <XCircle className="h-3 w-3" /> Not connected
            </span>
          ))}
      </div>
      {status?.detail && <p className="mb-3 text-sm text-text-muted">{status.detail}</p>}
      {children}
    </div>
  );
}

export function PlatformsView() {
  const [platforms, setPlatforms] = useState<PlatformStatus[]>([]);
  const [loading, setLoading] = useState(false);
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [savingKey, setSavingKey] = useState(false);
  const [keyError, setKeyError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setPlatforms(await api.listPlatforms());
    } catch {
      // Backend unreachable state is already surfaced elsewhere (Device tab); keep
      // this view quiet rather than duplicating a connectivity error banner.
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const ollama = platforms.find((p) => p.id === "ollama");
  const nvidia = platforms.find((p) => p.id === "nvidia-nim");

  const saveKey = useCallback(async () => {
    if (!apiKeyInput.trim()) return;
    setSavingKey(true);
    setKeyError(null);
    try {
      await api.setNvidiaApiKey(apiKeyInput.trim());
      setApiKeyInput("");
      await refresh();
    } catch (err) {
      setKeyError(err instanceof Error ? err.message : String(err));
    } finally {
      setSavingKey(false);
    }
  }, [apiKeyInput, refresh]);

  const clearKey = useCallback(async () => {
    setSavingKey(true);
    setKeyError(null);
    try {
      await api.clearNvidiaApiKey();
      await refresh();
    } catch (err) {
      setKeyError(err instanceof Error ? err.message : String(err));
    } finally {
      setSavingKey(false);
    }
  }, [refresh]);

  return (
    <div>
      <p className="mb-6 max-w-[60ch] leading-relaxed text-text-muted">
        Some engines use a program or service from outside DocBox. Ollama and Tesseract
        run on this computer; NVIDIA NIM sends images to NVIDIA's cloud once you connect
        it.
      </p>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <PlatformCard icon={Server} title="Ollama" status={ollama}>
          <p className="mb-3 text-xs text-text-muted">
            Once Ollama is running, pick a model under Setup › Ollama and DocBox
            downloads it for you.
          </p>
          <PrerequisiteCard id="ollama" onReady={() => void refresh()} />
        </PlatformCard>

        <PlatformCard icon={Type} title="Tesseract" status={undefined}>
          <p className="mb-3 text-xs text-text-muted">
            Tesseract needs its free program on this computer; DocBox handles the
            rest.
          </p>
          <PrerequisiteCard id="tesseract" />
        </PlatformCard>

        <PlatformCard icon={Cloud} title="NVIDIA NIM" status={nvidia}>
          <p className="mb-3 text-xs text-warn">
            Cloud, not local — images sent through a NIM model are uploaded to NVIDIA's
            API using the key below. This is the only non-local model source in DocBox.
          </p>
          {nvidia?.available ? (
            <button
              type="button"
              onClick={() => void clearKey()}
              disabled={savingKey}
              className="rounded-full border border-border px-3 py-1.5 text-sm font-medium text-text hover:bg-panel-2 disabled:opacity-50"
            >
              Remove API key
            </button>
          ) : (
            <div className="flex flex-col gap-2">
              <div className="flex items-center gap-2 rounded-full border border-border bg-bg px-3 py-1.5">
                <KeyRound className="h-3.5 w-3.5 text-text-muted" />
                <input
                  type="password"
                  value={apiKeyInput}
                  onChange={(e) => setApiKeyInput(e.target.value)}
                  placeholder="NVIDIA API key"
                  className="w-full bg-transparent text-sm outline-none placeholder:text-text-muted"
                />
              </div>
              <div className="flex items-center justify-between">
                <a
                  href="https://build.nvidia.com"
                  target="_blank"
                  rel="noreferrer"
                  className="flex items-center gap-1 text-xs text-text-muted hover:text-text"
                >
                  Get a key at build.nvidia.com <ExternalLink className="h-3 w-3" />
                </a>
                <button
                  type="button"
                  onClick={() => void saveKey()}
                  disabled={savingKey || !apiKeyInput.trim()}
                  className="rounded-full bg-accent px-3 py-1.5 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
                >
                  Connect
                </button>
              </div>
              {keyError && <p className="text-xs text-warn">{keyError}</p>}
            </div>
          )}
        </PlatformCard>
      </div>

      {loading && platforms.length === 0 && (
        <p className="mt-4 text-sm text-text-muted">Checking platforms…</p>
      )}
    </div>
  );
}
