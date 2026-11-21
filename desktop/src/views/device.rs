//! This device: the hardware DocBox checks models against, the graphics card (where models
//! read, and each engine's build), and the memory limit.

use std::collections::BTreeMap;
use std::time::Duration;

use gpui_kit::assets::IconName;
use gpui_kit::component::button::{Button, ButtonVariants};
use gpui_kit::component::slider::{Slider, SliderEvent, SliderState, SliderValue};
use gpui_kit::component::switch::Switch;
use gpui_kit::component::{ActiveTheme, Disableable, Selectable, Sizable, StyledExt};
use gpui_kit::prelude::FluentBuilder as _;
use gpui_kit::*;

use crate::api::{Device, DeviceCapabilities, DevicePreference, DownloadState, DownloadStatus, EngineGpuBuild, GpuStatus, SettingsUpdate};
use crate::backend::Backend;
use crate::format;
use crate::state::{AppState, call};
use crate::ui;

#[derive(Default)]
struct BuildRow {
    confirming: bool,
    job: Option<DownloadStatus>,
    result: Option<(String, bool)>,
    _poll: Option<Task<()>>,
}

pub struct DeviceView {
    state: Entity<AppState>,
    gpu: Option<GpuStatus>,
    loading: bool,
    rows: BTreeMap<String, BuildRow>,
    ram: Entity<SliderState>,
    ram_value: Option<f32>,
    seen_revision: u64,
    _subscriptions: Vec<Subscription>,
}

/// What reads fastest on this computer, from its hardware.
fn speed_advice(caps: &DeviceCapabilities, gpu: Option<&GpuStatus>) -> String {
    let card = format::short_gpu(caps.gpu_name.as_deref().unwrap_or("graphics card"));
    let on_card = gpu.and_then(|g| g.engines.iter().find(|e| e.installed == Some(Device::Gpu)));
    match (caps.gpu_memory_gb, on_card) {
        (Some(_), Some(engine)) => format!(
            "{} reads on your {card}, and so do Ollama's models. PaddleOCR Mobile and Tesseract stay on the processor, where they're quick anyway.",
            engine_short(&engine.name)
        ),
        (Some(mem), None) => format!(
            "Ollama models read on your {card} ({}), the fastest way to run the large vision models here. DocBox's own models read on the {}-core processor: PaddleOCR Mobile is quickest on it, and the larger PaddleOCR models read several times faster on the graphics card{}",
            format::gb(mem),
            caps.cpu_physical_cores,
            if gpu.is_some_and(|g| g.usable) { " once you switch PaddleOCR to it below." } else { "." }
        ),
        (None, _) => format!(
            "DocBox's models read on the {}-core processor. Without an NVIDIA graphics card, PaddleOCR Mobile is the quickest choice, and large vision models in Ollama will be slow.",
            caps.cpu_physical_cores
        ),
    }
}

/// "PaddleOCR engine (PP-OCR)" -> "PaddleOCR".
fn engine_short(name: &str) -> String {
    name.split(" engine").next().unwrap_or(name).to_string()
}

impl DeviceView {
    pub fn new(state: Entity<AppState>, window: &mut Window, cx: &mut Context<Self>) -> Self {
        let ram = cx.new(|_| SliderState::new().min(1.0).max(64.0).step(0.5));
        let subscriptions = vec![
            cx.observe_in(&state, window, |this: &mut Self, state, window, cx| {
                if state.read(cx).revision != this.seen_revision {
                    this.seen_revision = state.read(cx).revision;
                    this.load_gpu(cx);
                }
                this.sync_slider(window, cx);
                cx.notify();
            }),
            cx.subscribe(&ram, |this: &mut Self, _, event: &SliderEvent, cx| match event {
                SliderEvent::Change(SliderValue::Single(v)) => {
                    this.ram_value = Some(*v);
                    cx.notify();
                }
                // Saved once the slider rests, not at every step of a drag.
                SliderEvent::Release(SliderValue::Single(v)) => {
                    let patch = SettingsUpdate { ram_limit_gb: Some(*v as f64), ..Default::default() };
                    this.state.update(cx, |s, cx| s.update_settings(patch, cx));
                }
                _ => {}
            }),
        ];
        let mut this = Self {
            seen_revision: state.read(cx).revision,
            state,
            gpu: None,
            loading: false,
            rows: BTreeMap::new(),
            ram,
            ram_value: None,
            _subscriptions: subscriptions,
        };
        this.load_gpu(cx);
        this.sync_slider(window, cx);
        this
    }

    /// The slider's range is 1 GB up to all of this computer's memory, in half gigabytes.
    fn sync_slider(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        let s = self.state.read(cx);
        let Some(total) = s.caps.as_ref().map(|c| c.ram_total_gb) else { return };
        let max = ((total * 2.0).floor() / 2.0).max(1.0) as f32;
        let saved = s.settings.as_ref().and_then(|s| s.ram_limit_gb).map(|v| v as f32);
        let value = saved.unwrap_or(max).min(max);
        self.ram.update(cx, |slider, cx| {
            if slider.max_value() != max {
                *slider = SliderState::new().min(1.0).max(max).step(0.5);
            }
            if slider.value() != SliderValue::Single(value) {
                slider.set_value(value, window, cx);
            }
        });
        self.ram_value = Some(value);
    }

    fn load_gpu(&mut self, cx: &mut Context<Self>) {
        let api = self.state.read(cx).api.clone();
        call(cx, api, |api| api.gpu_status(), |this, result, cx| {
            this.gpu = result.ok();
            // A switch already running (started before this view opened) is followed too.
            let running: Vec<(String, DownloadStatus)> = this
                .gpu
                .iter()
                .flat_map(|g| g.engines.iter())
                .filter_map(|e| e.job.clone().filter(|j| !j.state.finished()).map(|j| (e.id.clone(), j)))
                .collect();
            for (id, job) in running {
                if this.rows.get(&id).is_none_or(|r| r.job.is_none()) {
                    this.follow(id, job, cx);
                }
            }
        })
        .detach();
    }

    fn refresh(&mut self, cx: &mut Context<Self>) {
        self.loading = true;
        self.state.update(cx, |s, cx| s.refresh_caps(cx));
        let api = self.state.read(cx).api.clone();
        call(cx, api, |api| api.gpu_status(), |this, result, _| {
            this.gpu = result.ok();
            this.loading = false;
        })
        .detach();
        cx.notify();
    }

    fn switch_build(&mut self, id: String, build: Device, cx: &mut Context<Self>) {
        let row = self.rows.entry(id.clone()).or_default();
        row.confirming = false;
        row.result = None;
        let api = self.state.read(cx).api.clone();
        let key = id.clone();
        call(cx, api, move |api| api.switch_engine_build(&id, build), move |this, result, cx| match result {
            Ok(job) => this.follow(key, job, cx),
            Err(err) => this.rows.entry(key).or_default().result = Some((err, true)),
        })
        .detach();
    }

    fn follow(&mut self, id: String, job: DownloadStatus, cx: &mut Context<Self>) {
        let api = self.state.read(cx).api.clone();
        let job_id = job.job_id.clone();
        let key = id.clone();
        let task = cx.spawn(async move |this, cx| {
            loop {
                cx.background_executor().timer(Duration::from_secs(1)).await;
                let (api2, job2) = (api.clone(), job_id.clone());
                let status = cx.background_spawn(async move { api2.engine_build_status(&job2) }).await;
                let done = this
                    .update(cx, |this, cx| {
                        let row = this.rows.entry(key.clone()).or_default();
                        let done = match status {
                            Ok(s) if s.state.finished() => {
                                row.result = Some((s.message.clone().unwrap_or_default(), s.state == DownloadState::Error));
                                row.job = None;
                                true
                            }
                            Ok(s) => {
                                row.job = Some(s);
                                false
                            }
                            Err(err) => {
                                row.result = Some((err, true));
                                row.job = None;
                                true
                            }
                        };
                        if done {
                            this.state.update(cx, |s, cx| s.bump(cx));
                        }
                        cx.notify();
                        done
                    })
                    .unwrap_or(true);
                if done {
                    break;
                }
            }
        });
        let row = self.rows.entry(id).or_default();
        row.job = Some(job);
        row._poll = Some(task);
        cx.notify();
    }

    fn build_row(&self, engine: &EngineGpuBuild, first: bool, cx: &mut Context<Self>) -> Div {
        let row = self.rows.get(&engine.id);
        let running = row.is_some_and(|r| r.job.is_some());
        let confirming = row.is_some_and(|r| r.confirming);
        let on_card = engine.installed == Some(Device::Gpu);
        let size = format::mb(engine.gpu_download_mb);
        let status = if engine.pending_restart {
            "Switches the next time DocBox starts."
        } else if on_card {
            "Graphics-card build installed."
        } else if engine.installed.is_some() {
            "Processor build installed."
        } else {
            "Not installed yet."
        };
        let (id1, id2, id3, id4) = (engine.id.clone(), engine.id.clone(), engine.id.clone(), engine.id.clone());
        let action: Option<AnyElement> = if engine.pending_restart {
            Some(
                Button::new(SharedString::from(format!("restart-{}", engine.id)))
                    .small()
                    .outline()
                    .icon(IconName::RotateCcw)
                    .label("Restart DocBox")
                    .on_click(|_, _, cx| {
                        // Stops the backend first, as quitting does; the next start applies the switch.
                        cx.global::<Backend>().shutdown();
                        cx.restart();
                    })
                    .into_any_element(),
            )
        } else if running {
            None
        } else if on_card {
            Some(
                Button::new(SharedString::from(format!("to-cpu-{}", engine.id)))
                    .small()
                    .outline()
                    .label("Use the processor instead")
                    .on_click(cx.listener(move |this, _, _, cx| this.switch_build(id1.clone(), Device::Cpu, cx)))
                    .into_any_element(),
            )
        } else if confirming {
            Some(
                div()
                    .h_flex()
                    .gap_2()
                    .child(
                        Button::new(SharedString::from(format!("to-gpu-yes-{}", engine.id)))
                            .small()
                            .primary()
                            .label(format!("Download {size}"))
                            .on_click(cx.listener(move |this, _, _, cx| this.switch_build(id2.clone(), Device::Gpu, cx))),
                    )
                    .child(
                        Button::new(SharedString::from(format!("to-gpu-no-{}", engine.id)))
                            .small()
                            .ghost()
                            .label("Cancel")
                            .on_click(cx.listener(move |this, _, _, cx| {
                                this.rows.entry(id3.clone()).or_default().confirming = false;
                                cx.notify();
                            })),
                    )
                    .into_any_element(),
            )
        } else {
            Some(
                Button::new(SharedString::from(format!("to-gpu-{}", engine.id)))
                    .small()
                    .outline()
                    .label(format!("Use the graphics card · {size}"))
                    .disabled(engine.blocked.is_some())
                    .on_click(cx.listener(move |this, _, _, cx| {
                        this.rows.entry(id4.clone()).or_default().confirming = true;
                        cx.notify();
                    }))
                    .into_any_element(),
            )
        };
        div()
            .v_flex()
            .gap_2()
            .when(!first, |d| d.pt_3().border_t_1().border_color(cx.theme().border))
            .child(
                div()
                    .h_flex()
                    .flex_wrap()
                    .justify_between()
                    .gap_3()
                    .child(div().v_flex().child(div().text_sm().font_medium().child(engine.name.clone())).child(ui::small_muted(status, cx)))
                    .when_some(action, |d, a| d.child(a)),
            )
            .when(confirming, |d| {
                d.child(ui::small_muted(
                    format!(
                        "DocBox downloads {}'s build for NVIDIA graphics cards, NVIDIA's CUDA libraries included, and installs it in place of the processor build. Your models stay, and read on the card from the next read.",
                        engine_short(&engine.name)
                    ),
                    cx,
                ))
            })
            .when(!on_card && !running, |d| d.when_some(engine.blocked.clone(), |d, why| d.child(ui::small_muted(why, cx))))
            .when_some(row.and_then(|r| r.job.clone()), |d, job| {
                d.child(
                    div()
                        .v_flex()
                        .gap_1()
                        .child(ui::progress_bar(SharedString::from(format!("build-{}", engine.id)), job.progress_pct.unwrap_or(0.0)))
                        .child(ui::small_muted(job.message.unwrap_or_else(|| "Starting".into()), cx)),
                )
            })
            .when_some(row.and_then(|r| r.result.clone()), |d, (text, error)| {
                d.child(if error { ui::error_text(text, cx) } else { ui::small_muted(text, cx) })
            })
    }

    fn graphics_card(&self, gpu: &GpuStatus, cx: &mut Context<Self>) -> Div {
        let preference = self.state.read(cx).settings.as_ref().map_or(DevicePreference::Auto, |s| s.device_preference);
        let mut details = String::new();
        if let Some(name) = &gpu.name {
            details.push_str(&format::short_gpu(name));
            if let Some(total) = gpu.memory_total_gb {
                details.push_str(&format!(" · {}", format::gb(total)));
                if let Some(free) = gpu.memory_free_gb {
                    details.push_str(&format!(", {} free", format::gb(free)));
                }
            }
            if let Some(driver) = &gpu.driver_version {
                details.push_str(&format!(" · driver {driver}"));
            }
            if let Some(cuda) = &gpu.cuda_version {
                details.push_str(&format!(" · CUDA {cuda}"));
            }
        }
        let mut card = ui::card(cx).gap_4().p_5().when(!details.is_empty(), |d| d.child(div().text_sm().font_medium().child(details)));
        if !gpu.usable {
            card = card.child(ui::muted(format!("{} DocBox's own models read on the processor.", gpu.reason.clone().unwrap_or_default()), cx));
        } else {
            let mut choices = div().h_flex().flex_wrap().gap_1();
            for (value, label) in [
                (DevicePreference::Auto, "Automatic: the models that read best on it"),
                (DevicePreference::Gpu, "Every model that can"),
                (DevicePreference::Cpu, "None: always the processor"),
            ] {
                let state = self.state.clone();
                choices = choices.child(
                    Button::new(SharedString::from(format!("pref-{value:?}")))
                        .small()
                        .outline()
                        .label(label)
                        .selected(preference == value)
                        .on_click(move |_, _, cx| {
                            let patch = SettingsUpdate { device_preference: Some(value), ..Default::default() };
                            state.update(cx, |s, cx| s.update_settings(patch, cx));
                        }),
                );
            }
            card = card
                .child(ui::muted(
                    "PaddleOCR or EasyOCR can read on this card, several times faster for the larger models, once its graphics-card build is installed. One engine at a time can use it. If the card fails to start or runs out of memory, the model reads on the processor and its details say why.",
                    cx,
                ))
                .child(div().v_flex().gap_2().child(ui::small_muted("Models that read on it", cx)).child(choices));
        }
        if gpu.usable || gpu.engines.iter().any(|e| e.installed == Some(Device::Gpu)) {
            let mut rows = div().v_flex().gap_3();
            for (i, engine) in gpu.engines.iter().enumerate() {
                rows = rows.child(self.build_row(engine, i == 0, cx));
            }
            card = card.child(rows);
        }
        card
    }
}

impl Render for DeviceView {
    fn render(&mut self, _: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        let caps = self.state.read(cx).caps.clone();
        let header = div()
            .h_flex()
            .flex_wrap()
            .justify_between()
            .gap_3()
            .child(div().flex_1().min_w(px(200.)).max_w(px(640.)).child(ui::muted(
                "DocBox compares this with what each model needs, so it can tell you which ones will run comfortably here.",
                cx,
            )))
            .child(
                Button::new("device-refresh")
                    .small()
                    .outline()
                    .icon(IconName::RefreshCw)
                    .label("Refresh")
                    .loading(self.loading)
                    .disabled(self.loading)
                    .on_click(cx.listener(|this, _, _, cx| this.refresh(cx))),
            );
        let Some(caps) = caps else {
            return div()
                .v_flex()
                .gap_5()
                .child(header)
                .when(!self.loading, |d| d.child(ui::notice("Couldn't reach DocBox's engine to read this computer's hardware.", cx)));
        };
        let gpu = self.gpu.clone();
        let reads_on_card = gpu.as_ref().is_some_and(|g| g.engines.iter().any(|e| e.installed == Some(Device::Gpu)));
        let graphics_sub = if reads_on_card {
            format!("{} · reads models", format::gb(caps.gpu_memory_gb.unwrap_or(0.0)))
        } else if let Some(mem) = caps.gpu_memory_gb {
            format!("{} · used by Ollama", format::gb(mem))
        } else {
            "DocBox's own engines read on the CPU".into()
        };
        let hardware = ui::wrap_row()
            .child(ui::stat_card("Free memory", format::gb(caps.ram_available_gb), Some(format!("of {} total", format::gb(caps.ram_total_gb)).into()), cx).flex_basis(px(200.)).flex_grow(1.).flex_shrink(1.).min_w_0().bg(cx.theme().secondary))
            .child(ui::stat_card("Processor", format!("{} cores", caps.cpu_physical_cores), Some(format!("{} threads", caps.cpu_logical_cores).into()), cx).flex_basis(px(200.)).flex_grow(1.).flex_shrink(1.).min_w_0())
            .child(ui::stat_card("Free disk", format::gb(caps.disk_free_gb), Some(format!("of {}, for models", format::gb(caps.disk_total_gb)).into()), cx).flex_basis(px(200.)).flex_grow(1.).flex_shrink(1.).min_w_0())
            .child(ui::stat_card("Graphics", caps.gpu_name.as_deref().map_or("CPU only".into(), format::short_gpu), Some(graphics_sub.into()), cx).flex_basis(px(200.)).flex_grow(1.).flex_shrink(1.).min_w_0())
            .child(ui::stat_card("System", caps.os_name.clone(), Some(caps.arch.clone().into()), cx).flex_basis(px(200.)).flex_grow(1.).flex_shrink(1.).min_w_0());

        let saved = self.state.read(cx).settings.as_ref().and_then(|s| s.ram_limit_gb);
        let state = self.state.clone();
        let total = caps.ram_total_gb;
        let ram_card = ui::card(cx)
            .gap_3()
            .p_5()
            .child(
                div()
                    .h_flex()
                    .items_start()
                    .justify_between()
                    .gap_4()
                    .child(div().flex_1().min_w(px(200.)).max_w(px(640.)).child(ui::muted(
                        "The most memory a model may take while it reads. Models over it aren't recommended, and DocBox won't start a read with one, so other apps keep what they need.",
                        cx,
                    )))
                    .child(
                        Switch::new("ram-limit")
                            .checked(saved.is_some())
                            .accessibility_label("Limit how much memory a model may take")
                            .on_change(move |on, _, cx| {
                                let max = ((total * 2.0).floor() / 2.0).max(1.0);
                                let limit = if *on { (total / 2.0).round().clamp(1.0, max) } else { 0.0 };
                                let patch = SettingsUpdate { ram_limit_gb: Some(limit), ..Default::default() };
                                state.update(cx, |s, cx| s.update_settings(patch, cx));
                            }),
                    ),
            )
            .when(saved.is_some(), |d| {
                d.child(
                    div()
                        .h_flex()
                        .gap_4()
                        .child(div().flex_1().child(Slider::new(&self.ram).accessibility_label("Memory limit")))
                        .child(div().w(px(64.)).text_right().text_sm().font_medium().child(format::gb(self.ram_value.unwrap_or(0.0) as f64))),
                )
            });

        div()
            .v_flex()
            .gap_5()
            .child(header)
            .child(ui::section("Hardware", hardware, cx))
            .child(div().max_w(px(800.)).child(ui::small_muted(speed_advice(&caps, gpu.as_ref()), cx)))
            .when_some(gpu, |d, gpu| d.child(ui::section("Graphics card", self.graphics_card(&gpu, cx), cx)))
            .child(ui::section("Memory limit", ram_card, cx))
    }
}
