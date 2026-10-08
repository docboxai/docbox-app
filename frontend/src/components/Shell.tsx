import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { Box, FileText, Gauge, Monitor, Plug, SlidersHorizontal } from "lucide-react";
import { useApp, type ViewId } from "../lib/app";
import { LogoTile } from "./Logo";
import { Switch, cx } from "./ui";

const NAV_ITEMS: { id: ViewId; label: string; icon: LucideIcon }[] = [
  { id: "setup", label: "Setup", icon: SlidersHorizontal },
  { id: "models", label: "Models", icon: Box },
  { id: "ocr", label: "Read a file", icon: FileText },
  { id: "bench", label: "Benchmarks", icon: Gauge },
  { id: "platforms", label: "Connections", icon: Plug },
  { id: "device", label: "This device", icon: Monitor },
];

function TopNav() {
  const { view, navigate } = useApp();
  return (
    <nav aria-label="Sections" className="flex items-center gap-0.5 rounded-full p-1 ring-1 ring-ink ring-inset">
      {NAV_ITEMS.map(({ id, label, icon: Icon }) => {
        const active = id === view;
        return (
          <button
            key={id}
            type="button"
            aria-current={active ? "page" : undefined}
            title={label}
            onClick={() => navigate(id)}
            className={cx(
              "flex h-[30px] items-center gap-[5px] rounded-3xl px-3 text-[13px] font-medium whitespace-nowrap transition-colors",
              active ? "bg-ink text-fg" : "text-on-light hover:bg-ink/10",
            )}
          >
            <Icon aria-hidden="true" className="h-3.5 w-3.5" />
            <span className="max-[1080px]:sr-only">{label}</span>
          </button>
        );
      })}
    </nav>
  );
}

function CloudToggle() {
  const { settings, updateSettings } = useApp();
  return (
    <div className="flex items-center gap-2.5">
      <span id="cloud-toggle-label" className="text-[13px] font-medium whitespace-nowrap text-on-light">
        Cloud engine
      </span>
      <Switch
        label="Cloud engine: allow NVIDIA's cloud models"
        checked={settings?.cloud_enabled ?? false}
        disabled={!settings}
        onChange={(next) => void updateSettings({ cloud_enabled: next })}
      />
    </div>
  );
}

// Decorative: a soft peak of bars, as drawn in the design. The real number sits in the
// tooltip pill above it.
const BAR_HEIGHTS = [
  13, 10, 10, 13, 10, 10, 13, 10, 10, 13, 10, 10, 13, 10, 10, 13, 10, 10, 14, 11, 11, 14, 12,
  13, 17, 15, 16, 21, 19, 22, 27, 27, 31, 38, 39, 43, 51, 52, 57, 65, 66, 70, 76, 76, 78, 83,
  80, 80, 81, 76, 73, 73, 66, 62, 60, 52, 48, 46, 39, 35, 34, 27, 24, 25,
];
const BAR_OPACITY = [
  0.14, 0.14, 0.15, 0.15, 0.15, 0.15, 0.15, 0.16, 0.16, 0.17, 0.17, 0.18, 0.19, 0.19, 0.2,
  0.21, 0.23, 0.24, 0.26, 0.27, 0.29, 0.31, 0.34, 0.36, 0.39, 0.42, 0.45, 0.48, 0.52, 0.55,
  0.59, 0.62, 0.66, 0.7, 0.74, 0.77, 0.81, 0.84, 0.87, 0.9, 0.92, 0.95, 0.97, 0.98, 0.99, 1,
  1, 1, 0.99, 0.98, 0.97, 0.95, 0.92, 0.9, 0.87, 0.84, 0.81, 0.77, 0.74, 0.7, 0.66, 0.62,
  0.59, 0.55,
];

export interface HeroStat {
  value: string;
  label: string;
}

function HardwareChart({ stat }: { stat: HeroStat | null }) {
  return (
    // Fixed width, and the pill grows leftward from the right edge, so a long stat never
    // moves the bars: they sit in the same place on every page.
    <div className="hidden w-[444px] shrink-0 flex-col gap-2 lg:flex">
      <div className="relative h-[23px]">
        {stat && (
          <div className="absolute right-0 bottom-0 inline-flex max-w-full items-center gap-1.5 rounded-full bg-ink px-2.5 py-1 text-[11px] whitespace-nowrap">
            <span className="shrink-0 font-semibold text-fg">{stat.value}</span>
            <span className="truncate text-fg-muted">{stat.label}</span>
          </div>
        )}
      </div>
      <div aria-hidden="true" className="flex h-[84px] items-end gap-1">
        {BAR_HEIGHTS.map((h, i) => (
          <span
            key={i}
            className="w-[3px] rounded-[2px] bg-ink"
            style={{ height: h, opacity: BAR_OPACITY[i] }}
          />
        ))}
      </div>
    </div>
  );
}

export function Hero({
  eyebrow,
  title,
  stat,
}: {
  eyebrow: string;
  title: string;
  stat: HeroStat | null;
}) {
  return (
    <header className="flex h-[300px] shrink-0 flex-col justify-between gap-8 rounded-[20px] bg-hero px-7 pt-6 pb-7 text-on-light">
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-2.5">
          <LogoTile />
          <span className="font-heading text-xl font-bold">DocBox</span>
        </div>
        <TopNav />
        <CloudToggle />
      </div>
      <div className="flex items-end justify-between gap-6">
        <div className="flex min-w-0 flex-col gap-2.5">
          <p className="text-[13px] font-medium tracking-[0.3px] text-on-light-muted">{eyebrow}</p>
          <h1 className="font-heading text-[clamp(44px,5vw,64px)] leading-none font-semibold tracking-[-1.5px]">
            {title}
          </h1>
          {stat && (
            <p className="text-[13px] text-on-light-muted lg:sr-only">
              {stat.value} {stat.label}
            </p>
          )}
        </div>
        <HardwareChart stat={stat} />
      </div>
    </header>
  );
}

export function Frame({ banner, children }: { banner?: ReactNode; children: ReactNode }) {
  return (
    <div className="flex h-screen flex-col gap-4 bg-ink p-4 text-fg">
      {banner}
      {children}
    </div>
  );
}
