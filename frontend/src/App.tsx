import { useEffect, useState } from "react";
import { getVersion } from "@tauri-apps/api/app";
import { Sidebar, type ViewId } from "./components/Sidebar";
import { DeviceView } from "./components/DeviceView";
import { ModelsView } from "./components/ModelsView";
import { OcrView } from "./components/OcrView";
import { PlatformsView } from "./components/PlatformsView";
import { SetupView } from "./components/SetupView";
import { BootGate } from "./components/BootScreen";
import { UpdateBanner } from "./components/UpdateBanner";
import { CaptionBand } from "./components/Poster";

const PAGES: Record<ViewId, { eyebrow: string; title: string }> = {
  setup: { eyebrow: "STEP 1", title: "Choose how DocBox reads text" },
  models: { eyebrow: "LIBRARY", title: "Every model DocBox can set up" },
  ocr: { eyebrow: "READ", title: "Read a file" },
  platforms: { eyebrow: "CONNECTIONS", title: "Outside programs and services" },
  device: { eyebrow: "THIS DEVICE", title: "What this computer can run" },
};

export default function App() {
  return (
    <BootGate>
      <Shell />
    </BootGate>
  );
}

function Shell() {
  const [view, setView] = useState<ViewId>("setup");
  const [version, setVersion] = useState<string | null>(null);
  const page = PAGES[view];

  useEffect(() => {
    if ("__TAURI_INTERNALS__" in window) void getVersion().then(setVersion);
  }, []);

  return (
    <div className="flex h-screen bg-bg text-text">
      <Sidebar active={view} onSelect={setView} />
      <main className="flex min-w-0 flex-1 flex-col">
        <UpdateBanner />
        <div className="min-h-0 flex-1 overflow-y-auto px-10 py-8">
          <header className="mb-7">
            <div className="font-mono text-xs font-bold tracking-widest text-accent">
              {page.eyebrow}
            </div>
            <h1 className="mt-1.5 text-[34px] leading-tight font-extrabold tracking-tight">
              {page.title}
            </h1>
          </header>
          {view === "device" && <DeviceView />}
          {view === "setup" && <SetupView />}
          {view === "models" && <ModelsView />}
          {view === "platforms" && <PlatformsView />}
          {view === "ocr" && <OcrView />}
        </div>
        <CaptionBand>
          <span>DOCBOX{version ? ` ${version}` : ""}</span>
          <span className="text-accent-light">EVERYTHING STAYS ON THIS COMPUTER</span>
        </CaptionBand>
      </main>
    </div>
  );
}
