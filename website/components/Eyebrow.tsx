import type { HTMLAttributes } from "react";

/** The short label above a heading, in the design system's eyebrow style (as in the app's
 * page headers): DM Sans, semibold, uppercase and tracked. `className` sets the colour. */
export function Eyebrow({ className = "", ...rest }: HTMLAttributes<HTMLParagraphElement>) {
  return <p {...rest} className={`text-[11px] font-semibold tracking-[1.2px] uppercase ${className}`} />;
}
