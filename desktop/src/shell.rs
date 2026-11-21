//! The window: the setup screen until the backend is up, then the sidebar, the page header
//! and the current view.

use std::time::Duration;

use gpui_kit::assets::IconName;
use gpui_kit::component::button::{Button, ButtonVariants};
use gpui_kit::component::sidebar::{Sidebar, SidebarMenu, SidebarMenuItem};
use gpui_kit::component::spinner::Spinner;
use gpui_kit::component::switch::Switch;
use gpui_kit::component::{ActiveTheme, Disableable, Icon, Sizable, StyledExt};
use gpui_kit::prelude::FluentBuilder as _;
use gpui_kit::*;

use crate::api::{Api, ReadState, SettingsUpdate};
use crate::backend::{Backend, BootState, BootStatus};
use crate::format;
use crate::state::{AppState, View, call};
use crate::ui;
use crate::views::{
    benchmarks::BenchmarksView, connections::ConnectionsView, device::DeviceView, models::ModelsView,
    read::ReadView, setup::SetupView,
};

/// The number in the header's pill, per view.
#[derive(Clone)]
struct HeroStat {
    value: String,
    label: String,
}

#[derive(Default)]
struct Views {
    setup: Option<Entity<SetupView>>,
    models: Option<Entity<ModelsView>>,
    read: Option<Entity<ReadView>>,
    benchmarks: Option<Entity<BenchmarksView>>,
    connections: Option<Entity<ConnectionsView>>,
    device: Option<Entity<DeviceView>>,
}

pub struct DocBox {
    backend: Backend,
    boot: BootStatus,
    state: Option<Entity<AppState>>,
    views: Views,
    stat: Option<HeroStat>,
    stat_for: Option<(View, u64)>,
    scroll: ScrollHandle,
    _tasks: Vec<Task<()>>,
    _subscriptions: Vec<Subscription>,
}

impl DocBox {
    pub fn new(backend: Backend, cx: &mut Context<Self>) -> Self {
        let mut this = Self {
            boot: backend.status(),
            backend,
            state: None,
            views: Views::default(),
            stat: None,
            stat_for: None,
            scroll: ScrollHandle::new(),
            _tasks: Vec::new(),
            _subscriptions: Vec::new(),
        };
        this.watch_boot(cx);
        this
    }

    /// Follow the backend's start, then build the app state once it answers.
    fn watch_boot(&mut self, cx: &mut Context<Self>) {
        let task = cx.spawn(async move |this, cx| {
            loop {
                cx.background_executor().timer(Duration::from_millis(250)).await;
                let done = this
                    .update(cx, |this, cx| {
                        this.boot = this.backend.status();
                        cx.notify();
                        match this.boot.state {
                            BootState::Ready => {
                                if let Some(url) = this.boot.base_url.clone() {
                                    this.ready(Api::new(url), cx);
                                }
                                true
                            }
                            BootState::Failed => true,
                            BootState::Starting => false,
                        }
                    })
                    .unwrap_or(true);
                if done {
                    break;
                }
            }
        });
        self._tasks.push(task);
    }

    fn ready(&mut self, api: Api, cx: &mut Context<Self>) {
        let state = cx.new(|cx| AppState::new(api, cx));
        self._subscriptions.push(cx.observe(&state, |this, state, cx| {
            let s = state.read(cx);
            if this.stat_for.map(|(view, _)| view) != Some(s.view) {
                // A new page starts at its top, not wherever the last one was scrolled to.
                this.scroll.set_offset(point(px(0.), px(0.)));
            }
            if this.stat_for != Some((s.view, s.revision)) {
                this.load_stat(cx);
            }
            cx.notify();
        }));
        self.state = Some(state);
        self.load_stat(cx);
    }

    fn retry(&mut self, cx: &mut Context<Self>) {
        self.backend.retry();
        self.boot = self.backend.status();
        self.watch_boot(cx);
        cx.notify();
    }

    fn load_stat(&mut self, cx: &mut Context<Self>) {
        let Some(state) = &self.state else { return };
        let s = state.read(cx);
        let (view, revision, api) = (s.view, s.revision, s.api.clone());
        self.stat_for = Some((view, revision));
        match view {
            // Worked out from the hardware numbers as they render: they may arrive later.
            View::Setup | View::Device => self.stat = None,
            View::Models => {
                call(cx, api, |api| api.engine_storage(), |this, r, _| {
                    this.stat = r.ok().map(|s| HeroStat {
                        value: format::bytes(s.models_bytes),
                        label: "used by models on disk".into(),
                    });
                })
                .detach();
            }
            View::Read => {
                call(cx, api, |api| api.list_reads(), |this, r, _| {
                    this.stat = r.ok().map(|list| {
                        let done: Vec<_> = list.iter().filter(|r| r.state == ReadState::Done).collect();
                        let cloud = done.iter().filter(|r| r.model_id.starts_with("nvidia-nim:")).count();
                        HeroStat {
                            value: format!("{} read", format::plural(done.len(), "file", "files")),
                            label: if cloud > 0 {
                                format!("{cloud} through the cloud")
                            } else {
                                "all on this computer".into()
                            },
                        }
                    });
                })
                .detach();
            }
            View::Benchmarks => {
                call(cx, api, |api| api.list_benchmarks(), |this, r, _| {
                    this.stat = r.ok().map(|list| {
                        let best = list
                            .iter()
                            .find_map(|run| {
                                let summary = run.summary.as_ref()?;
                                let id = summary.best_model_id.as_ref()?;
                                summary.leaderboard.iter().find(|row| &row.model_id == id)
                            })
                            .map(|row| crate::views::benchmarks::short_name(&row.name));
                        HeroStat {
                            value: format::plural(list.len(), "batch", "batches"),
                            label: best.map_or_else(|| "every page, every model".into(), |b| format!("best: {b}")),
                        }
                    });
                })
                .detach();
            }
            View::Connections => {
                call(cx, api, |api| api.list_platforms(), |this, r, _| {
                    this.stat = r.ok().map(|list| HeroStat {
                        value: format!("{} of 2", list.iter().filter(|p| p.available).count()),
                        label: "services connected".into(),
                    });
                })
                .detach();
            }
        }
    }

    fn current_view(&mut self, state: &Entity<AppState>, window: &mut Window, cx: &mut Context<Self>) -> AnyView {
        let view = state.read(cx).view;
        let v = &mut self.views;
        match view {
            View::Setup => v.setup.get_or_insert_with(|| cx.new(|cx| SetupView::new(state.clone(), window, cx))).clone().into(),
            View::Models => v.models.get_or_insert_with(|| cx.new(|cx| ModelsView::new(state.clone(), window, cx))).clone().into(),
            View::Read => v.read.get_or_insert_with(|| cx.new(|cx| ReadView::new(state.clone(), window, cx))).clone().into(),
            View::Benchmarks => v
                .benchmarks
                .get_or_insert_with(|| cx.new(|cx| BenchmarksView::new(state.clone(), window, cx)))
                .clone()
                .into(),
            View::Connections => v
                .connections
                .get_or_insert_with(|| cx.new(|cx| ConnectionsView::new(state.clone(), window, cx)))
                .clone()
                .into(),
            View::Device => v.device.get_or_insert_with(|| cx.new(|cx| DeviceView::new(state.clone(), window, cx))).clone().into(),
        }
    }

    fn render_boot(&mut self, cx: &mut Context<Self>) -> Div {
        let failed = self.boot.state == BootState::Failed;
        let progress = self.boot.progress as f64;
        let body = if failed {
            div()
                .v_flex()
                .gap_3()
                .child(
                    div()
                        .id("boot-error")
                        .max_h(px(240.))
                        .overflow_y_scroll()
                        .text_xs()
                        .font_family("monospace")
                        .text_color(cx.theme().muted_foreground)
                        .child(self.boot.message.clone()),
                )
                .when_some(self.boot.log_path.clone(), |d, path| {
                    d.child(ui::small_muted(format!("Logs: {}", path.display()), cx))
                })
                .child(
                    div().child(
                        Button::new("retry")
                            .primary()
                            .icon(IconName::RotateCcw)
                            .label("Try again")
                            .on_click(cx.listener(|this, _, _, cx| this.retry(cx))),
                    ),
                )
        } else {
            div()
                .v_flex()
                .gap_3()
                .child(ui::progress_bar("boot-progress", progress))
                .child(
                    div()
                        .h_flex()
                        .gap_2()
                        .text_sm()
                        .child(Spinner::new().small())
                        .child(div().flex_1().min_w_0().truncate().child(self.boot.message.clone()))
                        .child(format!("{}%", progress.round() as i64)),
                )
                .child(ui::muted("Reading engines like PaddleOCR install later, only when you choose one.", cx))
        };
        div()
            .size_full()
            .v_flex()
            .items_center()
            .justify_center()
            .bg(cx.theme().background)
            .child(
                div()
                    .w(px(560.))
                    .v_flex()
                    .gap_6()
                    .child(logo(cx))
                    .child(
                        div()
                            .v_flex()
                            .gap_2()
                            .child(ui::section_label("Welcome", cx))
                            .child(div().text_3xl().font_semibold().child(if failed {
                                "DocBox couldn't start"
                            } else {
                                "Getting DocBox ready"
                            }))
                            .child(ui::muted(
                                if failed {
                                    "Something went wrong while starting DocBox's engine."
                                } else {
                                    "The first time, DocBox sets up its own tools. It takes a minute or two and needs an internet connection. Your files never leave this computer."
                                },
                                cx,
                            )),
                    )
                    .child(ui::card(cx).p_5().child(body)),
            )
    }

    fn render_sidebar(&self, state: &Entity<AppState>, cx: &App) -> impl IntoElement {
        let current = state.read(cx).view;
        let items = View::ALL.into_iter().map(|view| {
            let state = state.clone();
            SidebarMenuItem::new(view.label())
                .icon(Icon::new(view.icon()))
                .active(view == current)
                .on_click(move |_, _, cx| state.update(cx, |s, cx| s.navigate(view, cx)))
        });
        let cloud = state.read(cx).cloud_enabled();
        let has_settings = state.read(cx).settings.is_some();
        let toggle_state = state.clone();
        Sidebar::new("nav")
            .w(px(220.))
            .header(div().px_2().py_1().child(logo(cx)))
            .child(SidebarMenu::new().children(items))
            .footer(
                div()
                    .h_flex()
                    .w_full()
                    .justify_between()
                    .gap_2()
                    .px_2()
                    .child(div().v_flex().child(div().text_sm().font_medium().child("Cloud engine")).child(
                        ui::small_muted(if cloud { "NVIDIA's cloud models allowed" } else { "Off: nothing leaves here" }, cx),
                    ))
                    .child(
                        Switch::new("cloud-switch")
                            .checked(cloud)
                            .disabled(!has_settings)
                            .accessibility_label("Cloud engine: allow NVIDIA's cloud models")
                            .on_change(move |next, _, cx| {
                                let patch = SettingsUpdate { cloud_enabled: Some(*next), ..Default::default() };
                                toggle_state.update(cx, |s, cx| s.update_settings(patch, cx));
                            }),
                    ),
            )
    }
}

pub fn logo(cx: &App) -> Div {
    div()
        .h_flex()
        .gap_2()
        .child(
            div()
                .size(px(28.))
                .rounded_md()
                .bg(cx.theme().primary)
                .h_flex()
                .justify_center()
                .child(Icon::new(IconName::ScanText).small().text_color(cx.theme().primary_foreground)),
        )
        .child(div().text_lg().font_bold().child("DocBox"))
}

impl Render for DocBox {
    fn render(&mut self, window: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        let Some(state) = self.state.clone() else {
            return self.render_boot(cx).into_any_element();
        };
        let view = state.read(cx).view;
        let content = self.current_view(&state, window, cx);
        let caps = state.read(cx).caps.clone();
        let stat = match view {
            View::Setup => caps.map(|c| HeroStat {
                value: format!("{} RAM", format::gb(c.ram_total_gb)),
                label: format!("{} disk free", format::gb(c.disk_free_gb)),
            }),
            View::Device => caps.map(|c| HeroStat {
                value: format!("{} cores", c.cpu_physical_cores),
                label: format!("{} threads", c.cpu_logical_cores),
            }),
            _ => self.stat.clone(),
        };
        let banner = crate::update::banner(cx);
        div()
            .size_full()
            .h_flex()
            .items_start()
            .bg(cx.theme().background)
            .text_color(cx.theme().foreground)
            .child(self.render_sidebar(&state, cx))
            .child(
                div()
                    .id("main")
                    .flex_1()
                    .h_full()
                    .min_w_0()
                    .overflow_y_scroll()
                    .track_scroll(&self.scroll)
                    .child(
                        div()
                            .v_flex()
                            .gap_5()
                            .px_8()
                            .py_6()
                            .max_w(px(1280.))
                            .when_some(banner, |d, b| d.child(b))
                            .child(
                                div()
                                    .h_flex()
                                    .flex_wrap()
                                    .items_end()
                                    .justify_between()
                                    .gap_4()
                                    .pb_4()
                                    .border_b_1()
                                    .border_color(cx.theme().border)
                                    .child(
                                        div()
                                            .v_flex()
                                            .gap_1()
                                            .child(ui::section_label(view.eyebrow(), cx))
                                            .child(div().text_3xl().font_semibold().child(view.title())),
                                    )
                                    .when_some(stat, |d, stat| {
                                        d.child(
                                            div()
                                                .h_flex()
                                                .gap_2()
                                                .px_3()
                                                .py_1()
                                                .rounded_full()
                                                .bg(cx.theme().secondary)
                                                .text_sm()
                                                .child(div().font_semibold().child(stat.value))
                                                .child(div().text_color(cx.theme().muted_foreground).child(stat.label)),
                                        )
                                    }),
                            )
                            .child(content),
                    ),
            )
            .into_any_element()
    }
}
