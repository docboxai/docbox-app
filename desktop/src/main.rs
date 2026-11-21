// Prevents an extra console window on Windows in release builds.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod api;
mod backend;
mod choice;
#[cfg(test)]
mod contract_test;
mod format;
mod instance;
mod jobs;
mod links;
mod model_actions;
mod shell;
mod state;
mod ui;
mod update;
mod views;

use futures::StreamExt;
use gpui_kit::component::TitleBar;
use gpui_kit::*;

use crate::backend::Backend;
use crate::instance::Instance;
use crate::shell::DocBox;

fn main() {
    // First, so a second launch hands over to the running app before anything else
    // starts: two apps would run two backends and two first-run `uv sync`s on the same data.
    let data_dir = match backend::data_dir() {
        Ok(dir) => dir,
        Err(err) => {
            eprintln!("[docbox] {err}");
            std::process::exit(1);
        }
    };
    let shown = match instance::claim(&data_dir) {
        Ok(Instance::Secondary) => return,
        Ok(Instance::Primary { _lock, shown }) => Some((_lock, shown)),
        // Can't tell (an unwritable data folder): run, the backend will say what's wrong.
        Err(err) => {
            eprintln!("[docbox] couldn't check for a running DocBox: {err}");
            None
        }
    };

    let backend = Backend::default();
    // The window shows right away (on the setup screen); the backend comes up meanwhile.
    backend.start();

    gpui_kit::application().with_assets(gpui_kit::assets::AllAssets).run(move |cx| {
        gpui_kit::init(cx);
        cx.set_global(backend.clone());
        // An AppImage runs from a mount that goes away when it exits: restarting (after an
        // update, or to apply an engine switch) must start the AppImage file itself.
        if let Some(appimage) = std::env::var_os("APPIMAGE") {
            cx.set_restart_path(appimage.into());
        }
        update::check(cx);

        let options = WindowOptions {
            window_bounds: Some(WindowBounds::centered(size(px(1280.), px(820.)), cx)),
            window_min_size: Some(size(px(900.), px(600.))),
            app_id: Some(backend::APP_IDENTIFIER.into()),
            // The window draws its own title bar (gpui-kit's TitleBar), and on Linux its
            // own frame too: GNOME's Wayland gives windows none.
            window_decorations: cfg!(target_os = "linux").then_some(WindowDecorations::Client),
            titlebar: Some(TitlebarOptions { title: Some("DocBox".into()), ..TitleBar::title_bar_options() }),
            ..TitleBar::window_options()
        };
        let window_backend = backend.clone();
        let (window, _) = gpui_kit::open_window(options, cx, |window, cx| {
            let quit_backend = window_backend.clone();
            window.on_window_should_close(cx, move |_, cx| {
                quit_backend.shutdown();
                cx.quit();
                true
            });
            cx.new(|cx| DocBox::new(window_backend.clone(), cx))
        })
        .expect("failed to open the DocBox window");

        let quit_backend = backend.clone();
        cx.on_app_quit(move |_| {
            quit_backend.shutdown();
            async {}
        })
        .detach();

        // A later launch asked for this window: bring it to the front.
        if let Some((lock, mut shown)) = shown {
            cx.spawn(async move |cx| {
                let _lock = lock;
                while shown.next().await.is_some() {
                    window.update(cx, |_, window, _| window.activate_window()).ok();
                }
            })
            .detach();
        }
    });
}
