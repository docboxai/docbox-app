"use client";

import { useSyncExternalStore } from "react";
import { Download } from "lucide-react";
import type { Installers } from "@/lib/github";
import { links } from "@/lib/links";

type System = "windows" | "macos" | "linux";

/** The button's label when it downloads the installer itself. */
const FILE_LABELS: Record<"windows" | "macos", string> = {
  windows: "Download for Windows",
  // Only Apple Silicon Macs are supported, and a browser can't tell an Intel Mac apart.
  macos: "Download for Mac (Apple Silicon)",
};

/** Its label when it opens the releases page to pick a file there. */
const PAGE_LABELS: Record<System, string> = {
  windows: "Choose a Windows download",
  macos: "Choose a Mac download",
  linux: "Choose a Linux download",
};

/** The visitor's desktop system, from the user agent. Phones and tablets get none: DocBox
 * is a desktop app. iPadOS says it's a Mac, so a "Mac" with a touch screen is an iPad. */
function detectSystem(): System | null {
  const ua = navigator.userAgent;
  if (/Android|iPhone|iPad|iPod|CrOS/.test(ua)) return null;
  if (/Windows/.test(ua)) return "windows";
  if (/Macintosh/.test(ua)) return navigator.maxTouchPoints > 0 ? null : "macos";
  if (/Linux|X11/.test(ua)) return "linux";
  return null;
}

const noSubscription = () => () => {};

/** "Download for <system>" straight to its installer where one file fits everyone on it, with
 * "Other platforms" beside it; otherwise "Choose a <system> download", which opens the
 * releases page. The page is pre-rendered, so it first shows (and without JavaScript stays)
 * "Download DocBox". "Other platforms" only appears once the button links straight to a
 * file, so nothing beside the button moves when its label changes. */
export function DownloadButton({ installers }: { installers: Installers }) {
  const system = useSyncExternalStore(noSubscription, detectSystem, () => null);
  const fileSystem = system === "windows" || system === "macos" ? system : null;
  const installer = fileSystem ? installers[fileSystem] : undefined;
  const label = fileSystem && installer ? FILE_LABELS[fileSystem] : system ? PAGE_LABELS[system] : "Download DocBox";
  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
      <a
        href={installer ?? links.download}
        className="press flex items-center gap-2.5 rounded-xl bg-white ps-[22px] pe-6 py-3.5 text-base font-semibold text-ink hover:bg-tolopea-100"
      >
        <Download aria-hidden="true" className="size-[18px]" />
        {label}
      </a>
      {installer && (
        <a
          href={links.download}
          className="rounded-sm text-sm font-semibold text-tolopea-100 transition-[color] duration-150 ease-out hover:text-white"
        >
          Other platforms
        </a>
      )}
    </div>
  );
}
