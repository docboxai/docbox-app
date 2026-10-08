import { links } from "@/lib/links";
import { enter } from "@/lib/reveal";
import { HeroEmblem } from "./HeroEmblem";
import { StarButton } from "./StarButton";

export function Hero({ stars }: { stars: number | null }) {
  return (
    <section aria-labelledby="hero-title" className="px-3 sm:px-5">
      <div className="overflow-hidden rounded-b-[28px] bg-[linear-gradient(180deg,#05030f_0%,#0a0626_28%,#24128a_52%,#4318ff_72%,#7f76ff_88%,#e5e5ff_100%)] px-6 pt-20 pb-48 lg:h-[820px] lg:px-0 lg:pt-[242px] lg:pb-0">
        <div className="mx-auto flex max-w-[864px] flex-col-reverse items-center gap-10 lg:flex-row lg:justify-between lg:gap-0">
          <div className="flex w-full max-w-[400px] flex-col items-start gap-[22px]">
            <div {...enter(0)}>
              <a
                href={links.engines}
                className="group press inline-block rounded-full bg-white/[0.08] px-3 py-1.5 text-xs font-medium text-tolopea-100 ring-1 ring-white/20 hover:bg-white/[0.14] hover:ring-white/35"
              >
                PaddleOCR-VL is now supported — Learn more{" "}
                <span
                  aria-hidden="true"
                  className="inline-block transition-transform duration-150 ease-[cubic-bezier(0.2,0,0,1)] group-hover:translate-x-0.5"
                >
                  →
                </span>
              </a>
            </div>
            <h1
              {...enter(100)}
              id="hero-title"
              className="text-fade font-heading text-[clamp(38px,9vw,54px)] leading-[1.074] font-normal tracking-[-1.2px]"
            >
              Effortless
              <br />
              OCR testing for
              <br />
              your documents
            </h1>
            <p {...enter(200)} className="text-[15px] leading-[23px] text-mist">
              The local test bench that sends every page to each OCR model you have installed —
              without a single file leaving your computer.
            </p>
            <div {...enter(300)} className="flex flex-wrap items-center gap-3 pt-1.5">
              <a
                href={links.download}
                className="press rounded-full bg-white px-5 py-3 text-sm font-semibold text-ink hover:bg-tolopea-100"
              >
                Download
              </a>
              <StarButton stars={stars} className="py-3" />
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
