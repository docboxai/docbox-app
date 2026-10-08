import type { ComponentType, SVGProps } from "react";
import { reveal } from "@/lib/reveal";
import { MiniCpmMark, OllamaMark, PaddlePaddleMark } from "./marks";

interface Engine {
  name: string;
  /** The project's official mark. Tesseract has none (its GitHub organisation shows
   * GitHub's default pattern), so it keeps the design's wordmark alone. */
  mark?: ComponentType<SVGProps<SVGSVGElement>>;
  /** Sized by eye against the 20px names: each mark has its own proportions. */
  markSize?: string;
  /** Each name is set in its own face, as in the design. */
  font: string;
}

const ENGINES: Engine[] = [
  { name: "PaddleOCR", mark: PaddlePaddleMark, markSize: "h-4 w-[26px]", font: "font-heading text-xl font-bold" },
  {
    name: "PaddleOCR-VL",
    mark: PaddlePaddleMark,
    markSize: "h-4 w-[26px]",
    font: "font-heading text-xl font-semibold",
  },
  { name: "Tesseract", font: "font-serif text-[23px] font-bold italic" },
  { name: "Ollama", mark: OllamaMark, markSize: "h-[22px] w-[18px]", font: "font-sans text-xl font-semibold" },
  { name: "MiniCPM-V", mark: MiniCpmMark, markSize: "size-5", font: "font-mono text-lg font-semibold" },
];

export function WorksWith() {
  return (
    <section aria-label="Works with" className="px-6 py-[72px]">
      <div className="mx-auto flex max-w-[880px] flex-col items-center gap-11">
        <ul className="flex w-full flex-wrap justify-center gap-x-10 gap-y-7 lg:flex-nowrap lg:justify-around lg:gap-x-0">
          {ENGINES.map(({ name, mark: Mark, markSize, font }, i) => (
            <li key={name} {...reveal(i * 60)} className="flex justify-center">
              <span className="flex items-center gap-2 text-white transition-[translate,color] duration-150 ease-out hover:-translate-y-0.5 hover:text-tolopea-200">
                {Mark && <Mark className={`${markSize} shrink-0`} />}
                <span className={`${font} whitespace-nowrap`}>{name}</span>
              </span>
            </li>
          ))}
        </ul>
        <p {...reveal(300)} className="text-center text-[13px] leading-5 text-dim">
          DocBox works with the OCR engines you already use.
        </p>
      </div>
    </section>
  );
}
