import { Logo } from "./Logo";

export type ViewId = "device" | "setup" | "models" | "ocr" | "platforms";

const NAV_ITEMS: { id: ViewId; label: string }[] = [
  { id: "setup", label: "Setup" },
  { id: "models", label: "Models" },
  { id: "ocr", label: "Read a file" },
  { id: "platforms", label: "Connections" },
  { id: "device", label: "This device" },
];

export function Sidebar({
  active,
  onSelect,
}: {
  active: ViewId;
  onSelect: (view: ViewId) => void;
}) {
  return (
    <nav
      aria-label="Sections"
      className="flex w-56 shrink-0 flex-col gap-1 border-r border-border bg-panel-2 px-3 py-6"
    >
      <div className="mb-6 flex items-center gap-2.5 px-2.5">
        <Logo size={34} />
        <span className="text-xl font-extrabold tracking-tight">DocBox</span>
        <span className="ml-auto bg-pink px-1.5 py-0.5 font-mono text-[11px] font-bold text-white">
          LOCAL
        </span>
      </div>
      {NAV_ITEMS.map(({ id, label }, i) => {
        const isActive = id === active;
        return (
          <button
            key={id}
            type="button"
            aria-current={isActive ? "page" : undefined}
            onClick={() => onSelect(id)}
            className={`flex min-h-11 items-center gap-3 rounded-xl px-3.5 text-left text-[15px] transition-colors ${
              isActive
                ? "bg-ink font-bold text-white"
                : "font-medium text-text hover:bg-accent-pale"
            }`}
          >
            <span
              aria-hidden="true"
              className={`font-mono text-xs ${isActive ? "text-white/70" : "text-text-muted"}`}
            >
              {String(i + 1).padStart(2, "0")}
            </span>
            {label}
          </button>
        );
      })}
    </nav>
  );
}
