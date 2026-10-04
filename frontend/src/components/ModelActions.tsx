import { useState } from "react";
import { Check, Download, PackagePlus, Pause, Play, Star, Trash2 } from "lucide-react";
import type { ModelInfo } from "../lib/api";
import { useApp } from "../lib/app";
import { PREREQUISITE_LABELS } from "../lib/engineMeta";
import { formatMb } from "../lib/format";
import type { ModelJob } from "../lib/useModelJob";
import { Button, ProgressBar, Spinner, cx } from "./ui";

export function isCloud(model: ModelInfo): boolean {
  return model.engine === "nvidia-nim";
}

export function sizeLabel(model: ModelInfo): string {
  return isCloud(model) ? "Cloud" : formatMb(model.approx_download_mb);
}

// What a model needs before it can run, in a few words; null when it's ready.
export function needsLabel(model: ModelInfo): string | null {
  if (model.status === "ready") return null;
  if (model.status === "needs_prerequisite") {
    return `Needs ${PREREQUISITE_LABELS[model.prerequisite ?? ""] ?? model.prerequisite}`;
  }
  if (isCloud(model)) return "Needs a key";
  return null;
}

// The compact control for a table row: Install / progress + Pause / Resume / Installed.
export function ModelActionCell({ model, job }: { model: ModelInfo; job: ModelJob }) {
  const { navigate } = useApp();

  if (job.phase === "running" || job.phase === "pausing") {
    return (
      <span className="flex items-center gap-2 text-[13px] text-fg-muted tabular-nums">
        <Spinner className="text-secondary" />
        {Math.round(job.progress)}%
        <Button
          size="sm"
          variant="ghost"
          icon={Pause}
          aria-label={`Pause setting up ${model.name}`}
          title={job.phase === "pausing" ? "Pausing after the current step" : "Pause"}
          disabled={job.phase === "pausing"}
          onClick={() => void job.pause()}
         
        />
      </span>
    );
  }
  if (job.phase === "paused") {
    return (
      <Button size="sm" variant="outline" icon={Play} onClick={() => void job.start()}>
        Resume · {Math.round(job.progress)}%
      </Button>
    );
  }
  if (model.status === "ready") {
    return (
      <span className="flex h-8 items-center gap-[5px] px-3 text-[13px] font-medium text-secondary">
        <Check aria-hidden="true" className="h-3.5 w-3.5" /> {isCloud(model) ? "Connected" : "Installed"}
      </span>
    );
  }
  const needs = needsLabel(model);
  if (needs) {
    return (
      <Button size="sm" variant="muted" onClick={() => navigate("platforms")} title="Set it up under Connections">
        {needs}
      </Button>
    );
  }
  return (
    <Button
      size="sm"
      icon={model.status === "needs_engine" ? PackagePlus : Download}
      title={model.status === "needs_engine" ? "Installs this engine once, then the model" : undefined}
      onClick={() => void job.start()}
    >
      {model.engine === "ollama" ? "Pull" : "Install"}
    </Button>
  );
}

// The full control: progress with its message, the main action, Remove (with an inline
// confirm) and Use as default. `light` is for purple/blue cards.
export function ModelSetupPanel({
  model,
  job,
  light = false,
}: {
  model: ModelInfo;
  job: ModelJob;
  light?: boolean;
}) {
  const { settings, updateSettings, navigate } = useApp();
  const [confirmRemove, setConfirmRemove] = useState(false);
  const muted = light ? "text-on-light-muted" : "text-fg-muted";
  const isDefault = settings?.default_model_id === model.id;
  const busy = job.phase === "running" || job.phase === "pausing";

  return (
    <div className="flex flex-col gap-3">
      {(busy || job.phase === "paused") && (
        <div className="flex flex-col gap-1.5">
          <ProgressBar value={job.progress} label={`Setting up ${model.name}`} light={light} />
          <div className={cx("flex items-center gap-1.5 text-xs", light ? "text-on-light" : "text-fg")}>
            {busy && <Spinner />}
            <span className="truncate">
              {job.phase === "paused"
                ? "Paused"
                : job.phase === "pausing"
                  ? "Pausing after the current step…"
                  : (job.message ?? "Working…")}
            </span>
            <span className="ml-auto tabular-nums">{Math.round(job.progress)}%</span>
          </div>
        </div>
      )}

      {confirmRemove ? (
        <div className={cx("flex flex-wrap items-center gap-2 rounded-xl px-3 py-2", light ? "bg-ink/10" : "bg-line/60")}>
          <span className="min-w-0 flex-1 text-sm">
            Remove this model?{" "}
            {model.engine === "ollama"
              ? "Ollama deletes it from its own store."
              : `Frees about ${formatMb(model.approx_download_mb)}.`}
          </span>
          <Button size="sm" variant="ink" disabled={job.removing} onClick={() => void job.remove().then((ok) => ok && setConfirmRemove(false))}>
            {job.removing ? "Removing…" : "Remove"}
          </Button>
          <Button size="sm" variant={light ? "light" : "outline"} onClick={() => setConfirmRemove(false)}>
            Keep
          </Button>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <span className={cx("mr-auto text-xs", muted)}>{sizeLabel(model)}</span>
          {busy && (
            <Button size="sm" variant={light ? "ink" : "outline"} icon={Pause} disabled={job.phase === "pausing"} onClick={() => void job.pause()}>
              Pause
            </Button>
          )}
          {job.phase === "paused" && (
            <Button size="sm" variant={light ? "ink" : "primary"} icon={Play} onClick={() => void job.start()}>
              Resume
            </Button>
          )}
          {job.phase === "idle" && model.status === "ready" && (
            <>
              <Button
                size="sm"
                variant={light ? "ink" : "outline"}
                icon={isDefault ? Check : Star}
                disabled={isDefault}
                onClick={() => void updateSettings({ default_model_id: model.id })}
              >
                {isDefault ? "Default" : "Use as default"}
              </Button>
              {!isCloud(model) && (
                <Button
                  size="sm"
                  variant={light ? "ink" : "ghost"}
                  icon={Trash2}
                  aria-label={`Remove ${model.name}`}
                  onClick={() => setConfirmRemove(true)}
                >
                  Remove
                </Button>
              )}
            </>
          )}
          {job.phase === "idle" && model.status !== "ready" && (
            needsLabel(model) ? (
              <Button size="sm" variant={light ? "ink" : "muted"} onClick={() => navigate("platforms")}>
                {needsLabel(model)}
              </Button>
            ) : (
              <Button
                size="sm"
                variant={light ? "ink" : "primary"}
                icon={model.status === "needs_engine" ? PackagePlus : Download}
                onClick={() => void job.start()}
              >
                {model.status === "needs_engine"
                  ? "Install engine + model"
                  : model.engine === "ollama"
                    ? "Pull"
                    : "Install"}
              </Button>
            )
          )}
        </div>
      )}
      {job.error && <p className={cx("text-xs", light ? "text-on-light" : "text-danger")}>{job.error}</p>}
    </div>
  );
}
