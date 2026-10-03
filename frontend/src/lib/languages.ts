// Catalog language codes (PaddleOCR-, Tesseract- and Ollama-style) to readable names.
const NAMES: Record<string, string> = {
  en: "English",
  eng: "English",
  ch: "Chinese",
  fr: "French",
  fra: "French",
  de: "German",
  es: "Spanish",
  it: "Italian",
  pt: "Portuguese",
  nl: "Dutch",
  ru: "Russian",
  uk: "Ukrainian",
  bg: "Bulgarian",
  ar: "Arabic",
  hi: "Hindi",
  mr: "Marathi",
  ko: "Korean",
  multi: "Many languages",
};

export function languageNames(codes: string[]): string {
  return codes.map((c) => NAMES[c] ?? c).join(", ");
}
