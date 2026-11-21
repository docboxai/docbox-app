//! Web pages the app opens in the default browser. Only `https` pages ever open, through
//! [`open`]: the app's own links below, and the addresses the backend lists (a model's
//! published figures, an outside program's download page, the benchmark score sources).
//! `tests/backend/test_external_links.py` checks both.

pub const RELEASES_PAGE: &str = "https://github.com/docboxai/docbox-app/releases/latest";
pub const NVIDIA_KEYS_PAGE: &str = "https://build.nvidia.com/";

/// Whether `url` is a web page the app may open: an `https` address with a host.
pub fn is_web_page(url: &str) -> bool {
    url::Url::parse(url).is_ok_and(|u| u.scheme() == "https" && u.host_str().is_some_and(|h| !h.is_empty()))
}

/// Open a web page in the default browser; anything else (a file, another scheme) is refused.
pub fn open(cx: &gpui_kit::App, url: &str) {
    if is_web_page(url) {
        cx.open_url(url);
    } else {
        eprintln!("[docbox] not opening {url:?}: only https web pages open from DocBox");
    }
}

#[cfg(test)]
mod tests {
    use super::{NVIDIA_KEYS_PAGE, RELEASES_PAGE, is_web_page};

    #[test]
    fn only_https_web_pages_open() {
        assert!(is_web_page(RELEASES_PAGE) && is_web_page(NVIDIA_KEYS_PAGE));
        assert!(!is_web_page("http://example.com/"));
        assert!(!is_web_page("file:///etc/passwd"));
        assert!(!is_web_page("javascript:alert(1)"));
        assert!(!is_web_page("not a url"));
    }
}
