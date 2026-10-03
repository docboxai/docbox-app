import { useEffect, useState, useCallback, useRef } from "react";
import { AlertTriangle, ArrowRight, Copy, Loader2 } from "lucide-react";
import { api, type ModelInfo, type OcrResult } from "../lib/api";
import { Chevrons } from "./Poster";

export function OcrView() {
  const [models, setModels] = useState<ModelInfo[] | null>(null);
  const [modelId, setModelId] = useState<string>("");
  const [file, setFile] = useState<File | null>(null);
  const [page, setPage] = useState(1);
  const [result, setResult] = useState<OcrResult | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [copied, setCopied] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    void (async () => {
      try {
        const all = await api.listModels();
        // "ready" rather than "downloaded": a model whose engine was uninstalled, or whose
        // Ollama isn't running, has files on disk but can't run.
        const ready = all.filter((m) => m.status === "ready");
        setModels(ready);
        if (ready.length > 0) setModelId(ready[0].id);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
        setModels([]);
      }
    })();
  }, []);

  const pickFile = (f: File | null) => {
    setFile(f);
    setPage(1);
    setResult(null);
  };

  const run = useCallback(async () => {
    if (!modelId || !file) return;
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      setResult(await api.runOcr(modelId, file, page - 1));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRunning(false);
    }
  }, [modelId, file, page]);

  const copy = useCallback(async () => {
    if (!result) return;
    await navigator.clipboard.writeText(result.text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }, [result]);

  if (models === null) return <p className="text-text-muted">Loading…</p>;

  if (models.length === 0) {
    return (
      <div className="flex items-center gap-3 rounded-2xl bg-accent-pale px-5 py-4">
        <AlertTriangle className="h-5 w-5 shrink-0 text-accent" />
        No models are ready yet. Go to Setup and pick one; it takes one click.
      </div>
    );
  }

  const isPdf = file?.type === "application/pdf" || file?.name.toLowerCase().endsWith(".pdf");

  return (
    <div className="flex flex-wrap items-stretch gap-6">
      <section aria-label="Your file" className="flex flex-[1_1_340px] flex-col gap-4">
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            pickFile(e.dataTransfer.files?.[0] ?? null);
          }}
          className={`relative flex min-h-52 flex-col items-center justify-center gap-3 overflow-hidden rounded-[18px] border-2 border-dashed p-5 text-center ${
            dragging ? "border-ink bg-accent-light" : "border-accent bg-accent-pale"
          }`}
        >
          <div aria-hidden="true" className="halftone absolute -bottom-2.5 -left-2.5 h-24 w-32 opacity-45" />
          <span aria-hidden="true" className="relative flex h-14 w-14 items-center justify-center rounded-full border-[3px] border-ink">
            <svg width="24" height="24" viewBox="0 0 24 24">
              <path d="M5 5 L19 19 M19 9 V19 H9" fill="none" stroke="#0b0b0c" strokeWidth="3" />
            </svg>
          </span>
          <div className="relative text-[17px] font-bold">
            {file ? file.name : "Drop an image or PDF here"}
          </div>
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="relative min-h-11 rounded-full bg-ink px-5.5 font-bold text-white"
          >
            {file ? "Choose another file" : "Choose a file"}
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*,.pdf"
            className="hidden"
            onChange={(e) => pickFile(e.target.files?.[0] ?? null)}
          />
        </div>

        {isPdf && (
          <div className="flex items-center gap-3 rounded-[14px] border border-border py-2 pr-2 pl-4">
            <label htmlFor="ocr-page" className="flex-1 font-semibold">
              PDF page
            </label>
            <input
              id="ocr-page"
              type="number"
              min={1}
              value={page}
              onChange={(e) => setPage(Math.max(1, Number(e.target.value) || 1))}
              className="h-11 w-20 rounded-full border border-border bg-panel-2 text-center font-mono font-bold outline-none focus:border-ink"
            />
          </div>
        )}

        <div className="flex flex-col gap-1.5">
          <label htmlFor="ocr-model" className="text-sm font-bold">
            Model
          </label>
          <select
            id="ocr-model"
            value={modelId}
            onChange={(e) => setModelId(e.target.value)}
            className="min-h-12 rounded-xl border border-border bg-panel px-3.5 outline-none focus:border-ink"
          >
            {models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
          </select>
        </div>

        <button
          type="button"
          disabled={!file || running}
          onClick={() => void run()}
          className="mt-auto flex min-h-15 items-center justify-center gap-3 rounded-full bg-accent text-lg font-extrabold text-white transition-opacity disabled:opacity-40"
        >
          {running ? <Loader2 className="h-5 w-5 animate-spin" /> : null}
          {running ? "Reading…" : "Read text"}
          {!running && <ArrowRight className="h-5 w-5" strokeWidth={2.5} />}
        </button>
      </section>

      <section
        aria-label="Text found"
        className="flex min-h-[420px] min-w-0 flex-[999_1_480px] flex-col overflow-hidden rounded-[18px] border border-border"
      >
        <div className="flex flex-wrap items-center gap-3 border-b border-border bg-panel-2 px-4.5 py-3">
          <span className="font-bold">Text found</span>
          {result && (
            <span className="text-[13px] text-text-muted">
              {result.lines.length} line{result.lines.length === 1 ? "" : "s"}
            </span>
          )}
          <span className="flex-1" />
          <button
            type="button"
            onClick={() => void copy()}
            disabled={!result}
            className="flex min-h-10 items-center gap-1.5 rounded-full border border-border bg-panel px-4 text-sm font-semibold disabled:opacity-40"
          >
            <Copy className="h-3.5 w-3.5" /> {copied ? "Copied" : "Copy"}
          </button>
        </div>

        {error && (
          <div className="m-4 flex items-center gap-2 rounded-xl border border-warn/30 bg-warn-bg px-4 py-3 text-sm text-warn">
            <AlertTriangle className="h-4 w-4 shrink-0" />
            {error}
          </div>
        )}

        <div className="flex-1 overflow-y-auto bg-panel px-4.5 py-2">
          {result ? (
            result.lines.map((line, i) => (
              <div key={i} className="flex min-h-11 items-center gap-3.5 border-b border-border">
                <span className="w-6 font-mono text-xs text-text-muted">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <span className="min-w-0 flex-1 select-text">{line.text}</span>
                {line.confidence != null && (
                  <>
                    <span aria-hidden="true" className="h-1.5 w-20 rounded-full bg-accent-light">
                      <span
                        className="block h-1.5 rounded-full bg-accent-bright"
                        style={{ width: `${Math.round(line.confidence * 100)}%` }}
                      />
                    </span>
                    <span className="w-10 text-right font-mono text-xs font-bold">
                      {Math.round(line.confidence * 100)}%
                    </span>
                  </>
                )}
              </div>
            ))
          ) : (
            <p className="py-6 text-text-muted">The text DocBox finds will appear here.</p>
          )}
        </div>
        <div className="bg-ink px-4.5 py-2.5">
          <Chevrons size={14} colors={["#fff", "#afcdf4", "#fff", "#ff2e7e", "#fff", "#afcdf4", "#fff", "#afcdf4"]} />
        </div>
      </section>
    </div>
  );
}
