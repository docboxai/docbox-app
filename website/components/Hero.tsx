import type { Installers } from "@/lib/github";
import { enter } from "@/lib/reveal";
import { DownloadButton } from "./DownloadButton";
import { HeroEmblem } from "./HeroEmblem";

/** The heading, one line and the download button: nothing else competes with it. The
 * header (SiteHeader) sits over its top edge, so the top padding leaves room for it.
 * A minimum height, not a fixed one, so larger text spacing never clips the button. */
export function Hero({ installers }: { installers: Installers }) {
  return (
    <section aria-labelledby="hero-title" className="px-3 sm:px-5">
      <div className="overflow-hidden rounded-b-[28px] bg-[linear-gradient(180deg,var(--color-ink)_0%,var(--color-night)_28%,var(--color-deep)_52%,var(--color-tolopea-600)_72%,var(--color-tolopea-400)_88%,var(--color-tolopea-100)_100%)] px-6 pt-28 pb-48 lg:min-h-[820px] lg:px-0 lg:pt-[242px] lg:pb-24">
        <div className="mx-auto flex max-w-[864px] flex-col items-center gap-10 lg:flex-row lg:justify-between lg:gap-0">
          <div className="flex w-full lg:max-w-[480px] flex-col items-start gap-[22px]">
            <h1
              {...enter(0)}
              id="hero-title"
              className="text-fade-soft font-heading text-[clamp(38px,9vw,54px)] leading-[1.074] font-normal tracking-[-1.2px]"
            >
              Effortless
              <br />
              OCR testing for
              <br />
              your documents
            </h1>
            <p {...enter(100)} className="text-base leading-6 text-mist">
              Test OCR models on your documents, right on your computer.
            </p>
            <div {...enter(200)} className="pt-2">
              <DownloadButton installers={installers} />
            </div>
          </div>
          <div {...enter(150)}>
            <HeroEmblem />
          </div>
        </div>
      </div>
    </section>
  );
}
