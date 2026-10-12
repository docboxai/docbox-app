import Link from "next/link";
import { links } from "@/lib/links";
import { LOGO_BODY, LOGO_CORNER } from "@/lib/shapes";
import { DiscordMark } from "./marks";
import { StarButton } from "./StarButton";

/** The bar over the top of the hero: the DocBox lockup, then GitHub and Discord. It sits on
 * the hero's dark top edge and scrolls away with it. */
export function SiteHeader({ stars }: { stars: number | null }) {
  return (
    <header className="absolute inset-x-0 top-0 z-10 px-9 sm:px-11 lg:px-5">
      <div className="mx-auto flex h-20 max-w-[864px] items-center justify-between gap-3">
        <Link href="/" className="flex items-center gap-2.5 rounded-sm">
          {/* The mark as the app icon draws it: the corner sits 186.14 units across the box. */}
          <svg viewBox="0 0 279.3 298" fill="currentColor" aria-hidden="true" className="h-6 w-auto">
            <path d={LOGO_BODY} />
            <path transform="translate(186.14 0.4)" d={LOGO_CORNER} />
          </svg>
          {/* Phones show the mark alone, to leave room for both buttons. */}
          <span className="font-heading text-lg font-bold tracking-[-0.3px] max-sm:sr-only">DocBox</span>
        </Link>
        <div className="flex items-center gap-2">
          <StarButton stars={stars} className="py-2" shortOnPhones />
          <a
            href={links.discord}
            className="press flex items-center gap-2 rounded-xl bg-ink/40 ps-3.5 pe-4 py-2 text-sm font-semibold ring-1 ring-white/25 hover:bg-ink/60 hover:ring-white/45 max-sm:px-3"
          >
            <DiscordMark className="size-4" />
            <span className="max-sm:sr-only">Discord</span>
          </a>
        </div>
      </div>
    </header>
  );
}
