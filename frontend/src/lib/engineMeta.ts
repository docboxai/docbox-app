import type { LucideIcon } from "lucide-react";
import { ScanText, Sparkles, Type, Zap, Server, Cloud } from "lucide-react";

// Display order used by the Setup view's engine groups and as a fallback anywhere
// else that wants a stable ordering.
export const ENGINE_ORDER = [
  "paddleocr",
  "paddleocr-vl",
  "tesseract",
  "easyocr",
  "ollama",
  "nvidia-nim",
];

export const ENGINE_ICONS: Record<string, LucideIcon> = {
  paddleocr: ScanText,
  "paddleocr-vl": Sparkles,
  tesseract: Type,
  easyocr: Zap,
  ollama: Server,
  "nvidia-nim": Cloud,
};

export const ENGINE_LABELS: Record<string, string> = {
  paddleocr: "PaddleOCR",
  "paddleocr-vl": "PaddleOCR-VL",
  tesseract: "Tesseract",
  easyocr: "EasyOCR",
  ollama: "Ollama",
  "nvidia-nim": "NVIDIA NIM",
};

// One paragraph per engine "family" describing what it's actually good for — shown on
// the Setup view above the variant picker for that engine.
export const ENGINE_CAPABILITIES: Record<string, string> = {
  paddleocr:
    "The everyday choice. Reads text from scans, receipts, photos of documents and " +
    "screenshots. Comes in small, balanced and extra-accurate versions, plus versions " +
    "for other alphabets.",
  "paddleocr-vl":
    "Understands whole pages, not just lines of text: headings, paragraphs and " +
    "tables in the right reading order. It's big and slow, so it needs a powerful " +
    "computer.",
  tesseract:
    "A long-standing classic that reads many languages. It needs the free Tesseract " +
    "program on your computer; DocBox can install it for you on Windows.",
  easyocr:
    "An alternative reader that often copes better with unusual or decorative fonts. " +
    "Its first setup is a larger one-time download.",
  ollama:
    "AI models that look at the whole image and write out the text. They run through " +
    "Ollama, a free program on your computer, and stay fully local.",
  "nvidia-nim":
    "Powerful AI models in NVIDIA's cloud, using your own API key. This is the only " +
    "option where your images leave this computer.",
};

// One short, plain-language line per engine for the Setup cards.
export const ENGINE_BLURBS: Record<string, string> = {
  paddleocr: "Scans, receipts, screenshots",
  "paddleocr-vl": "Whole documents with tables",
  tesseract: "Classic, many languages",
  easyocr: "Good with tricky fonts",
  ollama: "Local AI vision models",
  "nvidia-nim": "Cloud, with your API key",
};

export const PREREQUISITE_LABELS: Record<string, string> = {
  ollama: "Ollama",
  tesseract: "Tesseract",
};

// The external program each engine needs, shown as a setup card on its detail page.
export const ENGINE_PREREQUISITE: Record<string, string> = {
  ollama: "ollama",
  tesseract: "tesseract",
};

export const RECOMMENDED_MODEL_ID = "paddleocr-mobile-en";

// Practical "which one do I actually need" advice, shown alongside the variant picker
// on an engine's detail page — distinct from ENGINE_CAPABILITIES, which just describes
// what the engine is.
export const ENGINE_GUIDANCE: Record<string, string> = {
  paddleocr:
    "Start with Mobile: it's small and fast. If results look rough, try Balanced or " +
    "High accuracy. Reading French, Russian, Arabic, Hindi or Korean? Pick that " +
    "language's version.",
  "paddleocr-vl":
    "Only pick this if you need tables and page structure kept, and DocBox says it " +
    "fits this computer. For plain text, regular PaddleOCR is much faster.",
  tesseract:
    "Pick the language of your documents. It does best on clean, printed pages; " +
    "PaddleOCR usually handles messy or stylish text better.",
  easyocr:
    "Worth a try if PaddleOCR struggles with your text, especially unusual fonts.",
  ollama:
    "Granite Vision is the smallest and is made for documents. Qwen2.5-VL and " +
    "MiniCPM-V read messy pages better but are a few GB each. Models you already " +
    "have in Ollama show up here too.",
  "nvidia-nim":
    "Use this when your computer is too slow for the bigger models and you're happy " +
    "to send images to NVIDIA. Which models you see depends on your API key.",
};
