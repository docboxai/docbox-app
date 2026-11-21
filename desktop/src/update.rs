//! The "a new version is out" banner. Checks GitHub's latest release once per launch and
//! links to its page; engines, models and settings live in the data folder, so an update
//! keeps them.

use gpui_kit::assets::IconName;
use gpui_kit::component::button::{Button, ButtonVariants};
use gpui_kit::component::{ActiveTheme, Icon, Sizable, StyledExt};
use gpui_kit::prelude::FluentBuilder as _;
use gpui_kit::*;

use crate::links::RELEASES_PAGE;

const LATEST_RELEASE_API: &str = "https://api.github.com/repos/docboxai/docbox-app/releases/latest";

#[derive(Default)]
struct UpdateNotice {
    version: Option<String>,
    dismissed: bool,
}

impl Global for UpdateNotice {}

/// "1.2.3" or "v1.2.3" as numbers; None for anything else.
fn parse_version(version: &str) -> Option<[u64; 3]> {
    let mut parts = version.strip_prefix('v').unwrap_or(version).split('.');
    let v = [parts.next()?.parse().ok()?, parts.next()?.parse().ok()?, parts.next()?.parse().ok()?];
    parts.next().is_none().then_some(v)
}

pub fn is_newer(latest: &str, current: &str) -> bool {
    matches!((parse_version(latest), parse_version(current)), (Some(a), Some(b)) if a > b)
}

fn latest_release() -> Option<String> {
    let client = reqwest::blocking::Client::builder()
        .user_agent(concat!("DocBox/", env!("CARGO_PKG_VERSION")))
        .timeout(std::time::Duration::from_secs(15))
        .build()
        .ok()?;
    let release: serde_json::Value = client.get(LATEST_RELEASE_API).send().ok()?.error_for_status().ok()?.json().ok()?;
    let tag = release.get("tag_name")?.as_str()?;
    is_newer(tag, env!("CARGO_PKG_VERSION")).then(|| tag.trim_start_matches('v').to_string())
}

/// Start the once-per-launch check. Offline or rate-limited: no banner.
pub fn check(cx: &mut App) {
    cx.set_global(UpdateNotice::default());
    cx.spawn(async move |cx| {
        let version = cx.background_spawn(async move { latest_release() }).await;
        if version.is_some() {
            cx.update(|cx| {
                cx.global_mut::<UpdateNotice>().version = version;
                cx.refresh_windows();
            });
        }
    })
    .detach();
}

pub fn banner(cx: &App) -> Option<AnyElement> {
    let notice = cx.try_global::<UpdateNotice>()?;
    let version = notice.version.clone().filter(|_| !notice.dismissed)?;
    Some(
        div()
            .h_flex()
            .gap_3()
            .px_4()
            .py_2()
            .rounded_lg()
            .bg(cx.theme().secondary)
            .text_sm()
            .child(Icon::new(IconName::Download).small())
            .child(div().flex_1().min_w_0().child(format!(
                "DocBox {version} is out. Your engines, models and settings are kept when you update."
            )))
            .child(
                Button::new("update-download")
                    .small()
                    .primary()
                    .label("Download")
                    .on_click(|_, _, cx| cx.open_url(RELEASES_PAGE)),
            )
            .child(
                Button::new("update-dismiss")
                    .small()
                    .ghost()
                    .icon(IconName::X)
                    .tooltip("Not now")
                    .on_click(|_, window, cx| {
                        cx.global_mut::<UpdateNotice>().dismissed = true;
                        window.refresh();
                    }),
            )
            .into_any_element(),
    )
}

#[cfg(test)]
mod tests {
    use super::is_newer;

    #[test]
    fn compares_release_versions() {
        assert!(is_newer("v0.2.0", "0.1.9"));
        assert!(is_newer("0.1.10", "0.1.9"));
        assert!(!is_newer("v0.1.1", "0.1.1"));
        assert!(!is_newer("v0.1.0", "0.1.1"));
        assert!(!is_newer("nightly", "0.1.1"));
        assert!(!is_newer("v1.0", "0.1.1"));
    }
}
