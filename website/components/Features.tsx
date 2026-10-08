import { ArrowRight } from "lucide-react";
import { links } from "@/lib/links";
import { reveal } from "@/lib/reveal";
import { BatchScene, KeepScene, RouteScene } from "./FeatureScenes";

const CARD = "overflow-hidden rounded-3xl bg-night/80 ring-1 ring-white/[0.14]";

function Index({ children }: { children: string }) {
  return <p className="font-mono text-[11px] tracking-[1px] text-tolopea-300">{children}</p>;
}

export function Features() {
  return (
    <section aria-labelledby="features-title" className="px-3 sm:px-5">
      <div className="rounded-t-[28px] bg-[linear-gradient(180deg,#e5e5ff_0%,#8f86ff_5%,#4318ff_15%,#24128a_30%,#0a0626_55%,#05030f_100%)] px-4 py-24 sm:px-10">
        <div className="mx-auto flex max-w-[1040px] flex-col gap-12">
          <header className="flex flex-col gap-8 lg:flex-row lg:items-end lg:justify-between">
            <div {...reveal()} className="flex flex-col items-start gap-4">
              <p className="rounded-full px-3 py-1.5 text-xs font-medium ring-1 ring-white/35">The local OCR test bench</p>
              <h2
                id="features-title"
                className="text-fade-soft font-heading text-[clamp(36px,7vw,48px)] leading-[1.0625] font-normal tracking-[-1px]"
              >
                Folders in.
                <br />
                Answers out.
              </h2>
            </div>
            <p {...reveal(100)} className="max-w-[380px] text-[15px] leading-[23px] text-mist">
              DocBox treats a folder as one job. Every page goes to every model you have installed, and every
              read stays on your disk.
            </p>
          </header>

          <div className="flex flex-col gap-4">
            <article {...reveal()} className={`${CARD} flex flex-col lg:h-[420px] lg:flex-row lg:items-center lg:pl-11`}>
              <div className="flex shrink-0 flex-col items-start gap-3.5 px-7 pt-9 lg:w-[360px] lg:p-0">
                <Index>01 — ROUTE</Index>
                <h3 className="font-heading text-[30px] leading-[34px] font-normal tracking-[-0.5px]">
                  One folder in,
                  <br />
                  every model reads it
                </h3>
                <p className="text-sm leading-[22px] text-muted">
                  Drop a folder and each page is sent to PaddleOCR, Tesseract and any Ollama vision model you have
                  installed. The scores come back as they finish.
                </p>
                <a
                  href={links.engines}
                  className="group mt-1.5 flex items-center gap-1.5 rounded-sm text-[13px] font-semibold"
                >
                  See how routing works
                  <ArrowRight
                    aria-hidden="true"
                    className="size-3.5 transition-transform duration-150 ease-[cubic-bezier(0.2,0,0,1)] group-hover:translate-x-1"
                  />
                </a>
              </div>
              <div className="min-w-0 flex-1">
                <RouteScene />
              </div>
            </article>

            <div className="flex flex-col gap-4 lg:flex-row">
              <article
                {...reveal(100)}
                className={`${CARD} group flex flex-1 flex-col items-start gap-7 p-8 sm:flex-row sm:items-center`}
              >
                <BatchScene />
                <div className="flex flex-1 flex-col gap-3">
                  <Index>02 — BATCH</Index>
                  <h3 className="font-heading text-2xl leading-[27px] font-normal tracking-[-0.4px]">
                    Batches that
                    <br />
                    stay organised
                  </h3>
                  <p className="text-[13px] leading-5 text-muted">
                    Each folder becomes a named batch with its page count, models and status, ready to re-run when you
                    add a model.
                  </p>
                </div>
              </article>
              <article
                {...reveal(200)}
                className={`${CARD} group flex flex-1 flex-col items-start gap-7 p-8 sm:flex-row sm:items-center`}
              >
                <KeepScene />
                <div className="flex flex-1 flex-col gap-3">
                  <Index>03 — KEEP</Index>
                  <h3 className="font-heading text-2xl leading-[27px] font-normal tracking-[-0.4px]">
                    Every read,
                    <br />
                    kept on your disk
                  </h3>
                  <p className="text-[13px] leading-5 text-muted">
                    Outputs, scores and the original pages sit together in one local library. Nothing is uploaded, so
                    nothing needs deleting later.
                  </p>
                </div>
              </article>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
