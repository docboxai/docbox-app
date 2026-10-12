"use client";

import { useSyncExternalStore } from "react";
import { Download } from "lucide-react";
import type { Installers } from "@/lib/github";
import { links } from "@/lib/links";

type System = "windows" | "macos" | "linux";

const NAMES: Record<System, string> = { windows: "Windows", macos: "macOS", linux: "Linux" };

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

/** "Download for <system>", straight to its installer where one file fits everyone on it,
 * with "Other platforms" beside it. The page is pre-rendered, so it first shows (and
 * without JavaScript stays) "Download DocBox", which opens the releases page. */
export function DownloadButton({ installers }: { installers: Installers }) {
  const system = useSyncExternalStore(noSubscription, detectSystem, () => null);
  const installer = system === "windows" || system === "macos" ? installers[system] : undefined;
  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
      <a
        href={installer ?? links.download}
        className="press flex items-center gap-2.5 rounded-xl bg-white px-6 py-3.5 text-base font-semibold text-ink hover:bg-tolopea-100"
      >
        <Download aria-hidden="true" className="size-[18px]" />
        {system ? `Download for ${NAMES[system]}` : "Download DocBox"}
      </a>
      <a
        href={links.download}
        className="rounded-sm text-sm font-semibold text-tolopea-100 transition-[color] duration-150 ease-out hover:text-white"
      >
        Other platforms
      </a>
    </div>
  );
}
