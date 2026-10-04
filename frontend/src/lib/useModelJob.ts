import { useCallback, useEffect, useRef, useState } from "react";
import { api, type ModelInfo } from "./api";

export type JobPhase = "idle" | "running" | "pausing" | "paused";

export interface ModelJob {
  phase: JobPhase;
  progress: number;
  message: string | null;
  error: string | null;
  start: () => Promise<void>;
  pause: () => Promise<void>;
  remove: () => Promise<boolean>;
  removing: boolean;
}

const POLL_MS = 1000;

// One model's download/install job: start, follow its progress, pause, resume, remove.
// Picks up a job that was already running or paused (from the model listing), so the
// progress survives switching views.
export function useModelJob(model: ModelInfo, onChanged: () => void): ModelJob {
  const [jobId, setJobId] = useState<string | null>(model.active_job?.job_id ?? null);
  const [phase, setPhase] = useState<JobPhase>(() => {
    const state = model.active_job?.state;
    if (!state) return "idle";
    return state === "paused" ? "paused" : "running";
  });
  const [progress, setProgress] = useState(model.active_job?.progress_pct ?? 0);
  const [message, setMessage] = useState<string | null>(model.active_job?.message ?? null);
  const [error, setError] = useState<string | null>(null);
  const [removing, setRemoving] = useState(false);

  const onChangedRef = useRef(onChanged);
  onChangedRef.current = onChanged;

  // A refreshed listing may reveal a job started elsewhere (e.g. from another view).
  useEffect(() => {
    const job = model.active_job;
    if (phase !== "idle" || !job || job.job_id === jobId) return;
    setJobId(job.job_id);
    setProgress(job.progress_pct ?? 0);
    setMessage(job.message);
    setPhase(job.state === "paused" ? "paused" : "running");
  }, [model.active_job, phase, jobId]);

  const polling = jobId !== null && (phase === "running" || phase === "pausing");

  useEffect(() => {
    if (!polling || !jobId) return;
    let cancelled = false;
    void (async () => {
      while (!cancelled) {
        try {
          const s = await api.downloadStatus(model.id, jobId);
          if (cancelled) return;
          setProgress(s.progress_pct ?? 0);
          setMessage(s.state === "installing" ? `Installing engine · ${s.message ?? ""}` : s.message);
          if (s.state === "paused") {
            setPhase("paused");
            return;
          }
          if (s.state === "done" || s.state === "error") {
            if (s.state === "error") setError(s.message ?? "Setup failed");
            setPhase("idle");
            setJobId(null);
            onChangedRef.current();
            return;
          }
        } catch (err) {
          if (cancelled) return;
          setError(err instanceof Error ? err.message : String(err));
          setPhase("idle");
          setJobId(null);
          return;
        }
        await new Promise((r) => setTimeout(r, POLL_MS));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [polling, jobId, model.id]);

  const start = useCallback(async () => {
    setError(null);
    try {
      const { job_id } = await api.startDownload(model.id);
      setJobId(job_id);
      setPhase("running");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [model.id]);

  const pause = useCallback(async () => {
    if (!jobId) return;
    setPhase("pausing");
    try {
      await api.pauseDownload(model.id, jobId);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [model.id, jobId]);

  const remove = useCallback(async () => {
    setRemoving(true);
    setError(null);
    try {
      await api.deleteModel(model.id);
      setPhase("idle");
      setJobId(null);
      onChangedRef.current();
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      return false;
    } finally {
      setRemoving(false);
    }
  }, [model.id]);

  return { phase, progress, message, error, start, pause, remove, removing };
}
