import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowUpRight, Check, ChevronDown, FolderOpen, Search } from "lucide-react";
import { api, formatBytes, type ModelInfo, type StorageInfo } from "../lib/api";
import { useApp } from "../lib/app";
import { ENGINE_LABELS } from "../lib/engineMeta";
import { formatGb } from "../lib/format";
import { ON_BACKEND_COMPUTER } from "../lib/host";
import { languageNames } from "../lib/languages";
import { useModelJob } from "../lib/useModelJob";
import { ModelActionCell, ModelSetupPanel, isCloud, sizeLabel } from "./ModelActions";
import { StoragePanel } from "./StoragePanel";
import { Button, Card, CardButton, Chip, IconAction, Notice, SectionLabel, Spinner, StatCard, cx } from "./ui";

// Columns drop out as the window narrows: languages first, then engine.
const ROW_GRID =
  "grid grid-cols-[minmax(0,1fr)_84px_170px_150px] lg:grid-cols-[minmax(0,1fr)_130px_90px_190px_160px] xl:grid-cols-[minmax(0,1fr)_150px_140px_110px_200px_160px]";

function FitChip({ model }: { model: ModelInfo }) {
  const ok = model.fit.fits && model.fit.notes.length === 0;
  const why = [...model.fit.reasons, ...model.fit.notes].join("; ");
  return (
    <Chip tone={ok ? "success" : "warning"} title={why || undefined}>
      {model.fit.summary}
    </Chip>
  );
}

function LibraryRow({ model, onChanged, last }: { model: ModelInfo; onChanged: () => void; last: boolean }) {
  const job = useModelJob(model, onChanged);
  const [open, setOpen] = useState(false);
  const detailId = `model-detail-${model.id.replace(/[^a-z0-9-]/gi, "-")}`;
  const cell = "flex min-w-0 items-center px-4";
  return (
    <li className={cx(!last && "border-b border-line", open && "bg-line/30")}>
      <div
        className={cx(ROW_GRID, "min-h-[54px] cursor-pointer hover:bg-line/30")}
        onClick={(e) => {
          if (!(e.target as HTMLElement).closest("button, a, input, select")) setOpen((o) => !o);
        }}
      >
        <div className={cell}>
          <button
            type="button"
            aria-expanded={open}
            aria-controls={detailId}
            onClick={() => setOpen((o) => !o)}
            className="flex min-w-0 items-center gap-2 py-3 text-left text-sm font-medium hover:text-secondary"
          >
            <ChevronDown
              aria-hidden="true"
              className={cx("h-3.5 w-3.5 shrink-0 text-fg-muted transition-transform", open && "rotate-180")}
            />
            <span className="truncate">{model.name}</span>
          </button>
        </div>
        <div className={cx(cell, "hidden text-sm text-fg-muted lg:flex")}>
          <span className="truncate">{ENGINE_LABELS[model.engine] ?? model.engine}</span>
        </div>
        <div className={cx(cell, "hidden text-sm text-fg-muted xl:flex")}>
          <span className="truncate" title={languageNames(model.languages)}>
            {languageNames(model.languages)}
          </span>
        </div>
        <div className={cx(cell, "text-sm text-fg-muted tabular-nums")}>{sizeLabel(model)}</div>
        <div className={cell}>
          <FitChip model={model} />
        </div>
        <div className={cx(cell, "justify-end")}>
          <ModelActionCell model={model} job={job} />
        </div>
      </div>
      {open && (
        <div id={detailId} className="flex flex-wrap gap-x-8 gap-y-3 px-4 pt-1 pb-4 pl-[38px]">
          <div className="flex min-w-0 flex-[1_1_320px] flex-col gap-1.5">
            <p className="max-w-[70ch] text-sm leading-relaxed text-fg-muted">{model.description}</p>
            <p className="text-[13px] text-fg-muted">
              {languageNames(model.languages)} · needs about {formatGb(model.approx_ram_mb / 1024)} RAM
              {isCloud(model) && " · runs in NVIDIA's cloud"}
            </p>
            {!model.fit.fits && <p className="text-[13px] text-warning">{model.fit.reasons.join("; ")}</p>}
          </div>
          <div className="flex-[1_1_300px]">
            <ModelSetupPanel model={model} job={job} />
          </div>
        </div>
      )}
      {!open && job.error && <p className="px-4 pb-3 pl-[38px] text-xs text-danger">{job.error}</p>}
    </li>
  );
}

function DefaultModelCard({ models }: { models: ModelInfo[] }) {
  const { settings, updateSettings } = useApp();
  const model = models.find((m) => m.id === settings?.default_model_id) ?? null;
  const suggestion = !model ? models.find((m) => m.status === "ready") : undefined;

  if (!model) {
    return (
      <Card tone="primary-muted" className="flex min-h-[140px] flex-col justify-between gap-3 px-5 pt-4 pb-[18px]">
        <div className="flex items-center justify-between">
          <Chip>No default yet</Chip>
        </div>
        <div className="flex flex-wrap items-end justify-between gap-3">
          <p className="max-w-[46ch] text-sm text-on-light-muted">
            The default is picked first whenever you read a file.{" "}
            {suggestion ? "" : "Install a model below, then choose Use as default."}
          </p>
          {suggestion && (
            <Button
              size="sm"
              variant="ink"
              icon={Check}
              onClick={() => void updateSettings({ default_model_id: suggestion.id })}
            >
              Use {suggestion.name}
            </Button>
          )}
        </div>
      </Card>
    );
  }

  const ready = model.status === "ready";
  return (
    <Card tone="primary-muted" className="flex min-h-[140px] flex-col justify-between gap-3 px-5 pt-4 pb-[18px]">
      <div className="flex items-center justify-between gap-2">
        <div className="flex flex-wrap gap-1.5">
          <Chip>{ready ? `Installed · ${sizeLabel(model)}` : "Not installed"}</Chip>
          <Chip>Used for every file</Chip>
        </div>
        <IconAction icon={Check} label="This is the default model" />
      </div>
      <div className="flex flex-col gap-1">
        <h3 className="font-heading text-[clamp(26px,2.6vw,34px)] leading-[1.1] font-semibold tracking-[-0.6px]">
          {model.name}
        </h3>
        {!ready && (
          <p className="text-sm text-on-light-muted">Install it again from the library below to read with it.</p>
        )}
      </div>
    </Card>
  );
}

export function ModelsView() {
  const { caps, navigate, revision, bump } = useApp();
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [storage, setStorage] = useState<StorageInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [query, setQuery] = useState("");
  const [engineFilter, setEngineFilter] = useState("");
  const [folderError, setFolderError] = useState<string | null>(null);
  const [folderOpened, setFolderOpened] = useState(false);

  const refresh = useCallback(async () => {
    setError(null);
    try {
      const [list, info] = await Promise.all([api.listModels(), api.engineStorage().catch(() => null)]);
      setModels(list);
      setStorage(info);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh, revision]);

  const engines = useMemo(() => Array.from(new Set(models.map((m) => m.engine))), [models]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return models.filter((m) => {
      if (engineFilter && m.engine !== engineFilter) return false;
      if (!q) return true;
      return (
        m.name.toLowerCase().includes(q) ||
        m.description.toLowerCase().includes(q) ||
        languageNames(m.languages).toLowerCase().includes(q)
      );
    });
  }, [models, query, engineFilter]);

  // The revision bump refetches this view (effect above) and the hero's numbers.
  const onChanged = bump;

  const openFolder = async () => {
    setFolderError(null);
    try {
      await api.openModelsFolder();
      setFolderOpened(true);
      setTimeout(() => setFolderOpened(false), 1800);
    } catch (err) {
      setFolderError(err instanceof Error ? err.message : String(err));
    }
  };

  const header = "flex items-center px-4 text-xs font-medium tracking-[0.3px] text-fg-muted";

  return (
    <div className="flex flex-col gap-4">
      {error && <Notice>Couldn't reach DocBox's engine: {error}</Notice>}

      <div className="flex flex-wrap items-end gap-4">
        <section aria-labelledby="default-label" className="flex min-w-0 flex-[1_1_440px] flex-col gap-2.5">
          <SectionLabel id="default-label">Default model</SectionLabel>
          <DefaultModelCard models={models} />
        </section>
        <section aria-labelledby="storage-label" className="flex min-w-0 flex-[0_1_580px] flex-col gap-2.5 max-[1180px]:flex-[1_1_440px]">
          <SectionLabel id="storage-label">Storage</SectionLabel>
          <div className="grid grid-cols-2 gap-3">
            {/* The folder opens on the computer running DocBox, so offer it only there. */}
            {ON_BACKEND_COMPUTER ? (
              <CardButton
                onClick={() => void openFolder()}
                aria-label="Models on disk: show the models folder"
                label={folderOpened ? "Opened the models folder" : "Models on disk"}
                value={storage ? formatBytes(storage.models_bytes) : "…"}
                icon={FolderOpen}
                className="min-h-[140px]"
              />
            ) : (
              <StatCard label="Models on disk" value={storage ? formatBytes(storage.models_bytes) : "…"} className="min-h-[140px]" />
            )}
            <CardButton
              onClick={() => navigate("device")}
              aria-label="Room for more: free disk space. Open This device"
              label="Room for more"
              icon={ArrowUpRight}
              value={caps ? formatGb(caps.disk_free_gb) : "…"}
              className="min-h-[140px]"
            />
          </div>
          {folderError && <p className="text-xs text-danger">{folderError}</p>}
        </section>
      </div>

      <section aria-labelledby="library-label" className="flex flex-col gap-2.5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <SectionLabel id="library-label">Model library</SectionLabel>
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex h-9 w-64 items-center gap-2 rounded-xl bg-surface px-3 ring-1 ring-line ring-inset focus-within:ring-secondary">
              <Search aria-hidden="true" className="h-4 w-4 text-fg-muted" />
              <span className="sr-only">Search models or languages</span>
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search models or languages…"
                className="w-full bg-transparent text-sm outline-none placeholder:text-fg-muted focus-visible:outline-none"
              />
            </label>
            <label className="relative">
              <span className="sr-only">Engine</span>
              <select
                value={engineFilter}
                onChange={(e) => setEngineFilter(e.target.value)}
                className="h-9 appearance-none rounded-xl bg-surface pr-9 pl-3 text-sm ring-1 ring-line ring-inset outline-none focus:ring-secondary"
              >
                <option value="">All engines</option>
                {engines.map((engine) => (
                  <option key={engine} value={engine}>
                    {ENGINE_LABELS[engine] ?? engine}
                  </option>
                ))}
              </select>
              <ChevronDown aria-hidden="true" className="pointer-events-none absolute top-2.5 right-3 h-4 w-4 text-fg-muted" />
            </label>
          </div>
        </div>

        <Card className="overflow-hidden">
          <div className={cx(ROW_GRID, "h-9 border-b border-line")} aria-hidden="true">
            <div className={header}>Model</div>
            <div className={cx(header, "hidden lg:flex")}>Engine</div>
            <div className={cx(header, "hidden xl:flex")}>Languages</div>
            <div className={header}>Size</div>
            <div className={header}>On this computer</div>
            <div className={header} />
          </div>
          {!loaded ? (
            <div className="flex justify-center py-10 text-fg-muted">
              <Spinner className="h-6 w-6" />
            </div>
          ) : filtered.length === 0 ? (
            <p className="px-4 py-8 text-center text-sm text-fg-muted">
              {models.length === 0 ? "No models to show." : "No models match your search."}
            </p>
          ) : (
            <ul aria-label="Models">
              {filtered.map((m, i) => (
                <LibraryRow key={m.id} model={m} onChanged={onChanged} last={i === filtered.length - 1} />
              ))}
            </ul>
          )}
        </Card>
      </section>

      {storage && <StoragePanel info={storage} onChanged={onChanged} />}
    </div>
  );
}
