//! Models: the default model, storage, the model library (search, filter, install, remove,
//! where each one reads) and the engines on disk.

use std::collections::{BTreeMap, HashSet};
use std::time::Duration;

use gpui_kit::assets::IconName;
use gpui_kit::component::button::{Button, ButtonVariants};
use gpui_kit::component::input::{Input, InputEvent, InputState};
use gpui_kit::component::spinner::Spinner;
use gpui_kit::component::{ActiveTheme, Disableable, Icon, Selectable, Sizable, StyledExt};
use gpui_kit::prelude::FluentBuilder as _;
use gpui_kit::*;

use crate::api::{Device, DevicePreference, EngineStorage, ModelInfo, ModelStatus, SettingsUpdate, StorageInfo};
use crate::format;
use crate::jobs::ModelJob;
use crate::model_actions::{self, is_cloud, size_label};
use crate::state::{AppState, View, call};
use crate::ui;

#[derive(Default)]
struct EngineRemoval {
    confirm: bool,
    working: bool,
    note: Option<String>,
}

pub struct ModelsView {
    state: Entity<AppState>,
    models: Vec<(ModelInfo, Entity<ModelJob>)>,
    storage: Option<StorageInfo>,
    error: Option<String>,
    loaded: bool,
    seen_revision: u64,
    request: u64,
    search: Entity<InputState>,
    engine_filter: Option<String>,
    open: HashSet<String>,
    folder_opened: bool,
    folder_error: Option<String>,
    removals: BTreeMap<String, EngineRemoval>,
    _flash: Option<Task<()>>,
    _subscriptions: Vec<Subscription>,
    _jobs: Vec<Subscription>,
}

impl ModelsView {
    pub fn new(state: Entity<AppState>, window: &mut Window, cx: &mut Context<Self>) -> Self {
        let search = cx.new(|cx| InputState::new(window, cx).placeholder("Search models or languages…"));
        let subscriptions = vec![
            cx.observe(&state, |this: &mut Self, state, cx| {
                if state.read(cx).revision != this.seen_revision {
                    this.refresh(cx);
                }
                cx.notify();
            }),
            cx.subscribe(&search, |_, _, event: &InputEvent, cx| {
                if matches!(event, InputEvent::Change) {
                    cx.notify();
                }
            }),
        ];
        let mut this = Self {
            seen_revision: state.read(cx).revision,
            state,
            models: Vec::new(),
            storage: None,
            error: None,
            loaded: false,
            request: 0,
            search,
            engine_filter: None,
            open: HashSet::new(),
            folder_opened: false,
            folder_error: None,
            removals: BTreeMap::new(),
            _flash: None,
            _subscriptions: subscriptions,
            _jobs: Vec::new(),
        };
        this.refresh(cx);
        this
    }

    fn refresh(&mut self, cx: &mut Context<Self>) {
        self.seen_revision = self.state.read(cx).revision;
        self.error = None;
        // Only the latest refresh may set state: an older one finishing later would put back
        // a listing from before a download ended, which shows it still running.
        self.request += 1;
        let request = self.request;
        let api = self.state.read(cx).api.clone();
        // The list doesn't wait for the storage figures, which take longer to work out.
        call(cx, api.clone(), |api| api.engine_storage(), move |this, result, _| {
            if request == this.request {
                this.storage = result.ok();
            }
        })
        .detach();
        call(cx, api, |api| api.list_models(), move |this, result, cx| {
            if request != this.request {
                return;
            }
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

    fn open_folder(&mut self, cx: &mut Context<Self>) {
        self.folder_error = None;
        let api = self.state.read(cx).api.clone();
        call(cx, api, |api| api.open_models_folder(), |this, result, cx| match result {
            Ok(()) => {
                this.folder_opened = true;
                this._flash = Some(cx.spawn(async move |this, cx| {
                    cx.background_executor().timer(Duration::from_millis(1800)).await;
                    this.update(cx, |this, cx| {
                        this.folder_opened = false;
                        cx.notify();
                    })
                    .ok();
                }));
            }
            Err(err) => this.folder_error = Some(err),
        })
        .detach();
    }

    fn uninstall_engine(&mut self, id: String, cx: &mut Context<Self>) {
        let entry = self.removals.entry(id.clone()).or_default();
        entry.working = true;
        entry.note = None;
        let api = self.state.read(cx).api.clone();
        let key = id.clone();
        call(cx, api, move |api| api.uninstall_engine(&id), move |this, result, cx| {
            let entry = this.removals.entry(key).or_default();
            entry.working = false;
            match result {
                Ok(r) => {
                    entry.note = Some(r.detail);
                    entry.confirm = false;
                    this.state.update(cx, |s, cx| s.bump(cx));
                }
                Err(err) => entry.note = Some(err),
            }
        })
        .detach();
    }

    fn filtered(&self, cx: &App) -> Vec<&(ModelInfo, Entity<ModelJob>)> {
        let q = self.search.read(cx).value().trim().to_lowercase();
        self.models
            .iter()
            .filter(|(m, _)| self.engine_filter.as_ref().is_none_or(|e| &m.engine == e))
            .filter(|(m, _)| {
                q.is_empty()
                    || m.name.to_lowercase().contains(&q)
                    || m.description.to_lowercase().contains(&q)
                    || format::language_names(&m.languages).to_lowercase().contains(&q)
            })
            .collect()
    }

    fn default_card(&self, cx: &mut Context<Self>) -> Div {
        let state = self.state.clone();
        let default_id = state.read(cx).default_model_id().map(str::to_string);
        let model = self.models.iter().map(|(m, _)| m).find(|m| Some(&m.id) == default_id.as_ref());
        let card = ui::card(cx).min_h(px(140.)).justify_between().gap_3().p_5().bg(cx.theme().secondary);
        let Some(model) = model else {
            let suggestion = self.models.iter().map(|(m, _)| m).find(|m| m.status == ModelStatus::Ready).cloned();
            return card
                .child(div().h_flex().child(ui::chip("No default yet")))
                .child(
                    div()
                        .h_flex()
                        .flex_wrap()
                        .items_end()
                        .justify_between()
                        .gap_3()
                        .child(div().max_w(px(420.)).child(ui::muted(
                            if suggestion.is_some() {
                                "The default is picked first whenever you read a file."
                            } else {
                                "The default is picked first whenever you read a file. Install a model below, then choose Use as default."
                            },
                            cx,
                        )))
                        .when_some(suggestion, |d, m| {
                            d.child(
                                Button::new("use-suggestion")
                                    .small()
                                    .primary()
                                    .icon(IconName::Check)
                                    .label(format!("Use {}", m.name))
                                    .on_click(move |_, _, cx| {
                                        let patch = SettingsUpdate { default_model_id: Some(m.id.clone()), ..Default::default() };
                                        state.update(cx, |s, cx| s.update_settings(patch, cx));
                                    }),
                            )
                        }),
                );
        };
        let ready = model.status == ModelStatus::Ready;
        card.child(
            div()
                .h_flex()
                .justify_between()
                .child(
                    div()
                        .h_flex()
                        .gap_1()
                        .child(ui::chip(if ready { format!("Installed · {}", size_label(model)) } else { "Not installed".into() }))
                        .child(ui::chip("Used for every file")),
                )
                .child(Icon::new(IconName::Check).small()),
        )
        .child(
            div()
                .v_flex()
                .gap_1()
                .child(div().text_2xl().font_semibold().child(model.name.clone()))
                .when(!ready, |d| d.child(ui::muted("Install it again from the library below to read with it.", cx))),
        )
    }

    fn storage_cards(&self, cx: &mut Context<Self>) -> Div {
        let caps = self.state.read(cx).caps.clone();
        let state = self.state.clone();
        div()
            .v_flex()
            .gap_2()
            .child(
                div()
                    .h_flex()
                    .gap_3()
                    .child(
                        ui::stat_button(
                            "models-folder",
                            if self.folder_opened { "Opened the models folder" } else { "Models on disk" },
                            self.storage.as_ref().map_or("…".into(), |s| format::bytes(s.models_bytes)),
                            IconName::FolderOpen,
                            cx.listener(|this, _, _, cx| this.open_folder(cx)),
                            cx,
                        )
                        .flex_1()
                        .min_h(px(140.)),
                    )
                    .child(
                        ui::stat_button(
                            "room-for-more",
                            "Room for more",
                            caps.map_or("…".into(), |c| format::gb(c.disk_free_gb)),
                            IconName::ArrowUpRight,
                            move |_, _, cx| state.update(cx, |s, cx| s.navigate(View::Device, cx)),
                            cx,
                        )
                        .flex_1()
                        .min_h(px(140.)),
                    ),
            )
            .when_some(self.folder_error.clone(), |d, err| d.child(ui::error_text(err, cx)))
    }

    /// Where one model reads, whatever the Device view's setting says for the rest. Only for
    /// engines with a graphics-card build; "Like the rest" follows the global setting again.
    fn device_choice(&self, model: &ModelInfo, cx: &App) -> Div {
        let settings = self.state.read(cx).settings.clone();
        let own = settings
            .as_ref()
            .and_then(|s| s.model_devices.get(&model.id).copied())
            .map_or(DevicePreference::Auto, |d| match d {
                Device::Cpu => DevicePreference::Cpu,
                Device::Gpu => DevicePreference::Gpu,
            });
        let global = settings.as_ref().map_or(DevicePreference::Auto, |s| s.device_preference);
        let mut group = div().h_flex().gap_1().child(ui::small_muted("Reads on", cx).mr_1());
        for (choice, label) in [
            (DevicePreference::Auto, format!("Like the rest ({})", global.label().to_lowercase())),
            (DevicePreference::Gpu, DevicePreference::Gpu.label().to_string()),
            (DevicePreference::Cpu, DevicePreference::Cpu.label().to_string()),
        ] {
            let state = self.state.clone();
            let id = model.id.clone();
            group = group.child(
                Button::new(SharedString::from(format!("device-{}-{choice:?}", model.id)))
                    .xsmall()
                    .outline()
                    .label(label)
                    .selected(own == choice)
                    .on_click(move |_, _, cx| {
                        let patch = SettingsUpdate {
                            model_devices: Some(BTreeMap::from([(id.clone(), choice)])),
                            ..Default::default()
                        };
                        state.update(cx, |s, cx| s.update_settings(patch, cx));
                    }),
            );
        }
        group
    }

    /// What a model takes and how fast it reads: measured figures say so, estimates too.
    fn figures(&self, model: &ModelInfo, cx: &App) -> Div {
        let cloud = is_cloud(model);
        let ram = format::gb(model.approx_ram_mb / 1024.0);
        let mut line = format::language_names(&model.languages);
        if cloud {
            line.push_str(" · runs in NVIDIA's cloud");
        } else if model.ram_measured {
            line.push_str(&format!(" · takes up to {ram} of RAM to read a page"));
        } else {
            line.push_str(&format!(" · takes about {ram} of RAM (an estimate)"));
        }
        if let Some(s) = model.cpu_page_seconds {
            line.push_str(&format!(" · {} a page on a 6-core processor", format::seconds(s)));
        }
        let device = &model.device;
        let where_ = if device.runs_on == Device::Gpu {
            "Reads on this computer's graphics card.".to_string()
        } else if device.preferred == Device::Gpu {
            device.note.clone().unwrap_or_else(|| "Reads best on a graphics card.".into())
        } else {
            "Made for the processor: a graphics card wouldn't make it noticeably faster.".to_string()
        };
        div()
            .v_flex()
            .gap_1()
            .child(ui::small_muted(line, cx))
            .when(!cloud, |d| {
                d.child(
                    div()
                        .h_flex()
                        .flex_wrap()
                        .gap_1()
                        .child(ui::small_muted(where_, cx))
                        .when_some(model.figures_source.clone(), |d, url| {
                            d.child(
                                Button::new(SharedString::from(format!("figures-{}", model.id)))
                                    .link()
                                    .xsmall()
                                    .label("Published sizes and speeds")
                                    .icon(IconName::ArrowUpRight)
                                    .on_click(move |_, _, cx| cx.open_url(&url)),
                            )
                        }),
                )
            })
            .when(device.gpu_capable, |d| d.child(self.device_choice(model, cx)))
    }

    fn library(&self, cx: &mut Context<Self>) -> Div {
        let rows = self.filtered(cx);
        let border = cx.theme().border;
        let hover = cx.theme().accent;
        let header = |text: &'static str| div().text_xs().font_medium().text_color(cx.theme().muted_foreground).child(text);
        let mut table = ui::card(cx).overflow_hidden().child(
            div()
                .h_flex()
                .h(px(36.))
                .px_4()
                .gap_4()
                .border_b_1()
                .border_color(border)
                .child(header("Model").flex_1())
                .child(header("Engine").w(px(110.)))
                .child(header("Size").w(px(72.)))
                .child(header("On this computer").w(px(170.)))
                .child(div().w(px(150.))),
        );
        if !self.loaded {
            return table.child(div().h_flex().justify_center().py_10().child(Spinner::new()));
        }
        if rows.is_empty() {
            return table.child(div().py_8().text_center().child(ui::muted(
                if self.models.is_empty() { "No models to show." } else { "No models match your search." },
                cx,
            )));
        }
        let count = rows.len();
        for (i, (model, job)) in rows.into_iter().enumerate() {
            let open = self.open.contains(&model.id);
            let ok = model.fit.fits && model.fit.notes.is_empty();
            let id = model.id.clone();
            let mut row = div()
                .v_flex()
                .when(i + 1 < count, |d| d.border_b_1().border_color(border))
                .when(open, |d| d.bg(cx.theme().muted))
                .child(
                    div()
                        .id(SharedString::from(format!("row-{}", model.id)))
                        .h_flex()
                        .min_h(px(54.))
                        .px_4()
                        .gap_4()
                        .cursor_pointer()
                        .hover(move |s| s.bg(hover))
                        .on_click(cx.listener(move |this, _, _, cx| {
                            if !this.open.remove(&id) {
                                this.open.insert(id.clone());
                            }
                            cx.notify();
                        }))
                        .child(
                            div()
                                .h_flex()
                                .flex_1()
                                .min_w_0()
                                .gap_2()
                                .child(
                                    Icon::new(if open { IconName::ChevronUp } else { IconName::ChevronDown })
                                        .xsmall()
                                        .text_color(cx.theme().muted_foreground),
                                )
                                .child(div().text_sm().font_medium().truncate().child(model.name.clone())),
                        )
                        .child(div().w(px(110.)).text_sm().text_color(cx.theme().muted_foreground).truncate().child(format::engine_label(&model.engine)))
                        .child(div().w(px(72.)).text_sm().text_color(cx.theme().muted_foreground).child(size_label(model)))
                        .child(div().w(px(170.)).child(ui::fit_chip(ok, model.fit.summary.clone())))
                        .child(div().w(px(150.)).h_flex().justify_end().child(model_actions::action_cell(job, &self.state, cx))),
                );
            if open {
                row = row.child(
                    div()
                        .h_flex()
                        .flex_wrap()
                        .items_start()
                        .gap_8()
                        .pl(px(38.))
                        .pr_4()
                        .pb_4()
                        .child(
                            div()
                                .v_flex()
                                .flex_1()
                                .min_w(px(320.))
                                .gap_2()
                                .child(ui::muted(model.description.clone(), cx))
                                .child(self.figures(model, cx))
                                .when(!model.fit.fits, |d| {
                                    d.child(div().text_xs().text_color(cx.theme().warning).child(model.fit.reasons.join("; ")))
                                }),
                        )
                        .child(div().flex_1().min_w(px(300.)).child(model_actions::setup_panel(job, &self.state, true, cx))),
                );
            } else if let Some(err) = job.read(cx).error.clone() {
                row = row.child(div().pl(px(38.)).pb_3().child(ui::error_text(err, cx)));
            }
            table = table.child(row);
        }
        table
    }

    fn engine_filters(&self, cx: &mut Context<Self>) -> Div {
        let mut engines: Vec<String> = Vec::new();
        for (m, _) in &self.models {
            if !engines.contains(&m.engine) {
                engines.push(m.engine.clone());
            }
        }
        let mut row = div().h_flex().flex_wrap().gap_1().child(
            Button::new("filter-all")
                .xsmall()
                .outline()
                .label("All engines")
                .selected(self.engine_filter.is_none())
                .on_click(cx.listener(|this, _, _, cx| {
                    this.engine_filter = None;
                    cx.notify();
                })),
        );
        for engine in engines {
            let selected = self.engine_filter.as_ref() == Some(&engine);
            let label = format::engine_label(&engine);
            row = row.child(
                Button::new(SharedString::from(format!("filter-{engine}")))
                    .xsmall()
                    .outline()
                    .label(label)
                    .selected(selected)
                    .on_click(cx.listener(move |this, _, _, cx| {
                        this.engine_filter = Some(engine.clone());
                        cx.notify();
                    })),
            );
        }
        row
    }

    fn engine_row(&self, engine: &EngineStorage, last: bool, cx: &mut Context<Self>) -> Div {
        let removal = self.removals.get(&engine.id);
        let confirm = removal.is_some_and(|r| r.confirm);
        let working = removal.is_some_and(|r| r.working);
        let total = engine.package_bytes + engine.model_bytes;
        let (id1, id2, id3) = (engine.id.clone(), engine.id.clone(), engine.id.clone());
        div()
            .v_flex()
            .gap_2()
            .px_4()
            .py_3()
            .when(!last, |d| d.border_b_1().border_color(cx.theme().border))
            .child(
                div()
                    .h_flex()
                    .flex_wrap()
                    .gap_3()
                    .child(div().flex_1().min_w_0().text_sm().font_medium().child(engine.name.clone()))
                    .child(ui::small_muted(
                        if engine.installed {
                            format!("{} engine · {} models", format::bytes(engine.package_bytes), format::bytes(engine.model_bytes))
                        } else {
                            "Not installed".into()
                        },
                        cx,
                    ))
                    .when(engine.removal_pending, |d| d.child(ui::fit_chip(false, "Removed on next restart")))
                    .when(engine.installed && !engine.removal_pending && !confirm, |d| {
                        d.child(
                            Button::new(SharedString::from(format!("uninstall-{}", engine.id)))
                                .xsmall()
                                .ghost()
                                .icon(IconName::Trash)
                                .label("Uninstall")
                                .on_click(cx.listener(move |this, _, _, cx| {
                                    this.removals.entry(id1.clone()).or_default().confirm = true;
                                    cx.notify();
                                })),
                        )
                    }),
            )
            .when(confirm, |d| {
                d.child(
                    div()
                        .h_flex()
                        .flex_wrap()
                        .gap_2()
                        .px_3()
                        .py_2()
                        .rounded_md()
                        .bg(cx.theme().muted)
                        .child(div().flex_1().min_w_0().text_sm().child(format!(
                            "Uninstall {} and its downloaded models? Frees about {}.",
                            engine.name,
                            format::bytes(total)
                        )))
                        .child(
                            Button::new(SharedString::from(format!("uninstall-yes-{}", engine.id)))
                                .xsmall()
                                .danger()
                                .label(if working { "Removing…" } else { "Uninstall" })
                                .disabled(working)
                                .on_click(cx.listener(move |this, _, _, cx| this.uninstall_engine(id2.clone(), cx))),
                        )
                        .child(
                            Button::new(SharedString::from(format!("uninstall-no-{}", engine.id)))
                                .xsmall()
                                .outline()
                                .label("Keep")
                                .on_click(cx.listener(move |this, _, _, cx| {
                                    this.removals.entry(id3.clone()).or_default().confirm = false;
                                    cx.notify();
                                })),
                        ),
                )
            })
            .when_some(removal.and_then(|r| r.note.clone()), |d, note| d.child(ui::small_muted(note, cx)))
    }
}

impl Render for ModelsView {
    fn render(&mut self, _: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        let default_card = self.default_card(cx);
        let storage_cards = self.storage_cards(cx);
        let library = self.library(cx);
        let filters = self.engine_filters(cx);
        let engines = self.storage.clone().map(|info| {
            let count = info.engines.len();
            let mut list = ui::card(cx);
            for (i, e) in info.engines.iter().enumerate() {
                list = list.child(self.engine_row(e, i + 1 == count, cx));
            }
            div()
                .v_flex()
                .gap_2()
                .child(
                    div()
                        .h_flex()
                        .justify_between()
                        .child(ui::section_label("Engines on disk", cx))
                        .child(ui::small_muted(format!("Saved in {}", format::short_path(&info.data_dir, 3)), cx)),
                )
                .child(list)
        });
        div()
            .v_flex()
            .gap_5()
            .when_some(self.error.clone(), |d, err| d.child(ui::notice(format!("Couldn't reach DocBox's engine: {err}"), cx)))
            .child(
                ui::wrap_row()
                    .gap_4()
                    .items_end()
                    .child(div().flex_1().min_w(px(420.)).child(ui::section("Default model", default_card, cx)))
                    .child(div().flex_1().min_w(px(420.)).child(ui::section("Storage", storage_cards, cx))),
            )
            .child(
                div()
                    .v_flex()
                    .gap_2()
                    .child(
                        div()
                            .h_flex()
                            .flex_wrap()
                            .justify_between()
                            .gap_3()
                            .child(ui::section_label("Model library", cx))
                            .child(div().w(px(260.)).child(Input::new(&self.search).small().prefix(Icon::new(IconName::Search).small()))),
                    )
                    .child(filters)
                    .child(library),
            )
            .when_some(engines, |d, e| d.child(e))
    }
}
