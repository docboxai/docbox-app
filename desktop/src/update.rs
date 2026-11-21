//! Updates. Checks once per launch: a release's signed `updates.json` lets the app download,
//! verify and install the update itself (the Windows installer, the macOS app, the Linux
//! AppImage), then restart. Anywhere that can't install itself (a .deb or a run from source),
//! or when that check finds nothing usable, GitHub's latest release still shows the notice,
//! with a link to download it. Engines, models and settings live in the data folder, so an
//! update keeps them.

use std::sync::{Arc, Mutex};
use std::time::Duration;

use gpui_kit::assets::IconName;
use gpui_kit::component::button::{Button, ButtonVariants};
use gpui_kit::component::spinner::Spinner;
use gpui_kit::component::{ActiveTheme, Icon, Sizable, StyledExt};
use gpui_kit::prelude::FluentBuilder as _;
use gpui_kit::*;

use crate::backend::Backend;
use crate::links::RELEASES_PAGE;

const LATEST_RELEASE_API: &str = "https://api.github.com/repos/docboxai/docbox-app/releases/latest";
/// The release's manifest for this app's updater (the release workflow writes it). Installed
/// copies from before the native app read `latest.json` instead, in their own format.
const UPDATES_JSON: &str = "https://github.com/docboxai/docbox-app/releases/latest/download/updates.json";
/// Every installed copy back to 0.1.0 accepts only updates signed with this key.
const PUBKEY: &str = "dW50cnVzdGVkIGNvbW1lbnQ6IG1pbmlzaWduIHB1YmxpYyBrZXk6IDIyNjk3MEMzNjQwMUQ5NTAKUldSUTJRRmt3M0JwSXQvRmFpbEtXdEpXRU50SmlIdEpsZWVLMjR4MWxkZm9jMkVYd2d0LzZUME4K";

#[derive(Clone)]
enum Available {
    /// A signed update this copy installs itself.
    Install(Arc<cargo_packager_updater::Update>),
    /// Only a version to download by hand.
    Download(String),
}

#[derive(Clone, PartialEq)]
enum Phase {
    Idle,
    Downloading(u8),
    Installing,
}

#[derive(Default)]
struct UpdateNotice {
    available: Option<Available>,
    dismissed: bool,
    phase: Option<Phase>,
    error: Option<String>,
    // After a failed in-app install, Download is offered as well.
    offer_download: bool,
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

/// Whether this copy can replace itself: the Windows installer and the macOS app can, and
/// on Linux only an AppImage (a .deb's program belongs to the package manager).
fn installs_itself() -> bool {
    if cfg!(debug_assertions) {
        return false;
    }
    !cfg!(target_os = "linux") || std::env::var_os("APPIMAGE").is_some()
}

fn signed_update() -> Option<cargo_packager_updater::Update> {
    if !installs_itself() {
        return None;
    }
    let current = env!("CARGO_PKG_VERSION").parse().ok()?;
    let config = cargo_packager_updater::Config {
        endpoints: vec![UPDATES_JSON.parse().ok()?],
        pubkey: PUBKEY.into(),
        ..Default::default()
    };
    cargo_packager_updater::UpdaterBuilder::new(current, config)
        .timeout(Duration::from_secs(30))
        .build()
        .ok()?
        .check()
        .ok()
        .flatten()
}

fn latest_release() -> Option<String> {
    let client = reqwest::blocking::Client::builder()
        .user_agent(concat!("DocBox/", env!("CARGO_PKG_VERSION")))
        .timeout(Duration::from_secs(15))
        .build()
        .ok()?;
    let release: serde_json::Value = client.get(LATEST_RELEASE_API).send().ok()?.error_for_status().ok()?.json().ok()?;
    let tag = release.get("tag_name")?.as_str()?;
    is_newer(tag, env!("CARGO_PKG_VERSION")).then(|| tag.trim_start_matches('v').to_string())
}

/// Start the once-per-launch check. Offline or rate-limited: no notice.
pub fn check(cx: &mut App) {
    cx.set_global(UpdateNotice::default());
    cx.spawn(async move |cx| {
        let available = cx
            .background_spawn(async move {
                // No usable updates.json, a bad signature, offline: try the plain check.
                signed_update()
                    .map(|u| Available::Install(Arc::new(u)))
                    .or_else(|| latest_release().map(Available::Download))
            })
            .await;
        if available.is_some() {
            cx.update(|cx| {
                cx.global_mut::<UpdateNotice>().available = available;
                cx.refresh_windows();
            });
        }
    })
    .detach();
}

fn set(cx: &mut App, f: impl FnOnce(&mut UpdateNotice)) {
    f(cx.global_mut::<UpdateNotice>());
    cx.refresh_windows();
}

fn install(update: Arc<cargo_packager_updater::Update>, cx: &mut App) {
    set(cx, |n| {
        n.error = None;
        n.phase = Some(Phase::Downloading(0));
    });
    let progress = Arc::new(Mutex::new((0usize, None::<u64>)));
    let watched = progress.clone();
    let task = cx.background_spawn(async move {
        let bytes = update.download_extended(
            move |chunk, total| {
                let mut p = watched.lock().unwrap();
                p.0 += chunk;
                p.1 = total;
            },
            || {},
        );
        bytes.map(|bytes| (update, bytes))
    });
    cx.spawn(async move |cx| {
        // Show the download's progress while it runs.
        let shown = progress.clone();
        let ticker = cx.spawn(async move |cx| loop {
            cx.background_executor().timer(Duration::from_millis(250)).await;
            let (done, total) = *shown.lock().unwrap();
            if let Some(total) = total.filter(|t| *t > 0) {
                let pct = ((100 * done as u64) / total).min(100) as u8;
                cx.update(|cx| set(cx, |n| n.phase = Some(Phase::Downloading(pct))));
            }
        });
        let result = task.await;
        drop(ticker);
        cx.update(|cx| match result {
            Ok((update, bytes)) => {
                set(cx, |n| n.phase = Some(Phase::Installing));
                // Stop the backend first: on Windows the installer replaces files it holds
                // open, and the updater exits the app without the usual close handling.
                cx.global::<Backend>().shutdown();
                match update.install(bytes) {
                    Ok(()) => cx.restart(),
                    Err(err) => {
                        // The backend is stopped: start it again so the app keeps working.
                        cx.global::<Backend>().start();
                        set(cx, |n| {
                            n.error = Some(format!("Couldn't install it: {err}"));
                            n.offer_download = true;
                            n.phase = Some(Phase::Idle);
                        });
                    }
                }
            }
            Err(err) => set(cx, |n| {
                n.error = Some(format!("Couldn't download it: {err}"));
                n.offer_download = true;
                n.phase = Some(Phase::Idle);
            }),
        });
    })
    .detach();
}

pub fn banner(cx: &App) -> Option<AnyElement> {
    let notice = cx.try_global::<UpdateNotice>()?;
    if notice.dismissed {
        return None;
    }
    let available = notice.available.clone()?;
    let version = match &available {
        Available::Install(u) => u.version.clone(),
        Available::Download(v) => v.clone(),
    };
    let phase = notice.phase.clone().unwrap_or(Phase::Idle);
    let mut row = div()
        .h_flex()
        .flex_wrap()
        .gap_3()
        .px_4()
        .py_2()
        .rounded_lg()
        .bg(cx.theme().secondary)
        .text_sm()
        .child(Icon::new(IconName::Download).small())
        .child(
            div()
                .flex_1()
                .min_w(px(200.))
                .child(format!("DocBox {version} is available. Your engines, models and settings are kept."))
                .when_some(notice.error.clone(), |d, e| d.child(div().text_color(cx.theme().danger).child(e))),
        );
    match phase {
        Phase::Downloading(pct) => {
            row = row.child(div().h_flex().gap_2().child(Spinner::new().small()).child(format!("Downloading {pct}%")));
        }
        Phase::Installing => {
            row = row.child(div().h_flex().gap_2().child(Spinner::new().small()).child("Installing…"));
        }
        Phase::Idle => {
            if let Available::Install(update) = &available {
                let update = update.clone();
                row = row.child(
                    Button::new("update-install")
                        .small()
                        .primary()
                        .icon(IconName::Download)
                        .label("Install & restart")
                        .on_click(move |_, _, cx| install(update.clone(), cx)),
                );
            }
            if matches!(available, Available::Download(_)) || notice.offer_download {
                let primary = matches!(available, Available::Download(_));
                row = row.child(
                    Button::new("update-download")
                        .small()
                        .map(|b| if primary { b.primary() } else { b.ghost() })
                        .label("Download")
                        .on_click(|_, _, cx| crate::links::open(cx, RELEASES_PAGE)),
                );
            }
            row = row.child(
                Button::new("update-dismiss")
                    .small()
                    .ghost()
                    .icon(IconName::X)
                    .tooltip("Not now")
                    .on_click(|_, _, cx| set(cx, |n| n.dismissed = true)),
            );
        }
    }
    Some(row.into_any_element())
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

    #[test]
    fn the_updater_key_decodes_to_a_minisign_public_key() {
        use base64::Engine as _;
        let text = base64::engine::general_purpose::STANDARD.decode(super::PUBKEY).unwrap();
        let text = String::from_utf8(text).unwrap();
        assert!(text.starts_with("untrusted comment: minisign public key"), "{text}");
    }
}
