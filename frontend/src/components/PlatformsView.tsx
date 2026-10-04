import { useCallback, useEffect, useState } from "react";
import { ExternalLink, KeyRound } from "lucide-react";
import { api, type PlatformStatus } from "../lib/api";
import { useApp } from "../lib/app";
import { PrerequisiteCard } from "./PrerequisiteCard";
import { Button, Card, Chip, SectionLabel, Switch } from "./ui";

function StatusChip({ status }: { status: PlatformStatus | undefined }) {
  if (!status) return null;
  return status.available ? <Chip tone="success">Connected</Chip> : <Chip tone="warning">Not connected</Chip>;
}

function Connection({
  title,
  where,
  status,
  children,
}: {
  title: string;
  where: string;
  status?: PlatformStatus;
  children: React.ReactNode;
}) {
  return (
    <section aria-label={title} className="flex min-w-0 flex-[1_1_360px] flex-col gap-2.5">
      <SectionLabel>{where}</SectionLabel>
      <Card className="flex flex-1 flex-col gap-4 px-5 pt-4 pb-5">
        <div className="flex items-center justify-between gap-3">
          <h2 className="font-heading text-[26px] leading-[1.1] font-semibold tracking-[-0.5px]">{title}</h2>
          <StatusChip status={status} />
        </div>
        {status?.detail && <p className="text-sm leading-relaxed text-fg-muted">{status.detail}</p>}
        {children}
      </Card>
    </section>
  );
}

export function PlatformsView() {
  const { settings, updateSettings, bump } = useApp();
  const [platforms, setPlatforms] = useState<PlatformStatus[]>([]);
  const [keySaved, setKeySaved] = useState(false);
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [savingKey, setSavingKey] = useState(false);
  const [keyError, setKeyError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [list, key] = await Promise.all([api.listPlatforms(), api.nvidiaApiKeyStatus()]);
      setPlatforms(list);
      setKeySaved(key.configured);
    } catch {
      // An unreachable backend is reported by the other views; keep this one quiet.
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh, settings?.cloud_enabled]);

  const ollama = platforms.find((p) => p.id === "ollama");
  const nvidia = platforms.find((p) => p.id === "nvidia-nim");
  const cloud = settings?.cloud_enabled ?? false;

  const saveKey = useCallback(async () => {
    if (!apiKeyInput.trim()) return;
    setSavingKey(true);
    setKeyError(null);
    try {
      await api.setNvidiaApiKey(apiKeyInput.trim());
      setApiKeyInput("");
      await refresh();
      bump();
    } catch (err) {
      setKeyError(err instanceof Error ? err.message : String(err));
    } finally {
      setSavingKey(false);
    }
  }, [apiKeyInput, refresh, bump]);

  const clearKey = useCallback(async () => {
    setSavingKey(true);
    setKeyError(null);
    try {
      await api.clearNvidiaApiKey();
      await refresh();
      bump();
    } catch (err) {
      setKeyError(err instanceof Error ? err.message : String(err));
    } finally {
      setSavingKey(false);
    }
  }, [refresh, bump]);

  return (
    <div className="flex flex-col gap-4">
      <p className="max-w-[70ch] text-sm leading-relaxed text-fg-muted">
        Some engines use a program or service from outside DocBox. Ollama and Tesseract run on
        this computer; NVIDIA NIM sends images to NVIDIA's cloud, and only while the cloud
        engine is switched on.
      </p>
      <div className="flex flex-wrap items-stretch gap-4">
        <Connection title="Ollama" where="On this computer" status={ollama}>
          <p className="text-[13px] text-fg-muted">
            Once Ollama is running, pick a model under Setup › Ollama and DocBox downloads it for you.
          </p>
          <PrerequisiteCard id="ollama" onReady={() => void refresh()} />
        </Connection>

        <Connection title="Tesseract" where="On this computer">
          <p className="text-[13px] text-fg-muted">
            Tesseract needs its free program on this computer; DocBox handles the rest.
          </p>
          <PrerequisiteCard id="tesseract" />
        </Connection>

        <Connection title="NVIDIA NIM" where="In the cloud" status={nvidia}>
          <Card tone="grey" className="flex items-center justify-between gap-3 px-4 py-3">
            <span className="text-sm font-medium">
              Cloud engine {cloud ? "on" : "off"}
              <span className="block text-[13px] font-normal text-on-light-muted">
                {cloud ? "Images read with NIM models go to NVIDIA." : "Nothing leaves this computer."}
              </span>
            </span>
            <Switch
              label="Cloud engine: allow NVIDIA's cloud models"
              checked={cloud}
              disabled={!settings}
              onChange={(next) => void updateSettings({ cloud_enabled: next })}
            />
          </Card>
          {keySaved ? (
            <div>
              <Button size="sm" variant="outline" onClick={() => void clearKey()} disabled={savingKey}>
                Remove API key
              </Button>
            </div>
          ) : (
            <form
              className="flex flex-col gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                void saveKey();
              }}
            >
              <label className="flex h-10 items-center gap-2 rounded-xl bg-ink px-3 ring-1 ring-line ring-inset focus-within:ring-secondary">
                <KeyRound aria-hidden="true" className="h-4 w-4 text-fg-muted" />
                <span className="sr-only">NVIDIA API key</span>
                <input
                  type="password"
                  value={apiKeyInput}
                  onChange={(e) => setApiKeyInput(e.target.value)}
                  placeholder="NVIDIA API key"
                  autoComplete="off"
                  className="w-full bg-transparent text-sm outline-none placeholder:text-fg-muted focus-visible:outline-none"
                />
              </label>
              <div className="flex items-center justify-between gap-3">
                <a
                  href="https://build.nvidia.com"
                  target="_blank"
                  rel="noreferrer"
                  className="flex items-center gap-1 text-xs text-fg-muted underline-offset-2 hover:text-fg hover:underline"
                >
                  Get a key at build.nvidia.com <ExternalLink aria-hidden="true" className="h-3 w-3" />
                </a>
                <Button type="submit" size="sm" disabled={savingKey || !apiKeyInput.trim()}>
                  Connect
                </Button>
              </div>
            </form>
          )}
          {keyError && <p className="text-xs text-danger">{keyError}</p>}
        </Connection>
      </div>
    </div>
  );
}
