//! Connections: the outside programs and services some engines use (Ollama, Tesseract,
//! NVIDIA NIM).

use gpui_kit::assets::IconName;
use gpui_kit::component::button::{Button, ButtonVariants};
use gpui_kit::component::input::{Input, InputEvent, InputState};
use gpui_kit::component::switch::Switch;
use gpui_kit::component::{ActiveTheme, Disableable, Icon, Sizable, StyledExt};
use gpui_kit::prelude::FluentBuilder as _;
use gpui_kit::*;

use crate::api::{PlatformStatus, SettingsUpdate};
use crate::links::NVIDIA_KEYS_PAGE;
use crate::state::{AppState, call};
use crate::ui;
use crate::views::prerequisite::PrerequisiteCard;

pub struct ConnectionsView {
    state: Entity<AppState>,
    platforms: Vec<PlatformStatus>,
    key_saved: bool,
    key_input: Entity<InputState>,
    saving_key: bool,
    clear_input: bool,
    key_error: Option<String>,
    ollama: Entity<PrerequisiteCard>,
    tesseract: Entity<PrerequisiteCard>,
    seen_revision: u64,
    _subscriptions: Vec<Subscription>,
}

impl ConnectionsView {
    pub fn new(state: Entity<AppState>, window: &mut Window, cx: &mut Context<Self>) -> Self {
        let key_input = cx.new(|cx| InputState::new(window, cx).masked(true).placeholder("NVIDIA API key"));
        let ollama = cx.new(|cx| PrerequisiteCard::new("ollama", &state, cx));
        let tesseract = cx.new(|cx| PrerequisiteCard::new("tesseract", &state, cx));
        let subscriptions = vec![
            // A setting (the cloud switch), a started Ollama or a saved key bumps the revision.
            cx.observe(&state, |this: &mut Self, state, cx| {
                if state.read(cx).revision != this.seen_revision {
                    this.refresh(cx);
                }
                cx.notify();
            }),
            cx.subscribe(&key_input, |this: &mut Self, _, event: &InputEvent, cx| match event {
                InputEvent::PressEnter { .. } => this.save_key(cx),
                InputEvent::Change => cx.notify(),
                _ => {}
            }),
        ];
        let mut this = Self {
            seen_revision: state.read(cx).revision,
            state,
            platforms: Vec::new(),
            key_saved: false,
            key_input,
            saving_key: false,
            clear_input: false,
            key_error: None,
            ollama,
            tesseract,
            _subscriptions: subscriptions,
        };
        this.refresh(cx);
        this
    }

    fn refresh(&mut self, cx: &mut Context<Self>) {
        self.seen_revision = self.state.read(cx).revision;
        let api = self.state.read(cx).api.clone();
        call(
            cx,
            api,
            |api| Ok((api.list_platforms()?, api.nvidia_api_key_status()?)),
            |this, result, _| {
                // An unreachable backend is reported by the other views; keep this one quiet.
                if let Ok((list, key)) = result {
                    this.platforms = list;
                    this.key_saved = key.configured;
                }
            },
        )
        .detach();
    }

    fn save_key(&mut self, cx: &mut Context<Self>) {
        let key = self.key_input.read(cx).value().trim().to_string();
        if key.is_empty() || self.saving_key {
            return;
        }
        self.saving_key = true;
        self.key_error = None;
        let api = self.state.read(cx).api.clone();
        call(cx, api, move |api| api.set_nvidia_api_key(&key), |this, result, cx| {
            this.saving_key = false;
            match result {
                Ok(_) => {
                    this.key_saved = true;
                    // The field is emptied at the next render, which has the window.
                    this.clear_input = true;
                    this.state.update(cx, |s, cx| s.bump(cx));
                }
                Err(err) => this.key_error = Some(err),
            }
        })
        .detach();
        cx.notify();
    }

    fn clear_key(&mut self, cx: &mut Context<Self>) {
        self.saving_key = true;
        self.key_error = None;
        let api = self.state.read(cx).api.clone();
        call(cx, api, |api| api.clear_nvidia_api_key(), |this, result, cx| {
            this.saving_key = false;
            match result {
                Ok(_) => {
                    this.key_saved = false;
                    this.state.update(cx, |s, cx| s.bump(cx));
                }
                Err(err) => this.key_error = Some(err),
            }
        })
        .detach();
    }

    fn connection(&self, title: &str, where_: &str, status: Option<&PlatformStatus>, body: impl IntoElement, cx: &App) -> Div {
        div().flex_1().min_w(px(340.)).child(ui::section(
            where_.to_string(),
            ui::card(cx)
                .flex_1()
                .gap_4()
                .p_5()
                .child(
                    div()
                        .h_flex()
                        .justify_between()
                        .gap_3()
                        .child(div().text_2xl().font_semibold().child(title.to_string()))
                        .when_some(status, |d, s| {
                            d.child(ui::fit_chip(s.available, if s.available { "Connected" } else { "Not connected" }))
                        }),
                )
                .when_some(status.and_then(|s| s.detail.clone()), |d, detail| d.child(ui::muted(detail, cx)))
                .child(body),
            cx,
        ))
    }
}

impl Render for ConnectionsView {
    fn render(&mut self, window: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        if std::mem::take(&mut self.clear_input) {
            // Saved: the key isn't shown again.
            self.key_input.update(cx, |input, cx| input.set_value("", window, cx));
        }
        let ollama = self.platforms.iter().find(|p| p.id == "ollama").cloned();
        let nvidia = self.platforms.iter().find(|p| p.id == "nvidia-nim").cloned();
        let cloud = self.state.read(cx).cloud_enabled();
        let has_settings = self.state.read(cx).settings.is_some();
        let state = self.state.clone();
        let key_empty = self.key_input.read(cx).value().trim().is_empty();

        let key_controls = if self.key_saved {
            div().child(
                Button::new("remove-key")
                    .small()
                    .outline()
                    .label("Remove API key")
                    .disabled(self.saving_key)
                    .on_click(cx.listener(|this, _, _, cx| this.clear_key(cx))),
            )
        } else {
            div()
                .v_flex()
                .gap_2()
                .child(Input::new(&self.key_input).prefix(Icon::new(IconName::KeyRound).small()).mask_toggle())
                .child(
                    div()
                        .h_flex()
                        .justify_between()
                        .gap_3()
                        .child(
                            Button::new("get-key")
                                .link()
                                .xsmall()
                                .icon(IconName::ExternalLink)
                                .label("Get a key at build.nvidia.com")
                                .on_click(|_, _, cx| cx.open_url(NVIDIA_KEYS_PAGE)),
                        )
                        .child(
                            Button::new("connect-key")
                                .small()
                                .primary()
                                .label("Connect")
                                .loading(self.saving_key)
                                .disabled(self.saving_key || key_empty)
                                .on_click(cx.listener(|this, _, _, cx| this.save_key(cx))),
                        ),
                )
        };

        let nim_body = div()
            .v_flex()
            .gap_4()
            .child(
                div()
                    .h_flex()
                    .justify_between()
                    .gap_3()
                    .px_4()
                    .py_3()
                    .rounded_md()
                    .bg(cx.theme().muted)
                    .child(
                        div()
                            .v_flex()
                            .child(div().text_sm().font_medium().child(if cloud { "Cloud engine on" } else { "Cloud engine off" }))
                            .child(ui::small_muted(
                                if cloud { "Images read with NIM models go to NVIDIA." } else { "Nothing leaves this computer." },
                                cx,
                            )),
                    )
                    .child(
                        Switch::new("connections-cloud")
                            .checked(cloud)
                            .disabled(!has_settings)
                            .accessibility_label("Cloud engine: allow NVIDIA's cloud models")
                            .on_change(move |next, _, cx| {
                                let patch = SettingsUpdate { cloud_enabled: Some(*next), ..Default::default() };
                                state.update(cx, |s, cx| s.update_settings(patch, cx));
                            }),
                    ),
            )
            .child(key_controls)
            .when_some(self.key_error.clone(), |d, err| d.child(ui::error_text(err, cx)));

        div()
            .v_flex()
            .gap_5()
            .child(div().max_w(px(720.)).child(ui::muted(
                "Some engines use a program or service from outside DocBox. Ollama and Tesseract run on this computer; NVIDIA NIM sends images to NVIDIA's cloud, and only while the cloud engine is switched on.",
                cx,
            )))
            .child(
                ui::wrap_row()
                    .gap_4()
                    .items_start()
                    .child(self.connection(
                        "Ollama",
                        "On this computer",
                        ollama.as_ref(),
                        div()
                            .v_flex()
                            .gap_3()
                            .child(ui::small_muted(
                                "Once Ollama is running, pick a model under Setup › Ollama and DocBox downloads it for you.",
                                cx,
                            ))
                            .child(self.ollama.clone()),
                        cx,
                    ))
                    .child(self.connection(
                        "Tesseract",
                        "On this computer",
                        None,
                        div()
                            .v_flex()
                            .gap_3()
                            .child(ui::small_muted("Tesseract needs its free program on this computer; DocBox handles the rest.", cx))
                            .child(self.tesseract.clone()),
                        cx,
                    ))
                    .child(self.connection("NVIDIA NIM", "In the cloud", nvidia.as_ref(), nim_body, cx)),
            )
    }
}
