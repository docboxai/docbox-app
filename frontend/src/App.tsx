import { useEffect, useState } from "react";
import { api, formatBytes } from "./lib/api";
import { AppProvider, useApp, type ViewId } from "./lib/app";
import { formatGb, plural } from "./lib/format";
import { BenchmarksView } from "./components/BenchmarksView";
import { BootGate } from "./components/BootScreen";
import { DeviceView } from "./components/DeviceView";
import { ModelsView } from "./components/ModelsView";
import { OcrView } from "./components/OcrView";
import { PlatformsView } from "./components/PlatformsView";
import { SetupView } from "./components/SetupView";
import { Frame, Hero, type HeroStat } from "./components/Shell";
import { UpdateBanner } from "./components/UpdateBanner";

const PAGES: Record<ViewId, { eyebrow: string; title: string }> = {
  setup: { eyebrow: "STEP 1 OF 3", title: "Choose an engine" },
  models: { eyebrow: "STEP 2 OF 3", title: "Your models" },
  ocr: { eyebrow: "STEP 3 OF 3", title: "Read a file" },
  bench: { eyebrow: "THE LOCAL OCR TEST BENCH", title: "Benchmarks" },
  platforms: { eyebrow: "OUTSIDE PROGRAMS", title: "Connections" },
  device: { eyebrow: "HARDWARE", title: "This device" },
};

export default function App() {
  return (
    <BootGate>
      <AppProvider>
        <Shell />
      </AppProvider>
    </BootGate>
  );
}

// The number in the hero's tooltip pill, per view.
function useHeroStat(view: ViewId): HeroStat | null {
  const { caps, revision } = useApp();
  const [modelsBytes, setModelsBytes] = useState<number | null>(null);
  const [reads, setReads] = useState<{ done: number; cloud: number } | null>(null);
  const [connected, setConnected] = useState<number | null>(null);
  const [benches, setBenches] = useState<{ runs: number; best: string | null } | null>(null);

  useEffect(() => {
    if (view === "models") {
      api.engineStorage().then((s) => setModelsBytes(s.models_bytes), () => setModelsBytes(null));
    } else if (view === "ocr") {
      api.listReads().then(
        (list) => {
          const done = list.filter((r) => r.state === "done");
          setReads({ done: done.length, cloud: done.filter((r) => r.model_id.startsWith("nvidia-nim:")).length });
        },
        () => setReads(null),
      );
    } else if (view === "bench") {
      api.listBenchmarks().then(
        (list) => {
          const done = list.find((r) => r.state === "done" && r.summary?.best_model_id);
          const best = done?.summary?.leaderboard.find((r) => r.model_id === done.summary?.best_model_id);
          setBenches({ runs: list.length, best: best?.name ?? null });
        },
        () => setBenches(null),
      );
    } else if (view === "platforms") {
      api.listPlatforms().then((list) => setConnected(list.filter((p) => p.available).length), () => setConnected(null));
    }
  }, [view, revision]);

  switch (view) {
    case "setup":
      return caps ? { value: `${formatGb(caps.ram_total_gb)} RAM`, label: `${formatGb(caps.disk_free_gb)} disk free` } : null;
    case "models":
      return modelsBytes == null ? null : { value: formatBytes(modelsBytes), label: "used by models on disk" };
    case "ocr":
      return reads == null
        ? null
        : {
            value: `${plural(reads.done, "file")} read`,
            label: reads.cloud ? `${reads.cloud} through the cloud` : "all on this computer",
          };
    case "bench":
      return benches == null
        ? null
        : { value: plural(benches.runs, "batch", "batches"), label: benches.best ? `latest best: ${benches.best}` : "every page, every model" };
    case "platforms":
      return connected == null ? null : { value: `${connected} of 2`, label: "services connected" };
    case "device":
      return caps ? { value: `${caps.cpu_physical_cores} cores`, label: `${caps.cpu_logical_cores} threads` } : null;
  }
}

function Shell() {
  const { view } = useApp();
  const page = PAGES[view];
  const stat = useHeroStat(view);

  return (
    <Frame banner={<UpdateBanner />}>
      {/* A scroll container clips anything painted outside its children: focus outlines
          (2px + 2px offset) and the selected card's ring. -m-1 p-1 gives them those 4px
          without moving the layout. */}
      <main className="-m-1 flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-1">
        <Hero eyebrow={page.eyebrow} title={page.title} stat={stat} />
        <div className="shrink-0">
          {view === "setup" && <SetupView />}
          {view === "models" && <ModelsView />}
          {view === "ocr" && <OcrView />}
          {view === "bench" && <BenchmarksView />}
          {view === "platforms" && <PlatformsView />}
          {view === "device" && <DeviceView />}
        </div>
      </main>
    </Frame>
  );
}
