"use client";

import { useRef, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { reveal } from "@/lib/reveal";
import { ShaderCanvas } from "./shader/ShaderCanvas";
import beam from "./shader/glsl/beam";

type Segment = { text: string } | { slip: string };

interface Read {
  model: string;
  /** The model's name on the "Set … as default" button. */
  short: string;
  segments: Segment[];
  result: string;
  exact?: boolean;
}

// Each model's read of the highlighted invoice line; slips are the characters it got wrong.
const READS: Read[] = [
  {
    model: "PaddleOCR-VL 0.9B",
    short: "PaddleOCR-VL",
    segments: [{ text: "Total due $1,284.00 · Ref INV-0312" }],
    result: "Exact",
    exact: true,
  },
  {
    model: "PaddleOCR Mobile",
    short: "PaddleOCR Mobile",
    segments: [{ text: "Total due $1,284.00 · Ref INV-" }, { slip: "O" }, { text: "312" }],
    result: "1 slip",
  },
  {
    model: "MiniCPM-V 2.6",
    short: "MiniCPM-V",
    segments: [{ text: "Total due $1,284.00 · Ref INV" }, { slip: "␣" }, { text: "0312" }],
    result: "1 slip",
  },
  {
    model: "Tesseract 5",
    short: "Tesseract",
    segments: [{ text: "Tota" }, { slip: "1" }, { text: " due $1,2" }, { slip: "B" }, { text: "4.00 · Ref INV-0312" }],
    result: "2 slips",
  },
];

const DOC_LINES = [210, 248, 170, 248, 130];
const DOC_LINES_END = [190, 110, 220];

function SourcePage() {
  return (
    <div
      aria-hidden="true"
      className="relative flex w-full max-w-[300px] shrink-0 flex-col items-start gap-[13px] overflow-hidden rounded-[14px] bg-[linear-gradient(180deg,#ffffff_0%,#eceaff_100%)] p-[26px] shadow-[0_20px_50px_#4318ff59]"
    >
      <p className="text-[10px] font-semibold tracking-[1.2px] text-dim">INVOICE</p>
      <p className="font-heading text-xl font-bold text-ink">Northwind Supply Co.</p>
      {DOC_LINES.map((w, i) => (
        <span key={i} className="block h-1.5 max-w-full rounded-full bg-[#d6d2ee]" style={{ width: w }} />
      ))}
      <div className="flex w-full flex-col gap-1 rounded-lg border-[1.5px] border-tolopea-500 bg-tolopea-500/[0.12] px-3 py-2.5 font-mono text-[13px] font-semibold text-ink">
        <span>Total due $1,284.00</span>
        <span>Ref INV-0312</span>
      </div>
      {DOC_LINES_END.map((w, i) => (
        <span key={i} className="block h-1.5 max-w-full rounded-full bg-[#d6d2ee]" style={{ width: w }} />
      ))}
      <ShaderCanvas source={beam} className="pointer-events-none absolute inset-0 z-10 size-full" />
    </div>
  );
}

export function Compare() {
  const [selected, setSelected] = useState(0);
  const [defaultModel, setDefaultModel] = useState<number | null>(null);
  const inputs = useRef<(HTMLInputElement | null)[]>([]);

  const select = (index: number, focus = false) => {
    const next = (index + READS.length) % READS.length;
    setSelected(next);
    if (focus) inputs.current[next]?.focus();
  };

  const chosen = READS[selected];
  const isDefault = defaultModel === selected;

  return (
    <section id="compare" aria-labelledby="compare-title" className="scroll-mt-10 px-4 pt-[88px] sm:px-10">
      <div className="mx-auto flex max-w-[1080px] flex-col items-center gap-3.5">
        <h2
          {...reveal()}
          id="compare-title"
          className="text-fade font-heading text-[40px] leading-tight font-normal tracking-[-0.6px]"
        >
          Compare
        </h2>
        <p {...reveal(100)} className="text-center text-sm leading-[21px] text-dim">
          See every model&apos;s read of the same line
          <br />
          before you pick a default.
        </p>

        <div {...reveal(200)} className="w-full pt-[34px]">
          {/* Side by side only from 1096px: narrower, the reads would wrap mid-token. */}
          <div className="flex flex-col items-center gap-11 rounded-3xl bg-[#0a0718] p-5 ring-1 ring-white/[0.14] sm:p-9 min-[1096px]:flex-row">
            <SourcePage />

            <div className="flex w-full min-w-0 flex-1 flex-col">
              <div className="flex items-center justify-between gap-4 pb-4">
                <p id="compare-position" className="text-xs text-dim">
                  Line 7 of 42 · invoice-0312.pdf
                  <span className="sr-only">. Correct text: Total due $1,284.00 · Ref INV-0312</span>
                </p>
                <div className="flex gap-1.5">
                  <button
                    type="button"
                    aria-label="Previous model"
                    onClick={() => select(selected - 1, true)}
                    className="press grid size-7 place-items-center rounded-full ring-1 ring-white/[0.18] hover:bg-white/[0.06] hover:ring-white/40"
                  >
                    <ChevronLeft aria-hidden="true" className="size-3.5" />
                  </button>
                  <button
                    type="button"
                    aria-label="Next model"
                    onClick={() => select(selected + 1, true)}
                    className="press grid size-7 place-items-center rounded-full ring-1 ring-white/[0.18] hover:bg-white/[0.06] hover:ring-white/40"
                  >
                    <ChevronRight aria-hidden="true" className="size-3.5" />
                  </button>
                </div>
              </div>

              <div role="radiogroup" aria-labelledby="compare-title compare-position">
                {READS.map((read, i) => {
                  const active = i === selected;
                  return (
                    <label
                      key={read.model}
                      className={`grid cursor-pointer grid-cols-[1fr_auto] items-center gap-x-4 gap-y-2 border px-3.5 py-[18px] transition-[background-color,border-color,border-radius] duration-150 ease-[cubic-bezier(0.2,0,0,1)] has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-[-1px] has-[:focus-visible]:outline-white md:flex md:gap-4 ${
                        active
                          ? "rounded-xl border-tolopea-400 bg-tolopea-500/15"
                          : "rounded-none border-transparent border-b-white/[0.12] hover:bg-white/[0.04]"
                      }`}
                    >
                      <input
                        ref={(el) => {
                          inputs.current[i] = el;
                        }}
                        type="radio"
                        name="compare-read"
                        className="sr-only"
                        checked={active}
                        onChange={() => select(i)}
                      />
                      <span className="text-sm font-semibold md:w-[140px] md:shrink-0">{read.model}</span>
                      <span className="order-last col-span-2 block font-mono text-[13px] whitespace-pre-wrap text-mist md:order-none md:flex-1">
                        {read.segments.map((segment, j) =>
                          "slip" in segment ? (
                            <mark
                              key={j}
                              className="rounded bg-[#ff383c]/25 text-[#ffb3b5] ring-1 ring-[#ff6b6e]"
                            >
                              <span aria-hidden="true">{segment.slip}</span>
                              <span className="sr-only">{segment.slip === "␣" ? " (misread as a space)" : " (misread)"}</span>
                            </mark>
                          ) : (
                            <span key={j}>{segment.text}</span>
                          ),
                        )}
                      </span>
                      <span
                        className={`justify-self-end rounded-full px-2.5 py-1 text-xs font-semibold whitespace-nowrap ${
                          read.exact ? "bg-[#17c964]/15 text-[#5fe39a]" : "bg-[#ff383c]/15 text-[#ff9a9c]"
                        }`}
                      >
                        {read.result}
                      </span>
                    </label>
                  );
                })}
              </div>

              <div className="flex flex-wrap items-center justify-between gap-4 pt-5">
                <p className="text-xs text-dim">4 models · 42 lines compared</p>
                <button
                  type="button"
                  onClick={() => setDefaultModel(selected)}
                  aria-pressed={isDefault}
                  className="press rounded-xl bg-white px-4 py-2.5 text-[13px] font-semibold text-ink hover:bg-tolopea-100"
                >
                  {isDefault ? `${chosen.short} is the default` : `Set ${chosen.short} as default`}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
