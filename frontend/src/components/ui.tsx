// Building blocks from the design's component sheet (design/docboxapp.pen), shared by
// every view: chips, round icon actions, pill buttons, the switch, cards and tabs.
import { useId, type ButtonHTMLAttributes, type ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { AlertTriangle } from "lucide-react";

function cx(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(" ");
}

export function SectionLabel({ children, id }: { children: ReactNode; id?: string }) {
  return (
    <h2 id={id} className="text-[15px] font-medium text-fg-muted">
      {children}
    </h2>
  );
}

type ChipTone = "ink" | "success" | "warning" | "danger";

const CHIP_TONES: Record<ChipTone, string> = {
  ink: "bg-ink px-[9px] py-[3px] text-[11px] font-semibold tracking-[0.04em] text-fg uppercase",
  success: "bg-success/15 px-2 py-0.5 text-xs font-medium text-success",
  warning: "bg-warning/15 px-2 py-0.5 text-xs font-medium text-warning",
  danger: "bg-danger/15 px-2 py-0.5 text-xs font-medium text-danger",
};

export function Chip({
  tone = "ink",
  title,
  children,
}: {
  tone?: ChipTone;
  title?: string;
  children: ReactNode;
}) {
  return (
    <span
      title={title}
      className={cx("inline-flex items-center gap-1 rounded-2xl whitespace-nowrap", CHIP_TONES[tone])}
    >
      {children}
    </span>
  );
}

type ActionTone = "ink" | "light" | "hero" | "primary-soft" | "secondary-soft";

const ACTION_TONES: Record<ActionTone, string> = {
  ink: "bg-ink text-fg hover:bg-ink/80",
  light: "bg-fg text-ink hover:bg-fg/85",
  hero: "bg-hero text-ink hover:bg-hero/85",
  "primary-soft": "bg-primary-soft text-ink hover:bg-primary-soft/85",
  "secondary-soft": "bg-secondary-soft text-ink hover:bg-secondary-soft/85",
};

// The 28px round action in a card's top-right corner. Always labelled: it's icon-only.
export function IconAction({
  icon: Icon,
  label,
  tone = "ink",
  spin = false,
  onClick,
  disabled,
}: {
  icon: LucideIcon;
  label: string;
  tone?: ActionTone;
  spin?: boolean;
  onClick?: () => void;
  disabled?: boolean;
}) {
  const className = cx(
    "relative flex h-7 w-7 shrink-0 items-center justify-center rounded-full transition-colors",
    // A 28px circle is small to hit; extend the target without changing the look.
    "before:absolute before:-inset-2 before:content-['']",
    ACTION_TONES[tone],
    disabled && "opacity-50",
  );
  const glyph = <Icon aria-hidden="true" className={cx("h-3.5 w-3.5", spin && "animate-spin")} />;
  if (!onClick) {
    // Without a label it's decoration inside something already labelled (a card button).
    if (!label) return <span aria-hidden="true" className={className}>{glyph}</span>;
    return (
      <span role="img" aria-label={label} title={label} className={className}>
        {glyph}
      </span>
    );
  }
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      disabled={disabled}
      className={className}
    >
      {glyph}
    </button>
  );
}

type ButtonVariant = "primary" | "ink" | "outline" | "ghost" | "muted" | "light";
type ButtonSize = "sm" | "md" | "lg";

const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  primary: "bg-primary text-fg hover:bg-primary/85",
  ink: "bg-ink text-fg hover:bg-ink/80",
  light: "bg-fg text-ink hover:bg-fg/85",
  outline: "border border-line text-fg hover:bg-line/60",
  ghost: "text-fg hover:bg-line/60",
  muted: "bg-line text-fg hover:bg-line/80",
};

const BUTTON_SIZES: Record<ButtonSize, { box: string; square: string; icon: string }> = {
  sm: { box: "h-8 gap-[5px] px-3 text-[13px]", square: "h-8 w-8", icon: "h-3.5 w-3.5" },
  md: { box: "h-9 gap-2 px-4 text-sm", square: "h-9 w-9", icon: "h-4 w-4" },
  lg: { box: "h-10 gap-2 px-5 text-base", square: "h-10 w-10", icon: "h-[18px] w-[18px]" },
};

export function Button({
  variant = "primary",
  size = "md",
  icon: Icon,
  iconClassName,
  className,
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: LucideIcon;
  iconClassName?: string;
}) {
  const s = BUTTON_SIZES[size];
  // Icon-only buttons are square; they must carry an aria-label.
  const square = Icon !== undefined && (children === undefined || children === null);
  return (
    <button
      type="button"
      {...rest}
      className={cx(
        "inline-flex shrink-0 items-center justify-center rounded-3xl font-medium whitespace-nowrap transition-colors disabled:pointer-events-none disabled:opacity-50",
        square ? s.square : s.box,
        BUTTON_VARIANTS[variant],
        className,
      )}
    >
      {Icon && <Icon aria-hidden="true" className={cx("shrink-0", s.icon, iconClassName)} />}
      {children}
    </button>
  );
}

export function Switch({
  checked,
  onChange,
  label,
  disabled,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cx(
        "relative h-5 w-10 shrink-0 rounded-full transition-colors before:absolute before:-inset-2 before:content-[''] disabled:opacity-50",
        checked ? "bg-secondary" : "bg-ink",
      )}
    >
      <span
        aria-hidden="true"
        className={cx(
          "absolute top-0.5 h-4 w-[18px] rounded-full shadow-[0_1px_3px_#0000001a] transition-[left,background-color]",
          checked ? "left-5 bg-fg" : "left-0.5 bg-fg-muted",
        )}
      />
    </button>
  );
}

export type CardTone = "surface" | "primary-soft" | "primary-muted" | "secondary-soft" | "grey";

const CARD_TONES: Record<CardTone, string> = {
  surface: "bg-surface text-fg ring-1 ring-line ring-inset",
  "primary-soft": "bg-primary-soft text-on-light",
  "primary-muted": "bg-primary-muted text-on-light",
  "secondary-soft": "bg-secondary-soft text-on-light",
  grey: "bg-grey text-on-light",
};

export function isLightTone(tone: CardTone): boolean {
  return tone !== "surface";
}

export function Card({
  tone = "surface",
  className,
  children,
  as: Tag = "div",
  ...rest
}: {
  tone?: CardTone;
  className?: string;
  children: ReactNode;
  as?: "div" | "section" | "article" | "aside" | "li";
} & Record<`aria-${string}`, string | undefined>) {
  return (
    <Tag {...rest} className={cx("rounded-2xl", CARD_TONES[tone], className)}>
      {children}
    </Tag>
  );
}

// The design's most common card: a small label and an action on top, a big value below.
export function StatCard({
  tone = "surface",
  label,
  value,
  action,
  sub,
  valueSize = "lg",
  valueTitle,
  className,
}: {
  tone?: CardTone;
  label: ReactNode;
  value: ReactNode;
  valueTitle?: string;
  action?: ReactNode;
  sub?: ReactNode;
  valueSize?: "lg" | "md" | "sm";
  className?: string;
}) {
  const light = isLightTone(tone);
  return (
    <Card
      tone={tone}
      className={cx("flex min-w-0 flex-col justify-between gap-3 px-4 pt-3.5 pb-4", className)}
    >
      <div className="flex min-h-7 items-center justify-between gap-2">
        <span className={cx("min-w-0 truncate text-[13px] font-medium", light ? "text-on-light-muted" : "text-fg-muted")}>
          {label}
        </span>
        {action}
      </div>
      <div className="flex min-w-0 flex-col gap-0.5">
        <span
          title={valueTitle}
          className={cx(
            "line-clamp-2 pb-[0.12em] font-heading leading-[1.1] font-semibold tracking-[-0.5px] break-words",
            valueSize === "lg" && "text-[30px]",
            valueSize === "md" && "text-[26px]",
            valueSize === "sm" && "text-[22px]",
          )}
        >
          {value}
        </span>
        {sub && (
          <span className={cx("truncate text-[13px]", light ? "text-on-light-muted" : "text-fg-muted")}>
            {sub}
          </span>
        )}
      </div>
    </Card>
  );
}

// A StatCard that is one button as a whole: the corner icon only hints where it leads.
// Use it whenever a card navigates, so no card mixes a body action with a different
// corner action.
export function CardButton({
  onClick,
  label,
  icon,
  iconTone = "light",
  spin,
  className,
  ...card
}: Omit<Parameters<typeof StatCard>[0], "action" | "label"> & {
  onClick: () => void;
  label: ReactNode;
  icon: LucideIcon;
  iconTone?: ActionTone;
  spin?: boolean;
  "aria-label": string;
}) {
  const { "aria-label": ariaLabel, ...rest } = card;
  return (
    <button type="button" onClick={onClick} aria-label={ariaLabel} className={cx("group flex min-w-0 text-left", className)}>
      <StatCard
        {...rest}
        label={label}
        action={<IconAction icon={icon} label="" tone={iconTone} spin={spin} />}
        className="w-full transition-[filter] group-hover:brightness-110"
      />
    </button>
  );
}

// Segmented control ("Save the text as"): native radios, so arrow keys, focus and form
// semantics come from the browser; the labels carry the look.
export function Tabs<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
  label: string;
}) {
  const name = useId();
  return (
    <fieldset className="flex min-w-0 flex-col gap-1.5">
      <legend className="mb-1.5 text-[13px] font-medium text-on-light">{label}</legend>
      <div className="flex h-10 gap-0.5 rounded-[20px] bg-ink/12 p-1">
        {options.map((o) => (
          <label
            key={o.value}
            className={cx(
              "flex min-w-0 flex-1 cursor-pointer items-center justify-center rounded-3xl px-3 text-sm font-medium whitespace-nowrap transition-colors",
              "has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-secondary has-[:focus-visible]:outline-solid",
              o.value === value ? "bg-ink text-fg" : "text-on-light hover:bg-ink/10",
            )}
          >
            <input
              type="radio"
              name={name}
              value={o.value}
              checked={o.value === value}
              onChange={() => onChange(o.value)}
              className="sr-only"
            />
            {o.label}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

export function ProgressBar({
  value,
  label,
  light = false,
}: {
  value: number;
  label: string;
  light?: boolean;
}) {
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuenow={Math.round(value)}
      aria-valuemin={0}
      aria-valuemax={100}
      className={cx("h-2 w-full overflow-hidden rounded-full", light ? "bg-ink/20" : "bg-line")}
    >
      <div
        className={cx("h-full rounded-full transition-[width] duration-500", light ? "bg-ink" : "bg-secondary")}
        style={{ width: `${Math.max(3, Math.min(100, value))}%` }}
      />
    </div>
  );
}

// The design's spinner: a 270° ring.
export function Spinner({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className={cx("h-3.5 w-3.5 shrink-0 animate-spin", className)}>
      <circle
        cx="12"
        cy="12"
        r="10"
        fill="none"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
        strokeDasharray="47 63"
      />
    </svg>
  );
}

export function Notice({ children, tone = "danger" }: { children: ReactNode; tone?: "danger" | "warning" }) {
  return (
    <div
      role="alert"
      className={cx(
        "flex items-start gap-2 rounded-xl px-4 py-3 text-sm",
        tone === "danger" ? "bg-danger/15 text-danger" : "bg-warning/15 text-warning",
      )}
    >
      <AlertTriangle aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" />
      <div className="min-w-0">{children}</div>
    </div>
  );
}

export { cx };
