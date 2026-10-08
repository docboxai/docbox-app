import { Star } from "lucide-react";
import { formatCount } from "@/lib/github";
import { links } from "@/lib/links";
import { GitHubMark } from "./marks";

/** "Star on GitHub" with the live count; `className` sets the height to match the
 * button beside it. */
export function StarButton({ stars, className }: { stars: number | null; className: string }) {
  return (
    <a
      href={links.repo}
      className={`press flex items-center gap-2 rounded-full bg-ink/40 ps-[18px] pe-5 text-sm font-semibold ring-1 ring-white/25 hover:bg-ink/60 hover:ring-white/45 ${className}`}
    >
      <GitHubMark className="size-4" />
      Star on GitHub
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
