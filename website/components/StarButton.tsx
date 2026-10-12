import { Star } from "lucide-react";
import { formatCount } from "@/lib/github";
import { links } from "@/lib/links";
import { GitHubMark } from "./marks";

/** "Star on GitHub" with the live count; `className` sets the height to match the
 * button beside it. `shortOnPhones` shows just "GitHub" below 640px (screen readers still
 * hear "Star on GitHub"), so the header fits narrow phones. */
export function StarButton({
  stars,
  className,
  shortOnPhones = false,
}: {
  stars: number | null;
  className: string;
  shortOnPhones?: boolean;
}) {
  return (
    <a
      href={links.repo}
      className={`press flex items-center gap-2 whitespace-nowrap rounded-xl bg-ink/40 ps-[18px] pe-5 text-sm font-semibold ring-1 ring-white/25 hover:bg-ink/60 hover:ring-white/45 ${className}`}
    >
      <GitHubMark className="size-4" />
      <span>
        <span className={shortOnPhones ? "max-sm:sr-only" : undefined}>Star on </span>
        GitHub
      </span>
      {stars !== null && (
        <>
          <Star aria-hidden="true" className="size-[13px] text-sun" />
          <span className="text-tolopea-100">
            {formatCount(stars)}
            <span className="sr-only"> stars</span>
          </span>
        </>
      )}
    </a>
  );
}
