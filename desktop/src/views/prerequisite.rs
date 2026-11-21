//! Guided setup for an outside program an engine needs (Ollama, Tesseract): one-click
//! install on Windows (winget, with its own UAC prompt), copyable commands elsewhere,
//! "Start" for an installed-but-stopped Ollama, and "Check again".

use std::time::Duration;

use gpui_kit::assets::IconName;
use gpui_kit::component::button::{Button, ButtonVariants};
use gpui_kit::component::spinner::Spinner;
use gpui_kit::component::{ActiveTheme, Disableable, Icon, Sizable, StyledExt};
use gpui_kit::prelude::FluentBuilder as _;
use gpui_kit::*;

use crate::api::{Api, DownloadState, PrerequisiteInfo, PrerequisiteState};
use crate::state::{AppState, call};
use crate::ui;

pub struct PrerequisiteCard {
    id: String,
    api: Api,
    state: WeakEntity<AppState>,
    info: Option<PrerequisiteInfo>,
    checking: bool,
    installing: bool,
    progress: f64,
    message: Option<String>,
    error: Option<String>,
    copied: Option<String>,
    was_ready: Option<bool>,
    _task: Option<Task<()>>,
}

impl PrerequisiteCard {
    pub fn new(id: &str, state: &Entity<AppState>, cx: &mut Context<Self>) -> Self {
        let mut this = Self {
            id: id.to_string(),
            api: state.read(cx).api.clone(),
            state: state.downgrade(),
            info: None,
            checking: false,
            installing: false,
            progress: 0.0,
            message: None,
            error: None,
            copied: None,
            was_ready: None,
            _task: None,
        };
        this.check(cx);
        this
    }

    fn check(&mut self, cx: &mut Context<Self>) {
        self.checking = true;
        let id = self.id.clone();
        call(cx, self.api.clone(), move |api| api.get_prerequisite(&id), |this, result, cx| {
            this.checking = false;
            match result {
                Ok(info) => {
                    let ready = info.state == PrerequisiteState::Ready;
                    // Only announce a change to ready (right after an install or a start), not
                    // every check: the models that need it can now be set up.
                    if ready && this.was_ready == Some(false) {
                        if let Some(state) = this.state.upgrade() {
                            state.update(cx, |s, cx| s.bump(cx));
                        }
                    }
                    this.was_ready = Some(ready);
                    this.info = Some(info);
                }
                Err(err) => this.error = Some(err),
            }
        })
        .detach();
    }

    fn install(&mut self, cx: &mut Context<Self>) {
        self.installing = true;
        self.error = None;
        self.progress = 0.0;
        let api = self.api.clone();
        let id = self.id.clone();
        self._task = Some(cx.spawn(async move |this, cx| {
            let (api2, id2) = (api.clone(), id.clone());
            let started = cx.background_spawn(async move { api2.start_prerequisite_install(&id2) }).await;
            let job_id = match started {
                Ok(started) => started.job_id,
                Err(err) => {
                    this.update(cx, |this, cx| {
                        this.error = Some(err);
                        this.installing = false;
                        this.check(cx);
                    })
                    .ok();
                    return;
                }
            };
            loop {
                let (api2, id2, job2) = (api.clone(), id.clone(), job_id.clone());
                let status = cx.background_spawn(async move { api2.prerequisite_install_status(&id2, &job2) }).await;
                let done = this
                    .update(cx, |this, cx| {
                        let done = match status {
                            Ok(s) => {
                                this.progress = s.progress_pct.unwrap_or(0.0);
                                this.message = s.message.clone();
                                if s.state == DownloadState::Error {
                                    this.error = Some(s.message.unwrap_or_else(|| "Install failed".into()));
                                }
                                s.state.finished()
                            }
                            Err(err) => {
                                this.error = Some(err);
                                true
                            }
                        };
                        if done {
                            this.installing = false;
                            this.check(cx);
                        }
                        cx.notify();
                        done
                    })
                    .unwrap_or(true);
                if done {
                    break;
                }
                cx.background_executor().timer(Duration::from_secs(1)).await;
            }
        }));
        cx.notify();
    }

    fn start(&mut self, cx: &mut Context<Self>) {
        self.error = None;
        let api = self.api.clone();
        self._task = Some(cx.spawn(async move |this, cx| {
            let result = cx.background_spawn(async move { api.start_ollama() }).await;
            if let Err(err) = result {
                this.update(cx, |this, _| this.error = Some(err)).ok();
            }
            // The server takes a moment to accept connections after launch.
            cx.background_executor().timer(Duration::from_millis(2500)).await;
            this.update(cx, |this, cx| this.check(cx)).ok();
        }));
    }

    fn copy(&mut self, command: String, cx: &mut Context<Self>) {
        cx.write_to_clipboard(ClipboardItem::new_string(command.clone()));
        self.copied = Some(command);
        cx.notify();
        self._task = Some(cx.spawn(async move |this, cx| {
            cx.background_executor().timer(Duration::from_millis(1500)).await;
            this.update(cx, |this, cx| {
                this.copied = None;
                cx.notify();
            })
            .ok();
        }));
    }
}

impl Render for PrerequisiteCard {
    fn render(&mut self, _: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        let Some(info) = self.info.clone() else {
            return ui::card(cx)
                .h_flex()
                .gap_2()
                .px_4()
                .py_3()
                .text_sm()
                .text_color(cx.theme().muted_foreground)
                .map(|d| match &self.error {
                    Some(err) => d.child(err.clone()),
                    None => d.child(Spinner::new().small()).child("Checking…"),
                })
                .into_any_element();
        };

        if info.state == PrerequisiteState::Ready {
            return ui::card(cx)
                .h_flex()
                .gap_2()
                .px_4()
                .py_3()
                .text_sm()
                .child(Icon::new(IconName::Check).small().text_color(cx.theme().success))
                .child(if info.id == "ollama" {
                    format!("{} is installed and running.", info.name)
                } else {
                    format!("{} is installed.", info.name)
                })
                .into_any_element();
        }

        let title = if info.state == PrerequisiteState::Installed {
            format!("{} isn't running", info.name)
        } else {
            format!("{} is needed", info.name)
        };

        let body = if self.installing {
            div()
                .v_flex()
                .gap_1()
                .child(ui::progress_bar(SharedString::from(format!("prereq-{}", self.id)), self.progress))
                .child(
                    div()
                        .h_flex()
                        .gap_2()
                        .text_xs()
                        .text_color(cx.theme().muted_foreground)
                        .child(Spinner::new().xsmall())
                        .child(div().truncate().child(self.message.clone().unwrap_or_else(|| "Installing…".into()))),
                )
        } else {
            let mut buttons = div().h_flex().flex_wrap().gap_2();
            if info.can_start {
                buttons = buttons.child(
                    Button::new("prereq-start")
                        .small()
                        .primary()
                        .icon(IconName::Play)
                        .label(format!("Start {}", info.name))
                        .on_click(cx.listener(|this, _, _, cx| this.start(cx))),
                );
            }
            if info.can_auto_install {
                buttons = buttons.child(
                    Button::new("prereq-install")
                        .small()
                        .primary()
                        .icon(IconName::Download)
                        .label(format!("Install {} for me", info.name))
                        .on_click(cx.listener(|this, _, _, cx| this.install(cx))),
                );
            }
            buttons = buttons.child(
                Button::new("prereq-check")
                    .small()
                    .outline()
                    .icon(IconName::RefreshCw)
                    .label("Check again")
                    .loading(self.checking)
                    .disabled(self.checking)
                    .on_click(cx.listener(|this, _, _, cx| this.check(cx))),
            );
            let mut body = div().v_flex().gap_3().child(buttons);
            if info.state == PrerequisiteState::Missing {
                let mut commands = div().v_flex().gap_1().child(ui::small_muted(
                    if info.can_auto_install { "Or run this yourself:" } else { "Run this in a terminal:" },
                    cx,
                ));
                for (i, command) in info.commands.iter().enumerate() {
                    let cmd = command.clone();
                    commands = commands.child(
                        div()
                            .h_flex()
                            .gap_2()
                            .child(
                                div()
                                    .flex_1()
                                    .min_w_0()
                                    .px_2()
                                    .py_1()
                                    .rounded_md()
                                    .bg(cx.theme().muted)
                                    .text_xs()
                                    .font_family("monospace")
                                    .truncate()
                                    .child(command.clone()),
                            )
                            .child(
                                Button::new(("prereq-copy", i))
                                    .small()
                                    .ghost()
                                    .icon(IconName::Copy)
                                    .label(if self.copied.as_deref() == Some(command.as_str()) { "Copied" } else { "Copy" })
                                    .on_click(cx.listener(move |this, _, _, cx| this.copy(cmd.clone(), cx))),
                            ),
                    );
                }
                let url = info.download_url.clone();
                commands = commands.child(
                    div().child(
                        Button::new("prereq-site")
                            .link()
                            .small()
                            .icon(IconName::ExternalLink)
                            .label("Or download it from the official site")
                            .on_click(move |_, _, cx| cx.open_url(&url)),
                    ),
                );
                body = body.child(commands);
            }
            body
        };

        ui::card(cx)
            .gap_3()
            .p_4()
            .child(
                div()
                    .v_flex()
                    .gap_1()
                    .child(
                        div()
                            .h_flex()
                            .gap_2()
                            .font_medium()
                            .child(Icon::new(IconName::Wrench).small().text_color(cx.theme().warning))
                            .child(title),
                    )
                    .child(ui::muted(info.about.clone(), cx)),
            )
            .child(body)
            .when_some(self.error.clone(), |d, err| d.child(ui::error_text(err, cx)))
            .into_any_element()
    }
}
