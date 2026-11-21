//! Setup: the recommended model, this computer at a glance, and every engine with its
//! versions.

use std::collections::BTreeMap;

use gpui_kit::assets::IconName;
use gpui_kit::component::button::{Button, ButtonVariants};
use gpui_kit::component::spinner::Spinner;
use gpui_kit::component::switch::Switch;
use gpui_kit::component::{ActiveTheme, Disableable, Icon, Sizable, StyledExt};
use gpui_kit::prelude::FluentBuilder as _;
use gpui_kit::*;

use crate::api::{ModelInfo, ModelStatus, SettingsUpdate};
use crate::format;
use crate::jobs::{JobPhase, ModelJob};
use crate::model_actions::{self, is_cloud, size_label};
use crate::state::{AppState, View, call};
use crate::ui;
use crate::views::prerequisite::PrerequisiteCard;

pub struct SetupView {
    state: Entity<AppState>,
    models: Vec<(ModelInfo, Entity<ModelJob>)>,
    error: Option<String>,
    loading: bool,
    loaded: bool,
    seen_revision: u64,
    engine: Option<String>,
    variant: Option<String>,
    prerequisite: Option<Entity<PrerequisiteCard>>,
    request: u64,
    _subscription: Subscription,
    // Redraw when any shown model's job moves on.
    _jobs: Vec<Subscription>,
}

/// The version an engine's page opens on: the recommended one, else the first that fits.
fn default_variant(variants: &[&(ModelInfo, Entity<ModelJob>)]) -> Option<String> {
    variants
        .iter()
        .find(|(m, _)| m.recommended)
        .or_else(|| variants.iter().find(|(m, _)| m.fit.fits))
        .or_else(|| variants.first())
        .map(|(m, _)| m.id.clone())
}

impl SetupView {
    pub fn new(state: Entity<AppState>, _: &mut Window, cx: &mut Context<Self>) -> Self {
        let subscription = cx.observe(&state, |this: &mut Self, state, cx| {
            if state.read(cx).revision != this.seen_revision {
                this.refresh(cx);
            }
        });
        let mut this = Self {
            seen_revision: state.read(cx).revision,
            state,
            models: Vec::new(),
            error: None,
            loading: false,
            loaded: false,
            engine: None,
            variant: None,
            prerequisite: None,
            request: 0,
            _subscription: subscription,
            _jobs: Vec::new(),
        };
        this.refresh(cx);
        this
    }

    fn refresh(&mut self, cx: &mut Context<Self>) {
        self.seen_revision = self.state.read(cx).revision;
        self.loading = true;
        self.error = None;
        // Only the latest refresh may set the list: an older one finishing later would put
        // back a listing from before a download ended, which shows it still running.
        self.request += 1;
        let request = self.request;
        let api = self.state.read(cx).api.clone();
        call(cx, api, |api| api.list_models(), move |this, result, cx| {
            if request != this.request {
                return;
            }
            this.loading = false;
            this.loaded = true;
            match result {
                Ok(list) => {
                    let state = this.state.clone();
                    this.models = list
                        .into_iter()
                        .map(|m| {
                            let job = state.update(cx, |s, cx| s.job(&m, cx));
                            (m, job)
                        })
                        .collect();
                    this._jobs = this.models.iter().map(|(_, job)| cx.observe(job, |_, _, cx| cx.notify())).collect();
                }
                Err(err) => this.error = Some(err),
            }
        })
        .detach();
    }

    fn by_engine(&self) -> BTreeMap<String, Vec<&(ModelInfo, Entity<ModelJob>)>> {
        let mut map: BTreeMap<String, Vec<_>> = BTreeMap::new();
        for engine in format::ENGINE_ORDER {
            map.insert(engine.to_string(), Vec::new());
        }
        for entry in &self.models {
            map.entry(entry.0.engine.clone()).or_default().push(entry);
        }
        map
    }

    fn open_engine(&mut self, engine: Option<String>, cx: &mut Context<Self>) {
        self.prerequisite = engine
            .as_deref()
            .and_then(format::engine_prerequisite)
            .map(|id| cx.new(|cx| PrerequisiteCard::new(id, &self.state, cx)));
        self.engine = engine;
        self.variant = None;
        cx.notify();
    }

    fn engine_card(&self, engine: &str, variants: &[&(ModelInfo, Entity<ModelJob>)], cx: &mut Context<Self>) -> impl IntoElement {
        let (label, icon, tone) = if !self.loaded {
            ("Checking…".to_string(), IconName::LoaderCircle, cx.theme().muted)
        } else if variants.iter().any(|(m, _)| m.status == ModelStatus::Ready) {
            (if engine == "nvidia-nim" { "Connected" } else { "Ready" }.to_string(), IconName::Check, cx.theme().secondary)
        } else if engine == "nvidia-nim" {
            ("Needs a key".to_string(), IconName::ArrowDownRight, cx.theme().background)
        } else if variants.iter().any(|(m, _)| m.status == ModelStatus::NeedsPrerequisite) {
            (if engine == "ollama" { "Needs Ollama" } else { "Needs setup" }.to_string(), IconName::ArrowDownRight, cx.theme().background)
        } else {
            (format::engine_blurb(engine).to_string(), IconName::Plus, cx.theme().background)
        };
        let hover = cx.theme().accent;
        let engine_id = engine.to_string();
        ui::card(cx)
            .id(SharedString::from(format!("engine-{engine}")))
            .flex_1()
            .min_w(px(170.))
            .min_h(px(132.))
            .justify_between()
            .p_4()
            .bg(tone)
            .cursor_pointer()
            .hover(move |s| s.bg(hover))
            .on_click(cx.listener(move |this, _, _, cx| this.open_engine(Some(engine_id.clone()), cx)))
            .child(
                div()
                    .h_flex()
                    .justify_between()
                    .child(ui::small_muted(label, cx))
                    .child(Icon::new(icon).small()),
            )
            .child(div().text_xl().font_semibold().child(format::engine_label(engine)))
    }

    fn recommended_card(&self, cx: &mut Context<Self>) -> AnyElement {
        let Some((model, job)) = self.models.iter().find(|(m, _)| m.recommended) else {
            let text = if !self.loaded {
                None
            } else if self.error.is_some() {
                Some("Unable to check which model suits this computer.")
            } else {
                Some("No model runs smoothly on this computer right now. Free up memory or disk space, then refresh.")
            };
            return ui::card(cx)
                .min_h(px(200.))
                .items_center()
                .justify_center()
                .bg(cx.theme().secondary)
                .map(|d| match text {
                    Some(text) => d.child(div().max_w(px(360.)).text_center().child(ui::muted(text, cx))),
                    None => d.child(Spinner::new()),
                })
                .into_any_element();
        };
        let j = job.read(cx);
        let busy = j.busy();
        let ready = model.status == ModelStatus::Ready && j.phase == JobPhase::Idle;
        let mut chips = div().h_flex().flex_wrap().gap_1().child(ui::chip("Best for this computer"));
        if busy {
            chips = chips.child(ui::chip(format!("Installing · {}%", j.progress.round() as i64)));
        }
        if j.phase == JobPhase::Paused {
            chips = chips.child(ui::chip(format!("Paused · {}%", j.progress.round() as i64)));
        }
        if ready {
            chips = chips.child(ui::chip(format!("Installed · {}", size_label(model))));
        }
        let state = self.state.clone();
        let footer = if busy || j.phase == JobPhase::Paused {
            model_actions::setup_panel(job, &self.state, false, cx).into_any_element()
        } else if ready {
            div()
                .h_flex()
                .flex_wrap()
                .justify_between()
                .gap_3()
                .child(ui::muted("Set up and ready. Next, read a file with it.", cx))
                .child(
                    Button::new("recommended-read")
                        .small()
                        .primary()
                        .icon(IconName::ArrowRight)
                        .label("Read a file")
                        .on_click(move |_, _, cx| state.update(cx, |s, cx| s.navigate(View::Read, cx))),
                )
                .into_any_element()
        } else {
            let job = job.clone();
            div()
                .h_flex()
                .flex_wrap()
                .justify_between()
                .gap_3()
                .child(div().flex_1().min_w(px(240.)).child(ui::muted(
                    format!("{} One click sets up everything it needs ({}).", model.description, size_label(model)),
                    cx,
                )))
                .child(
                    Button::new("recommended-install")
                        .small()
                        .primary()
                        .icon(IconName::Download)
                        .label("Install")
                        .on_click(move |_, _, cx| job.update(cx, |j, cx| j.start(cx))),
                )
                .when_some(j.error.clone(), |d, err| d.child(ui::error_text(err, cx)))
                .into_any_element()
        };
        ui::card(cx)
            .min_h(px(200.))
            .justify_between()
            .gap_4()
            .p_5()
            .bg(cx.theme().secondary)
            .child(chips)
            .child(div().v_flex().gap_3().child(div().text_2xl().font_semibold().child(model.name.clone())).child(footer))
            .into_any_element()
    }

    fn device_cards(&self, cx: &mut Context<Self>) -> impl IntoElement {
        let s = self.state.read(cx);
        let caps = s.caps.clone();
        let cloud = s.cloud_enabled();
        let has_settings = s.settings.is_some();
        let nim_ready = self.models.iter().any(|(m, _)| m.engine == "nvidia-nim" && m.status == ModelStatus::Ready);
        let to_device = |id: &'static str, label: &'static str, value: String, cx: &App| {
            let state = self.state.clone();
            ui::stat_button(id, label, value, IconName::ArrowUpRight, move |_, _, cx| {
                state.update(cx, |s, cx| s.navigate(View::Device, cx))
            }, cx)
            .flex_1()
            .min_w(px(160.))
        };
        let state = self.state.clone();
        div()
            .v_flex()
            .gap_3()
            .child(
                div()
                    .h_flex()
                    .gap_3()
                    .child(to_device("dev-mem", "Memory", caps.as_ref().map_or("…".into(), |c| format::gb(c.ram_total_gb)), cx))
                    .child(to_device("dev-disk", "Disk free", caps.as_ref().map_or("…".into(), |c| format::gb(c.disk_free_gb)), cx)),
            )
            .child(
                div()
                    .h_flex()
                    .gap_3()
                    .child(to_device(
                        "dev-gpu",
                        "Graphics",
                        caps.as_ref()
                            .and_then(|c| c.gpu_name.as_deref())
                            .map_or("CPU only".into(), format::short_gpu),
                        cx,
                    ))
                    .child(
                        ui::card(cx)
                            .flex_1()
                            .min_w(px(160.))
                            .gap_1()
                            .px_4()
                            .py_3()
                            .child(ui::small_muted("NVIDIA cloud engine", cx))
                            .child(
                                div()
                                    .h_flex()
                                    .justify_between()
                                    .child(div().text_xl().font_semibold().child(if !cloud {
                                        "Off"
                                    } else if nim_ready {
                                        "On"
                                    } else {
                                        "On · no key"
                                    }))
                                    .child(
                                        Switch::new("setup-cloud")
                                            .checked(cloud)
                                            .disabled(!has_settings)
                                            .accessibility_label("Cloud engine: allow NVIDIA's cloud models")
                                            .on_change(move |next, _, cx| {
                                                let patch = SettingsUpdate { cloud_enabled: Some(*next), ..Default::default() };
                                                state.update(cx, |s, cx| s.update_settings(patch, cx));
                                            }),
                                    ),
                            ),
                    ),
            )
    }

    fn render_engine(&mut self, engine: String, cx: &mut Context<Self>) -> AnyElement {
        let groups = self.by_engine();
        let variants: Vec<&(ModelInfo, Entity<ModelJob>)> = groups.get(&engine).cloned().unwrap_or_default();
        let selected_id = self
            .variant
            .clone()
            .filter(|id| variants.iter().any(|(m, _)| &m.id == id))
            .or_else(|| default_variant(&variants));
        let selected = variants.iter().find(|(m, _)| Some(&m.id) == selected_id.as_ref()).map(|(m, j)| (m.clone(), j.clone()));

        let mut page = div()
            .v_flex()
            .gap_4()
            .child(
                div().child(
                    Button::new("back")
                        .ghost()
                        .small()
                        .icon(IconName::ArrowLeft)
                        .label("All engines")
                        .on_click(cx.listener(|this, _, _, cx| this.open_engine(None, cx))),
                ),
            )
            .child(
                ui::wrap_row()
                    .child(
                        ui::card(cx)
                            .flex_1()
                            .min_w(px(360.))
                            .gap_2()
                            .p_5()
                            .child(div().text_2xl().font_semibold().child(format::engine_label(&engine)))
                            .child(ui::muted(format::engine_capabilities(&engine), cx)),
                    )
                    .child(
                        ui::card(cx)
                            .flex_1()
                            .min_w(px(300.))
                            .gap_2()
                            .p_5()
                            .bg(cx.theme().secondary)
                            .child(div().text_lg().font_semibold().child("Which one do I need?"))
                            .child(ui::muted(format::engine_guidance(&engine), cx)),
                    ),
            )
            .when_some(self.prerequisite.clone(), |d, card| d.child(card));

        if variants.is_empty() {
            let cloud = self.state.read(cx).cloud_enabled();
            let text = if engine == "nvidia-nim" {
                if cloud {
                    "Not connected. Add an API key under Connections to see models here."
                } else {
                    "The cloud engine is switched off. Switch it on, then add an API key under Connections."
                }
            } else {
                "No versions available."
            };
            let state = self.state.clone();
            page = page.child(
                ui::card(cx)
                    .h_flex()
                    .flex_wrap()
                    .justify_between()
                    .gap_3()
                    .px_5()
                    .py_4()
                    .child(ui::muted(text, cx))
                    .when(engine == "nvidia-nim", |d| {
                        d.child(
                            Button::new("open-connections")
                                .small()
                                .outline()
                                .label("Open Connections")
                                .on_click(move |_, _, cx| state.update(cx, |s, cx| s.navigate(View::Connections, cx))),
                        )
                    }),
            );
            return page.into_any_element();
        }

        let mut list = ui::card(cx).overflow_hidden();
        let row_hover = cx.theme().accent;
        let row_selected = cx.theme().muted;
        let count = variants.len();
        for (i, (m, _)) in variants.iter().enumerate() {
            let is_selected = Some(&m.id) == selected_id.as_ref();
            let ok = m.fit.fits && m.fit.notes.is_empty();
            let why = m.fit.reasons.iter().chain(m.fit.notes.iter()).cloned().collect::<Vec<_>>().join("; ");
            let id = m.id.clone();
            list = list.child(
                div()
                    .id(SharedString::from(format!("variant-{}", m.id)))
                    .h_flex()
                    .gap_3()
                    .min_h(px(56.))
                    .px_4()
                    .cursor_pointer()
                    .when(i + 1 < count, |d| d.border_b_1().border_color(cx.theme().border))
                    .when(is_selected, |d| d.bg(row_selected))
                    .hover(move |s| s.bg(row_hover))
                    .on_click(cx.listener(move |this, _, _, cx| {
                        this.variant = Some(id.clone());
                        cx.notify();
                    }))
                    .child(
                        div()
                            .v_flex()
                            .flex_1()
                            .min_w_0()
                            .child(div().text_sm().font_medium().truncate().child(m.name.clone()))
                            .child(ui::small_muted(format::language_names(&m.languages), cx).truncate()),
                    )
                    .child(
                        div()
                            .id(SharedString::from(format!("fit-{}", m.id)))
                            .when(!why.is_empty(), |d| d.tooltip(move |window, cx| gpui_kit::component::tooltip::Tooltip::new(why.clone()).build(window, cx)))
                            .child(ui::fit_chip(ok, if m.recommended { "Best for this computer".to_string() } else { m.fit.summary.clone() })),
                    )
                    .child(div().w(px(64.)).text_right().text_sm().text_color(cx.theme().muted_foreground).child(size_label(m)))
                    .child(div().w(px(16.)).when(m.status == ModelStatus::Ready, |d| {
                        d.child(Icon::new(IconName::Check).small().text_color(cx.theme().success))
                    })),
            );
        }

        let mut row = ui::wrap_row().items_start().child(div().flex_1().min_w(px(420.)).child(ui::section("Versions", list, cx)));
        if let Some((model, job)) = selected {
            let mut panel = ui::card(cx)
                .gap_3()
                .p_5()
                .bg(cx.theme().secondary)
                .child(div().text_xl().font_semibold().child(model.name.clone()))
                .child(ui::muted(model.description.clone(), cx));
            if !model.fit.fits {
                panel = panel.child(div().text_sm().font_medium().child(format!("May not fit: {}", model.fit.reasons.join("; "))));
            }
            if is_cloud(&model) {
                panel = panel.child(
                    div().text_sm().font_medium().child("Runs in NVIDIA's cloud: images you read with it leave this computer."),
                );
            }
            panel = panel.child(model_actions::setup_panel(&job, &self.state, false, cx));
            row = row.child(div().w(px(360.)).child(ui::section("Selected", panel, cx)));
        }
        page.child(row).into_any_element()
    }
}

impl Render for SetupView {
    fn render(&mut self, _: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        if let Some(engine) = self.engine.clone() {
            return self.render_engine(engine, cx);
        }
        let groups = self.by_engine();
        let mut engines = ui::wrap_row();
        for engine in format::ENGINE_ORDER {
            let variants = groups.get(engine).cloned().unwrap_or_default();
            engines = engines.child(self.engine_card(engine, &variants, cx));
        }
        let recommended = self.recommended_card(cx);
        let device = self.device_cards(cx).into_any_element();
        div()
            .v_flex()
            .gap_5()
            .when_some(self.error.clone(), |d, err| d.child(ui::notice(format!("Couldn't reach DocBox's engine: {err}"), cx)))
            .child(
                ui::wrap_row()
                    .gap_4()
                    .items_end()
                    .child(div().flex_1().min_w(px(420.)).child(ui::section("Recommended start", recommended, cx)))
                    .child(div().flex_1().min_w(px(420.)).child(ui::section("This device", device, cx))),
            )
            .child(
                div()
                    .v_flex()
                    .gap_2()
                    .child(
                        div()
                            .h_flex()
                            .justify_between()
                            .child(ui::section_label("All engines", cx))
                            .child(
                                Button::new("setup-refresh")
                                    .ghost()
                                    .small()
                                    .icon(IconName::RefreshCw)
                                    .label("Refresh")
                                    .loading(self.loading)
                                    .disabled(self.loading)
                                    .on_click(cx.listener(|this, _, _, cx| this.refresh(cx))),
                            ),
                    )
                    .child(engines),
            )
            .into_any_element()
    }
}
