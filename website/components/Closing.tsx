import { Download } from "lucide-react";
import { links } from "@/lib/links";
import { reveal } from "@/lib/reveal";
import { ClosingAurora } from "./ClosingAurora";
import { StarButton } from "./StarButton";

const FOOTER_LINKS = [
  { label: "Models", href: links.engines },
  { label: "Docs", href: links.docs },
  { label: "Changelog", href: links.changelog },
  { label: "GitHub", href: links.repo },
];

export function Closing({ stars }: { stars: number | null }) {
  return (
    <section aria-labelledby="closing-title" className="px-3 pt-24 sm:px-5">
      <div className="relative isolate flex flex-col items-center gap-[22px] overflow-hidden rounded-[28px] px-6 py-24 text-center ring-1 ring-white/[0.14] sm:px-10">
        <ClosingAurora />
        <p {...reveal()} className="relative rounded-full bg-ink/40 px-3 py-1.5 text-xs font-medium ring-1 ring-white/25">
          Free · Windows, macOS &amp; Linux
        </p>
        <h2
          {...reveal(100)}
          id="closing-title"
          className="relative font-heading text-[clamp(36px,7vw,54px)] leading-[1.074] font-normal tracking-[-1.2px]"
        >
          Your documents never
          <br />
          leave your computer.
        </h2>
        <p {...reveal(200)} className="relative text-[15px] text-mist">
          Install DocBox, open a folder, and see which model reads it best.
        </p>
        <div {...reveal(300)} className="relative flex flex-wrap items-center justify-center gap-3 pt-2.5">
          <a
            href={links.download}
            className="press flex items-center gap-2 rounded-full bg-white py-[13px] ps-5 pe-[22px] text-sm font-semibold text-ink hover:bg-tolopea-100"
          >
            <Download aria-hidden="true" className="size-4" />
            Download DocBox
          </a>
          <StarButton stars={stars} className="py-[13px]" />
        </div>
      </div>
    </section>
  );
}

export function SiteFooter() {
  return (
    <footer className="flex flex-col items-center justify-between gap-4 px-8 pt-7 pb-7 sm:flex-row sm:px-10">
      <p className="text-[13px] text-dim">DocBox · The local OCR test bench</p>
      <nav aria-label="Footer">
        <ul className="flex gap-6">
          {FOOTER_LINKS.map(({ label, href }) => (
            <li key={label}>
              <a href={href} className="rounded-sm text-[13px] text-muted transition-[color] duration-150 ease-out hover:text-white">
                {label}
              </a>
            </li>
          ))}
        </ul>
      </nav>
    </footer>
  );
}
