//! How numbers, names and engines are written in the interface.

/// "16 GB", "1.2 TB", "386 MB" from gigabytes.
pub fn gb(gb: f64) -> String {
    if gb >= 1000.0 {
        format!("{:.1} TB", gb / 1024.0)
    } else if gb >= 10.0 {
        format!("{} GB", gb.round() as i64)
    } else {
        format!("{gb:.1} GB")
    }
}

pub fn mb(mb: f64) -> String {
    if mb >= 1000.0 {
        format!("{:.1} GB", mb / 1024.0)
    } else {
        format!("{} MB", mb.round() as i64)
    }
}

pub fn bytes(bytes: u64) -> String {
    let b = bytes as f64;
    if b < 1e6 {
        format!("{} KB", (b / 1e3).round() as i64)
    } else if b < 1e9 {
        format!("{} MB", (b / 1e6).round() as i64)
    } else {
        format!("{:.1} GB", b / 1e9)
    }
}

pub fn seconds(seconds: f64) -> String {
    if seconds < 60.0 {
        format!("{seconds:.1} s")
    } else {
        let m = (seconds / 60.0).floor();
        format!("{} min {} s", m as i64, (seconds - m * 60.0).round() as i64)
    }
}

pub fn plural(n: usize, one: &str, many: &str) -> String {
    format!("{n} {}", if n == 1 { one } else { many })
}

/// "NVIDIA GeForce GTX 1660 Ti" -> "GTX 1660 Ti", for narrow cards.
pub fn short_gpu(name: &str) -> String {
    let mut rest = name.trim();
    for prefix in ["NVIDIA ", "AMD ", "Intel(R) ", "Intel "] {
        if rest.len() >= prefix.len() && rest[..prefix.len()].eq_ignore_ascii_case(prefix) {
            rest = rest[prefix.len()..].trim_start();
            break;
        }
    }
    for prefix in ["GeForce ", "Radeon "] {
        if rest.len() >= prefix.len() && rest[..prefix.len()].eq_ignore_ascii_case(prefix) {
            rest = rest[prefix.len()..].trim_start();
            break;
        }
    }
    rest.to_string()
}

/// The last `keep` folders of a path: the full path starts with the user's profile folder,
/// which is long and personal.
pub fn short_path(path: &str, keep: usize) -> String {
    let sep = if path.contains('\\') { '\\' } else { '/' };
    let parts: Vec<&str> = path.split(sep).filter(|p| !p.is_empty()).collect();
    if parts.len() > keep {
        format!("…{sep}{}", parts[parts.len() - keep..].join(&sep.to_string()))
    } else {
        path.to_string()
    }
}

/// Catalog language codes (PaddleOCR-, Tesseract- and Ollama-style) to readable names.
pub fn language_names(codes: &[String]) -> String {
    codes
        .iter()
        .map(|c| match c.as_str() {
            "en" | "eng" => "English",
            "ch" => "Chinese",
            "fr" | "fra" => "French",
            "de" => "German",
            "es" => "Spanish",
            "it" => "Italian",
            "pt" => "Portuguese",
            "nl" => "Dutch",
            "ru" => "Russian",
            "uk" => "Ukrainian",
            "bg" => "Bulgarian",
            "ar" => "Arabic",
            "hi" => "Hindi",
            "mr" => "Marathi",
            "ko" => "Korean",
            "multi" => "Many languages",
            other => other,
        })
        .collect::<Vec<_>>()
        .join(", ")
}

/// Display order of the engines, for Setup's engine cards and anywhere else that wants a
/// stable order.
pub const ENGINE_ORDER: [&str; 6] =
    ["paddleocr", "paddleocr-vl", "tesseract", "easyocr", "ollama", "nvidia-nim"];

pub fn engine_label(engine: &str) -> String {
    match engine {
        "paddleocr" => "PaddleOCR",
        "paddleocr-vl" => "PaddleOCR-VL",
        "tesseract" => "Tesseract",
        "easyocr" => "EasyOCR",
        "ollama" => "Ollama",
        "nvidia-nim" => "NVIDIA NIM",
        other => other,
    }
    .to_string()
}

/// A few words per engine for the Setup cards: what it's good at.
pub fn engine_blurb(engine: &str) -> &'static str {
    match engine {
        "paddleocr" => "Scans & receipts",
        "paddleocr-vl" => "Documents & tables",
        "tesseract" => "Many languages",
        "easyocr" => "Tricky fonts",
        "ollama" => "Local AI vision",
        "nvidia-nim" => "Cloud, your own key",
        _ => "",
    }
}

/// What each engine is good for, above its versions on Setup.
pub fn engine_capabilities(engine: &str) -> &'static str {
    match engine {
        "paddleocr" => {
            "The everyday choice. Reads text from scans, receipts, photos of documents and \
             screenshots. Comes in small, balanced and extra-accurate versions, plus versions \
             for other alphabets."
        }
        "paddleocr-vl" => {
            "Understands whole pages, not just lines of text: headings, paragraphs and tables \
             in the right reading order. It's big and slow, so it needs a powerful computer."
        }
        "tesseract" => {
            "A long-standing classic that reads many languages. It needs the free Tesseract \
             program on your computer; DocBox can install it for you on Windows."
        }
        "easyocr" => {
            "An alternative reader that often copes better with unusual or decorative fonts. \
             Its first setup is a larger one-time download."
        }
        "ollama" => {
            "AI models that look at the whole image and write out the text. They run through \
             Ollama, a free program on your computer, and stay fully local."
        }
        "nvidia-nim" => {
            "Powerful AI models in NVIDIA's cloud, using your own API key. This is the only \
             option where your images leave this computer."
        }
        _ => "",
    }
}

/// Practical "which one do I actually need" advice next to an engine's versions.
pub fn engine_guidance(engine: &str) -> &'static str {
    match engine {
        "paddleocr" => {
            "Start with the version marked Best for this computer. Balanced reads most \
             accurately; Mobile is smaller, for older computers. Reading French, Russian, \
             Arabic, Hindi or Korean? Pick that language's version."
        }
        "paddleocr-vl" => {
            "Only pick this if you need tables and page structure kept, and DocBox says it \
             fits this computer. For plain text, regular PaddleOCR is much faster."
        }
        "tesseract" => {
            "Pick the language of your documents. It does best on clean, printed pages; \
             PaddleOCR usually handles messy or stylish text better."
        }
        "easyocr" => "Worth a try if PaddleOCR struggles with your text, especially unusual fonts.",
        "ollama" => {
            "Granite Vision is the smallest and is made for documents. Qwen2.5-VL and \
             MiniCPM-V read messy pages better but are a few GB each. Models you already have \
             in Ollama show up here too."
        }
        "nvidia-nim" => {
            "Use this when your computer is too slow for the bigger models and you're happy to \
             send images to NVIDIA. Which models you see depends on your API key."
        }
        _ => "",
    }
}

/// The outside program an engine needs, set up from its Setup page.
pub fn engine_prerequisite(engine: &str) -> Option<&'static str> {
    match engine {
        "ollama" => Some("ollama"),
        "tesseract" => Some("tesseract"),
        _ => None,
    }
}

pub fn prerequisite_label(id: &str) -> String {
    match id {
        "ollama" => "Ollama".into(),
        "tesseract" => "Tesseract".into(),
        other => other.into(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sizes_read_as_the_design_writes_them() {
        assert_eq!(gb(16.0), "16 GB");
        assert_eq!(gb(7.54), "7.5 GB");
        assert_eq!(gb(1229.0), "1.2 TB");
        assert_eq!(mb(386.4), "386 MB");
        assert_eq!(mb(1970.0), "1.9 GB");
        assert_eq!(bytes(1_270_000_000), "1.3 GB");
        assert_eq!(bytes(52_000), "52 KB");
        assert_eq!(seconds(3.21), "3.2 s");
        assert_eq!(seconds(75.0), "1 min 15 s");
    }

    #[test]
    fn graphics_card_names_lose_the_brand() {
        assert_eq!(short_gpu("NVIDIA GeForce GTX 1660 Ti"), "GTX 1660 Ti");
        assert_eq!(short_gpu("NVIDIA RTX A2000"), "RTX A2000");
        assert_eq!(short_gpu("Apple M2"), "Apple M2");
    }

    #[test]
    fn long_paths_keep_their_last_folders() {
        assert_eq!(short_path("/home/me/Documents/DocBox", 2), "…/Documents/DocBox");
        assert_eq!(short_path("C:\\Users\\me\\Documents\\DocBox", 3), "…\\me\\Documents\\DocBox");
        assert_eq!(short_path("/data", 2), "/data");
    }
}
