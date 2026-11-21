//! One benchmark run: its header and actions, progress and problems, the leaderboard (graph
//! and ranked bars, from this run or published OCRBench scores) and the page-by-page
//! Compare (the page beside every model's reading of it, slips against the reference
//! marked).

use std::collections::HashSet;
use std::sync::Arc;
use std::time::Duration;

use gpui_kit::assets::IconName;
use gpui_kit::component::button::{Button, ButtonVariants};
use gpui_kit::component::checkbox::Checkbox;
use gpui_kit::component::select::{Select, SelectEvent, SelectState};
use gpui_kit::component::spinner::Spinner;
use gpui_kit::component::{ActiveTheme, Disableable, Selectable, Sizable, StyledExt};
use gpui_kit::prelude::FluentBuilder as _;
use gpui_kit::*;

use crate::api::{BenchRun, BenchState, DiffSpan, LeaderboardRow, ModelInfo, ModelRunState, PageView, ReferenceData, SettingsUpdate};
use crate::choice::Choice;
use crate::format;
use crate::state::{AppState, call};
use crate::ui;
use crate::views::bench_chart::{self, BarRow, ChartPoint, ChartSpec, Series};

const POLL: Duration = Duration::from_secs(1);

pub enum RunEvent {
    Closed,
    /// Something changed (stopped, re-run); select this run, if given.
    Changed(Option<String>),
    Deleted,
}

#[derive(Clone, Copy, PartialEq)]
enum Source {
    Run,
    V1,
    V2,
}

#[derive(Clone, Copy, PartialEq)]
enum XKey {
    Speed,
    Memory,
    Load,
}

impl XKey {
    fn label(self) -> &'static str {
        match self {
            XKey::Speed => "Seconds per page",
            XKey::Memory => "Peak memory",
            XKey::Load => "Load time",
        }
    }

    fn short(self) -> &'static str {
        match self {
            XKey::Speed => "Per page",
            XKey::Memory => "Peak RAM",
            XKey::Load => "Load time",
        }
    }

    fn of(self, r: &LeaderboardRow) -> Option<f64> {
        match self {
            XKey::Speed => r.seconds_per_page,
            XKey::Memory => r.peak_memory_mb,
            XKey::Load => r.load_seconds,
        }
    }

    fn format(self) -> fn(f64) -> String {
        match self {
            XKey::Memory => bench_chart::mb_tick,
            _ => bench_chart::sec_tick,
        }
    }
}

/// Short names for labels ("PaddleOCR Balanced — Chinese + English" -> "PaddleOCR
/// Balanced"); tooltips keep the full name.
pub fn short_name(name: &str) -> String {
    match name.split_once(" — ") {
        Some((head, tail)) if ["PaddleOCR", "Tesseract", "EasyOCR", "Ollama", "NVIDIA NIM"].contains(&head) => {
            format!("{head} {tail}")
        }
        Some((head, _)) => head.to_string(),
        None => name.to_string(),
    }
}

/// A model's family label ("PaddleOCR English" for every size of it), or its own name.
fn family_label(family: Option<&str>, name: &str) -> String {
    family.map_or_else(|| short_name(name), |f| f.replace(" — ", " "))
}

pub struct BenchRunPanel {
    state: Entity<AppState>,
    run: BenchRun,
    confirm_delete: bool,
    error: Option<String>,
    // Leaderboard.
    source: Source,
    x_key: XKey,
    zh: bool,
    best_size: bool,
    hidden: HashSet<String>,
    filter_open: bool,
    reference: Option<ReferenceData>,
    catalog: Option<Vec<ModelInfo>>,
    active_point: Option<String>,
    active_bar: Option<String>,
    // Compare.
    file_select: Entity<SelectState<Vec<Choice>>>,
    against_select: Entity<SelectState<Vec<Choice>>>,
    file_id: Option<String>,
    page: u32,
    against: Option<String>,
    page_view: Option<PageView>,
    image: Option<Arc<Image>>,
    compare_error: Option<String>,
    compare_request: u64,
    _poll: Option<Task<()>>,
    _subscriptions: Vec<Subscription>,
}

impl EventEmitter<RunEvent> for BenchRunPanel {}

impl BenchRunPanel {
    pub fn new(state: Entity<AppState>, run: BenchRun, window: &mut Window, cx: &mut Context<Self>) -> Self {
        // Start where there's something to compare: the first file with reference text.
        let file_id = run.files.iter().find(|f| f.has_reference).or(run.files.first()).map(|f| f.id.clone());
        let files: Vec<Choice> = run
            .files
            .iter()
            .map(|f| Choice::new(f.id.clone(), format!("{}{}", f.id, if f.has_reference { " · reference" } else { "" })))
            .collect();
        let mut against_choices = vec![Choice::new("", "nothing")];
        against_choices.extend(run.models.iter().map(|m| Choice::new(m.model_id.clone(), m.name.clone())));
        let file_select = cx.new(|cx| SelectState::new(files, None, window, cx));
        let against_select = cx.new(|cx| SelectState::new(against_choices, None, window, cx));
        if let Some(id) = &file_id {
            let id = SharedString::from(id.clone());
            file_select.update(cx, |s, cx| s.set_selected_value(&id, window, cx));
        }
        against_select.update(cx, |s, cx| s.set_selected_value(&SharedString::from(""), window, cx));
        let subscriptions = vec![
            cx.subscribe(&file_select, |this: &mut Self, _, event: &SelectEvent<Vec<Choice>>, cx| {
                let SelectEvent::Confirm(Some(value)) = event else { return };
                this.file_id = Some(value.to_string());
                this.page = 1;
                this.load_page(cx);
            }),
            cx.subscribe(&against_select, |this: &mut Self, _, event: &SelectEvent<Vec<Choice>>, cx| {
                let SelectEvent::Confirm(value) = event;
                this.against = value.as_ref().map(|v| v.to_string()).filter(|v| !v.is_empty());
                this.load_page(cx);
            }),
            cx.observe(&state, |_, _, cx| cx.notify()),
        ];
        let mut this = Self {
            state,
            run,
            confirm_delete: false,
            error: None,
            source: Source::Run,
            x_key: XKey::Speed,
            zh: false,
            best_size: false,
            hidden: HashSet::new(),
            filter_open: false,
            reference: None,
            catalog: None,
            active_point: None,
            active_bar: None,
            file_select,
            against_select,
            file_id,
            page: 1,
            against: None,
            page_view: None,
            image: None,
            compare_error: None,
            compare_request: 0,
            _poll: None,
            _subscriptions: subscriptions,
        };
        this.load(cx);
        this
    }

    fn busy(&self) -> bool {
        self.run.state.active()
    }

    /// The list's copy has no live leaderboard while running; follow the run itself.
    fn load(&mut self, cx: &mut Context<Self>) {
        let api = self.state.read(cx).api.clone();
        let id = self.run.id.clone();
        call(cx, api, move |api| api.get_benchmark(&id), |this, result, cx| {
            let Ok(run) = result else { return };
            let progressed = run.pages_done != this.run.pages_done || run.state != this.run.state;
            this.run = run;
            if progressed || this.page_view.is_none() {
                this.load_page(cx);
            }
            if this.busy() {
                this._poll = Some(cx.spawn(async move |this, cx| {
                    cx.background_executor().timer(POLL).await;
                    this.update(cx, |this, cx| this.load(cx)).ok();
                }));
            }
        })
        .detach();
    }

    fn load_page(&mut self, cx: &mut Context<Self>) {
        let Some(file_id) = self.file_id.clone() else { return };
        self.compare_error = None;
        self.compare_request += 1;
        let request = self.compare_request;
        let (api, run_id, page, against) = (self.state.read(cx).api.clone(), self.run.id.clone(), self.page, self.against.clone());
        call(
            cx,
            api,
            move |api| {
                let view = api.benchmark_page(&run_id, &file_id, page, against.as_deref())?;
                let image = api.benchmark_image(&run_id, &file_id, page).ok();
                Ok((view, image))
            },
            move |this, result, _| {
                if request != this.compare_request {
                    return;
                }
                match result {
                    Ok((view, image)) => {
                        this.page_view = Some(view);
                        this.image = image.map(|bytes| Arc::new(Image::from_bytes(ImageFormat::Png, bytes)));
                    }
                    Err(err) => this.compare_error = Some(err),
                }
            },
        )
        .detach();
    }

    fn act(&mut self, cx: &mut Context<Self>, what: &'static str) {
        self.error = None;
        let api = self.state.read(cx).api.clone();
        let id = self.run.id.clone();
        match what {
            "cancel" => call(cx, api, move |api| api.cancel_benchmark(&id), |this, r, cx| match r {
                Ok(_) => cx.emit(RunEvent::Changed(None)),
                Err(err) => this.error = Some(err),
            })
            .detach(),
            "rerun" => call(cx, api, move |api| api.rerun_benchmark(&id), |this, r, cx| match r {
                Ok(next) => cx.emit(RunEvent::Changed(Some(next.id))),
                Err(err) => this.error = Some(err),
            })
            .detach(),
            "report" => call(cx, api, move |api| api.open_benchmark_report(&id, "file"), |this, r, _| {
                if let Err(err) = r {
                    this.error = Some(err);
                }
            })
            .detach(),
            "delete" => call(cx, api, move |api| api.delete_benchmark(&id), |this, r, cx| match r {
                Ok(()) => cx.emit(RunEvent::Deleted),
                Err(err) => this.error = Some(err),
            })
            .detach(),
            _ => {}
        }
    }

    fn set_source(&mut self, source: Source, cx: &mut Context<Self>) {
        self.source = source;
        self.hidden.clear();
        if source != Source::Run && (self.reference.is_none() || self.catalog.is_none()) {
            let api = self.state.read(cx).api.clone();
            call(cx, api, |api| Ok((api.benchmark_reference().ok(), api.list_models().unwrap_or_default())), |this, r, _| {
                if let Ok((reference, catalog)) = r {
                    this.reference = reference;
                    this.catalog = Some(catalog);
                }
            })
            .detach();
        }
        cx.notify();
    }

    fn segmented<T: Copy + PartialEq + 'static>(
        &self,
        id: &str,
        value: T,
        options: &[(T, &str)],
        set: fn(&mut Self, T, &mut Context<Self>),
        cx: &mut Context<Self>,
    ) -> Div {
        let mut group = div().h_flex().gap_0p5().p_0p5().rounded_full().bg(cx.theme().muted);
        for (i, (v, label)) in options.iter().enumerate() {
            let v = *v;
            group = group.child(
                Button::new(SharedString::from(format!("{id}-{i}")))
                    .xsmall()
                    .ghost()
                    .rounded(px(999.))
                    .label(label.to_string())
                    .selected(v == value)
                    .on_click(cx.listener(move |this, _, _, cx| set(this, v, cx))),
            );
        }
        group
    }

    fn run_details(r: &LeaderboardRow, scored: bool) -> Vec<(String, String)> {
        let accuracy = if scored {
            [Some(bench_chart::pct(r.accuracy)), bench_chart::plus_minus(r.accuracy_margin)].into_iter().flatten().collect::<Vec<_>>().join(" ")
        } else {
            "–".into()
        };
        let mut rows = vec![
            ("Accuracy".into(), accuracy),
            ("Per page".into(), bench_chart::secs(r.seconds_per_page, None)),
            ("Load".into(), bench_chart::secs(r.load_seconds, Some(1))),
            (
                "Peak RAM".into(),
                if r.peak_memory_mb.is_none() && r.memory_note.is_some() { "not measured".into() } else { bench_chart::mb(r.peak_memory_mb) },
            ),
            ("Word errors".into(), bench_chart::pct(r.wer)),
            ("Confidence".into(), bench_chart::pct(r.mean_confidence)),
            ("Pages failed".into(), r.pages_failed.to_string()),
        ];
        if scored && r.scored_units > 0 {
            rows.push(("Scored on".into(), format::plural(r.scored_units as usize, "reference", "references")));
        }
        rows
    }

    fn leaderboard(&mut self, cx: &mut Context<Self>) -> Div {
        let scored = self.run.summary.as_ref().is_some_and(|s| s.ranked_by == "cer");
        let rows: Vec<LeaderboardRow> = self.run.summary.as_ref().map(|s| s.leaderboard.clone()).unwrap_or_default();
        let y_of = |r: &LeaderboardRow| if scored { r.accuracy } else { r.mean_confidence };
        let family_of = |r: &LeaderboardRow| r.family.clone().unwrap_or_else(|| r.model_id.clone());
        let has_sizes = rows.iter().enumerate().any(|(i, r)| {
            r.family.is_some() && rows.iter().position(|q| q.family == r.family) != Some(i)
        });
        let read: Vec<&LeaderboardRow> = rows.iter().filter(|r| r.pages_read > 0).collect();
        let visible: Vec<&LeaderboardRow> = read.iter().copied().filter(|r| !self.hidden.contains(&r.model_id)).collect();
        let shown: Vec<&LeaderboardRow> = if self.best_size {
            // One entry per family: the size with the best score (the first, on a tie).
            visible
                .iter()
                .copied()
                .filter(|r| {
                    let fam = family_of(r);
                    let best = visible
                        .iter()
                        .filter(|q| family_of(q) == fam)
                        .fold(None::<&LeaderboardRow>, |best, q| match best {
                            Some(b) if y_of(b).unwrap_or(f64::NEG_INFINITY) >= y_of(q).unwrap_or(f64::NEG_INFINITY) => Some(b),
                            _ => Some(q),
                        });
                    best.is_some_and(|b| b.model_id == r.model_id)
                })
                .collect()
        } else {
            visible.clone()
        };
        let x = self.x_key;
        let default_id = self.state.read(cx).default_model_id().map(str::to_string);

        // --- this run
        let run_points: Vec<ChartPoint> = shown
            .iter()
            .filter(|r| x.of(r).is_some() && y_of(r).is_some())
            .map(|r| ChartPoint {
                id: r.model_id.clone(),
                name: r.name.clone(),
                family: family_of(r),
                label: family_label(r.family.as_deref(), &r.name),
                variant: r.variant.clone(),
                series: Series::of(&r.engine),
                x: x.of(r).unwrap().max(0.001),
                y: y_of(r).unwrap() * 100.0,
                hollow: false,
                rows: Self::run_details(r, scored),
            })
            .collect();
        let unplotted: Vec<&LeaderboardRow> = shown.iter().copied().filter(|r| x.of(r).is_none() || y_of(r).is_none()).collect();

        // --- published scores
        let v1 = self.source == Source::V1;
        let ref_max = self
            .reference
            .as_ref()
            .and_then(|r| r.benchmarks.get(if v1 { "ocrbench_v1" } else { "ocrbench_v2" }))
            .map_or(if v1 { 1000.0 } else { 100.0 }, |b| b.max);
        struct RefItem {
            id: String,
            label: String,
            engine: String,
            download_mb: f64,
            value: f64,
            self_reported: bool,
            source: String,
            url: String,
            installed: bool,
        }
        let mut ref_items: Vec<RefItem> = Vec::new();
        if let (Some(reference), Some(catalog)) = (&self.reference, &self.catalog) {
            if self.source != Source::Run {
                for m in &reference.models {
                    let Some(info) = catalog.iter().find(|c| c.id == m.model_id) else { continue };
                    let (value, self_reported, source, url) = if v1 {
                        match &m.scores.ocrbench_v1 {
                            Some(s) => (Some(s.value), s.self_reported, s.source.clone(), s.url.clone()),
                            None => continue,
                        }
                    } else {
                        match &m.scores.ocrbench_v2 {
                            Some(s) => (if self.zh { s.zh } else { s.en }, s.self_reported, s.source.clone(), s.url.clone()),
                            None => continue,
                        }
                    };
                    let Some(value) = value else { continue };
                    ref_items.push(RefItem {
                        id: m.model_id.clone(),
                        label: m.label.clone(),
                        engine: info.engine.clone(),
                        download_mb: info.approx_download_mb,
                        value,
                        self_reported,
                        source,
                        url,
                        installed: info.status == crate::api::ModelStatus::Ready
                            || self.run.models.iter().any(|r| r.model_id == m.model_id),
                    });
                }
            }
        }
        let ref_shown: Vec<&RefItem> = ref_items.iter().filter(|i| !self.hidden.contains(&i.id)).collect();
        let score_text = |v: f64| if v1 { format!("{v}") } else { format!("{v:.1}") };
        let split_name = if v1 { "OCRBench v1".to_string() } else { format!("OCRBench v2 {}", if self.zh { "ZH" } else { "EN" }) };
        let ref_points: Vec<ChartPoint> = ref_shown
            .iter()
            .map(|i| ChartPoint {
                id: i.id.clone(),
                name: i.label.clone(),
                family: i.id.clone(),
                label: format!("{}{}", i.label, if i.self_reported { " *" } else { "" }),
                variant: None,
                series: Series::of(&i.engine),
                x: i.download_mb.max(1.0),
                y: i.value,
                hollow: !i.installed,
                rows: vec![
                    (split_name.clone(), format!("{} / {ref_max}", score_text(i.value))),
                    ("Download".into(), format::mb(i.download_mb)),
                    ("Reported by".into(), if i.self_reported { "the model's makers".into() } else { "OCRBench leaderboard".into() }),
                    ("Here".into(), if i.installed { "installed".into() } else { "not installed".into() }),
                ],
            })
            .collect();

        let points = if self.source == Source::Run { run_points } else { ref_points };
        let series: Vec<Series> = Series::ORDER.into_iter().filter(|s| points.iter().any(|p| p.series == *s)).collect();
        let filter_items: Vec<(String, String, Series)> = if self.source == Source::Run {
            read.iter()
                .map(|r| {
                    let label = match &r.variant {
                        Some(v) => format!("{} [{}]", family_label(r.family.as_deref(), &r.name), v.to_lowercase()),
                        None => short_name(&r.name),
                    };
                    (r.model_id.clone(), label, Series::of(&r.engine))
                })
                .collect()
        } else {
            ref_items.iter().map(|i| (i.id.clone(), i.label.clone(), Series::of(&i.engine))).collect()
        };

        let empty: Option<&str> = if self.source == Source::Run {
            if read.is_empty() {
                Some(if self.busy() { "Models appear here as they finish reading." } else { "No model finished reading, so there's nothing to rank." })
            } else if visible.is_empty() {
                Some("No models selected.")
            } else {
                None
            }
        } else if self.reference.is_none() || self.catalog.is_none() {
            Some("Loading the published scores…")
        } else if ref_items.is_empty() {
            Some("No model in DocBox's catalog has a published score on this benchmark.")
        } else if ref_shown.is_empty() {
            Some("No models selected.")
        } else {
            None
        };

        // Controls.
        let mut controls = div().h_flex().flex_wrap().gap_2().child(self.segmented(
            "source",
            self.source,
            &[(Source::Run, "This run"), (Source::V1, "OCRBench v1"), (Source::V2, "OCRBench v2")],
            |this, v, cx| this.set_source(v, cx),
            cx,
        ));
        if self.source == Source::Run {
            controls = controls.child(self.segmented(
                "cost",
                self.x_key,
                &[(XKey::Speed, XKey::Speed.short()), (XKey::Memory, XKey::Memory.short()), (XKey::Load, XKey::Load.short())],
                |this, v, cx| {
                    this.x_key = v;
                    cx.notify();
                },
                cx,
            ));
            if has_sizes {
                controls = controls.child(self.segmented(
                    "sizes",
                    self.best_size,
                    &[(false, "Every size"), (true, "Best size")],
                    |this, v, cx| {
                        this.best_size = v;
                        cx.notify();
                    },
                    cx,
                ));
            }
        }
        if self.source == Source::V2 {
            controls = controls.child(self.segmented(
                "split",
                self.zh,
                &[(false, "English"), (true, "Chinese")],
                |this, v, cx| {
                    this.zh = v;
                    cx.notify();
                },
                cx,
            ));
        }
        if filter_items.len() > 1 {
            let shown_count = filter_items.iter().filter(|(id, _, _)| !self.hidden.contains(id)).count();
            controls = controls.child(
                div().ml_auto().child(
                    Button::new("model-filter")
                        .small()
                        .outline()
                        .label(format!("Models ({shown_count}/{})", filter_items.len()))
                        .icon(if self.filter_open { IconName::ChevronUp } else { IconName::ChevronDown })
                        .on_click(cx.listener(|this, _, _, cx| {
                            this.filter_open = !this.filter_open;
                            cx.notify();
                        })),
                ),
            );
        }

        let mut section = div().v_flex().gap_3().child(ui::section_label("Leaderboard", cx)).child(controls);
        if self.filter_open && filter_items.len() > 1 {
            let mut list = div().h_flex().flex_wrap().gap_x_4().gap_y_1();
            for (id, label, series) in &filter_items {
                let key = id.clone();
                list = list.child(
                    div()
                        .h_flex()
                        .gap_1()
                        .child(div().size(px(8.)).rounded_full().bg(series.color()))
                        .child(
                            Checkbox::new(SharedString::from(format!("show-{id}")))
                                .label(label.clone())
                                .checked(!self.hidden.contains(id))
                                .on_change(cx.listener(move |this, checked: &bool, _, cx| {
                                    if *checked {
                                        this.hidden.remove(&key);
                                    } else {
                                        this.hidden.insert(key.clone());
                                    }
                                    cx.notify();
                                })),
                        ),
                );
            }
            section = section.child(
                ui::card(cx)
                    .gap_2()
                    .p_3()
                    .child(list)
                    .child(div().child(Button::new("show-all-models").xsmall().link().label("Show all").on_click(cx.listener(|this, _, _, cx| {
                        this.hidden.clear();
                        cx.notify();
                    })))),
            );
        }

        let mut body = ui::card(cx).gap_3().p_4();
        if let Some(text) = empty {
            body = body.items_center().py_10().child(ui::muted(text, cx)).when(text == "No models selected.", |d| {
                d.child(Button::new("show-all-empty").small().outline().label("Show all").on_click(cx.listener(|this, _, _, cx| {
                    this.hidden.clear();
                    cx.notify();
                })))
            });
            return section.child(body);
        }
        if let Some(legend) = bench_chart::legend(&series, cx) {
            body = body.child(legend);
        }
        let spec = if self.source == Source::Run {
            ChartSpec {
                title: if scored { "Accuracy (1 − character error rate)".into() } else { "Mean confidence (no reference text)".into() },
                x_label: x.label().into(),
                x_format: x.format(),
                y_format: |v| format!("{v}%"),
                y_cap: 100.0,
            }
        } else {
            ChartSpec {
                title: if v1 {
                    "OCRBench v1 score (of 1,000)".into()
                } else {
                    format!("OCRBench v2 {} (of 100)", if self.zh { "Chinese" } else { "English" })
                },
                x_label: "Download size".into(),
                x_format: bench_chart::mb_tick,
                y_format: |v| format!("{v}"),
                y_cap: ref_max,
            }
        };
        let this = cx.entity().downgrade();
        let hover_point = move |id: Option<String>, _: &mut Window, cx: &mut App| {
            if let Some(this) = this.upgrade() {
                this.update(cx, |this, cx| {
                    if id.is_some() || this.active_point.is_some() {
                        this.active_point = id;
                        cx.notify();
                    }
                });
            }
        };
        body = body.child(if points.is_empty() {
            div().py_6().h_flex().justify_center().child(ui::muted(format!("No model has a {} figure to plot.", x.short().to_lowercase()), cx)).into_any_element()
        } else {
            div().id("chart-scroll").overflow_x_scroll().child(bench_chart::chart(&points, &spec, self.active_point.as_deref(), hover_point, cx)).into_any_element()
        });
        if self.source == Source::Run && !unplotted.is_empty() {
            let why: Vec<String> = unplotted
                .iter()
                .map(|r| {
                    let reason = if x.of(r).is_none() {
                        match (&r.memory_note, x) {
                            (Some(note), XKey::Memory) => {
                                let mut c = note.chars();
                                c.next().map_or(String::new(), |f| f.to_lowercase().collect::<String>() + c.as_str())
                            }
                            _ => format!("no {} figure", x.short().to_lowercase()),
                        }
                    } else {
                        "no score yet".into()
                    };
                    format!("{} ({reason})", short_name(&r.name))
                })
                .collect();
            body = body.child(ui::small_muted(format!("Not on the graph: {}.", why.join("; ")), cx));
        }
        if self.source == Source::Run && !scored {
            body = body.child(ui::small_muted(
                "Without reference text the height is each model's own confidence, which isn't accuracy. Add name.gt.txt files to rank by accuracy.",
                cx,
            ));
        }

        let this = cx.entity().downgrade();
        let hover_bar = move |id: Option<String>, _: &mut Window, cx: &mut App| {
            if let Some(this) = this.upgrade() {
                this.update(cx, |this, cx| {
                    if id.is_some() || this.active_bar.is_some() {
                        this.active_bar = id;
                        cx.notify();
                    }
                });
            }
        };
        let bars_el = if self.source == Source::Run {
            let mut sorted = shown.clone();
            sorted.sort_by(|a, b| y_of(b).unwrap_or(-1.0).total_cmp(&y_of(a).unwrap_or(-1.0)));
            let rows: Vec<BarRow> = sorted
                .iter()
                .map(|r| {
                    let y = y_of(r);
                    let m = if scored { r.accuracy_margin } else { None };
                    let is_default = default_id.as_deref() == Some(r.model_id.as_str());
                    let state = self.state.clone();
                    let id = r.model_id.clone();
                    BarRow {
                        id: r.model_id.clone(),
                        name: r.name.clone(),
                        label: family_label(r.family.as_deref(), &r.name),
                        variant: r.variant.clone(),
                        series: Series::of(&r.engine),
                        value: y,
                        low: y.zip(m).map(|(y, m)| y - m),
                        high: y.zip(m).map(|(y, m)| y + m),
                        display: bench_chart::pct(y),
                        margin: bench_chart::plus_minus(m),
                        cells: vec![
                            bench_chart::secs(r.seconds_per_page, None).into_any_element(),
                            (if r.peak_memory_mb.is_none() && r.memory_note.is_some() {
                                "not measured".to_string()
                            } else {
                                bench_chart::mb(r.peak_memory_mb)
                            })
                            .into_any_element(),
                            bench_chart::secs(r.load_seconds, Some(1)).into_any_element(),
                        ],
                        details: Self::run_details(r, scored),
                        note: (r.pages_failed > 0).then(|| format!("{} failed", format::plural(r.pages_failed as usize, "page", "pages"))),
                        action: Some(if is_default {
                            ui::fit_chip(true, "Default").into_any_element()
                        } else {
                            Button::new(SharedString::from(format!("bench-default-{}", r.model_id)))
                                .xsmall()
                                .outline()
                                .label("Set as default")
                                .on_click(move |_, _, cx| {
                                    let patch = SettingsUpdate { default_model_id: Some(id.clone()), ..Default::default() };
                                    state.update(cx, |s, cx| s.update_settings(patch, cx));
                                })
                                .into_any_element()
                        }),
                    }
                })
                .collect();
            bench_chart::bars(
                rows,
                if scored { "Accuracy" } else { "Confidence" },
                &["Per page", "Peak RAM", "Load"],
                |t| format!("{}%", (t * 100.0).round() as i64),
                true,
                self.active_bar.as_deref(),
                hover_bar,
                cx,
            )
        } else {
            let mut sorted = ref_shown.clone();
            sorted.sort_by(|a, b| b.value.total_cmp(&a.value));
            let rows: Vec<BarRow> = sorted
                .iter()
                .map(|i| {
                    let url = i.url.clone();
                    BarRow {
                        id: i.id.clone(),
                        name: i.label.clone(),
                        label: i.label.clone(),
                        variant: None,
                        series: Series::of(&i.engine),
                        value: Some(i.value / ref_max),
                        low: None,
                        high: None,
                        display: score_text(i.value),
                        margin: None,
                        cells: vec![
                            format::mb(i.download_mb).into_any_element(),
                            Button::new(SharedString::from(format!("src-{}", i.id)))
                                .link()
                                .xsmall()
                                .label(format!("{}{}", i.source, if i.self_reported { " *" } else { "" }))
                                .on_click(move |_, _, cx| cx.open_url(&url))
                                .into_any_element(),
                        ],
                        details: vec![
                            ("Score".into(), format!("{} / {ref_max}", score_text(i.value))),
                            ("Download".into(), format::mb(i.download_mb)),
                            ("Reported by".into(), if i.self_reported { "the model's makers".into() } else { "OCRBench leaderboard".into() }),
                            ("Here".into(), if i.installed { "installed".into() } else { "not installed".into() }),
                        ],
                        note: None,
                        action: None,
                    }
                })
                .collect();
            bench_chart::bars(rows, "Score", &["Download", "Source"], move |t| format!("{}", (t * ref_max).round() as i64), false, self.active_bar.as_deref(), hover_bar, cx)
        };
        body = body.child(div().id("bars-scroll").overflow_x_scroll().pt_3().border_t_1().border_color(cx.theme().border).child(bars_el));
        if self.source == Source::Run && scored && shown.iter().any(|r| r.accuracy_margin.is_some()) {
            body = body.child(ui::small_muted(
                "± is a 95% interval: how much accuracy varies between the pages or documents with reference text. Fewer of them means a wider interval.",
                cx,
            ));
        }
        if self.source != Source::Run {
            if let Some(reference) = &self.reference {
                let about = reference.benchmarks.get(if v1 { "ocrbench_v1" } else { "ocrbench_v2" }).map(|b| b.about.clone()).unwrap_or_default();
                let unplaced: Vec<String> =
                    self.run.models.iter().filter(|m| !ref_items.iter().any(|i| i.id == m.model_id)).map(|m| m.name.clone()).collect();
                let mut notes = div().v_flex().gap_1().child(ui::small_muted(
                    format!(
                        "Published scores for reference, not measured on your files. {about} * Reported by the model's makers. Hollow points aren't installed here."
                    ),
                    cx,
                ));
                if !unplaced.is_empty() {
                    notes = notes.child(ui::small_muted(
                        format!("Not on {}: {}.", if v1 { "OCRBench v1" } else { "OCRBench v2" }, unplaced.join(", ")),
                        cx,
                    ));
                }
                for n in &reference.notes {
                    notes = notes.child(ui::small_muted(format!("• {n}"), cx));
                }
                notes = notes.child(ui::small_muted(format!("Scores checked {}.", reference.checked), cx));
                body = body.child(notes);
            }
        }
        section.child(body)
    }

    fn diff_text(spans: &[DiffSpan], cx: &App) -> Div {
        // Changed or added text highlighted, missed reference text struck through.
        let mut text = div().h_flex().flex_wrap().text_sm();
        for s in spans {
            let piece = match s.op.as_str() {
                "equal" => div().child(s.text.clone()),
                "delete" => div().line_through().text_color(cx.theme().danger.opacity(0.7)).bg(cx.theme().danger.opacity(0.1)).child(s.reference.clone()),
                _ => div().text_color(cx.theme().danger).bg(cx.theme().danger.opacity(0.2)).child(s.text.clone()),
            };
            text = text.child(piece);
        }
        text
    }

    fn compare(&mut self, cx: &mut Context<Self>) -> Option<Div> {
        let file = self.file_id.as_ref().and_then(|id| self.run.files.iter().find(|f| &f.id == id))?.clone();
        let default_id = self.state.read(cx).default_model_id().map(str::to_string);
        let best = self
            .run
            .summary
            .as_ref()
            .and_then(|s| s.leaderboard.iter().find(|r| Some(&r.model_id) == s.best_model_id.as_ref()))
            .cloned();
        let mut header = div()
            .h_flex()
            .flex_wrap()
            .justify_between()
            .gap_3()
            .child(ui::section_label("Compare", cx))
            .child(div().w(px(300.)).child(Select::new(&self.file_select).small()));
        if file.pages > 1 {
            let pages = file.pages;
            header = header.child(
                div()
                    .h_flex()
                    .gap_1()
                    .text_sm()
                    .child(Button::new("prev-page").ghost().small().icon(IconName::ChevronLeft).disabled(self.page <= 1).on_click(cx.listener(|this, _, _, cx| {
                        this.page = this.page.saturating_sub(1).max(1);
                        this.load_page(cx);
                    })))
                    .child(format!("Page {} of {pages}", self.page))
                    .child(Button::new("next-page").ghost().small().icon(IconName::ChevronRight).disabled(self.page >= pages).on_click(cx.listener(move |this, _, _, cx| {
                        this.page = (this.page + 1).min(pages);
                        this.load_page(cx);
                    }))),
            );
        }
        let image = div()
            .v_flex()
            .gap_2()
            .w(px(320.))
            .flex_none()
            .child(
                div()
                    .min_h(px(200.))
                    .rounded_md()
                    .bg(gpui_kit::white())
                    .p_3()
                    .overflow_hidden()
                    .when_some(self.image.clone(), |d, image| d.child(img(image).w_full().max_h(px(520.)).object_fit(ObjectFit::Contain))),
            )
            .child(ui::small_muted(file.id.clone(), cx).truncate());

        let mut right = div().v_flex().flex_basis(px(320.)).flex_grow(1.).flex_shrink(1.).min_w_0().gap_3();
        let view = self.page_view.clone();
        if view.as_ref().is_some_and(|v| v.reference_kind == "reference") {
            let reference = view.as_ref().and_then(|v| v.reference.clone()).unwrap_or_default();
            right = right.child(
                div()
                    .v_flex()
                    .gap_1()
                    .px_4()
                    .py_3()
                    .rounded_md()
                    .bg(cx.theme().muted)
                    .child(ui::small_muted("REFERENCE TEXT", cx))
                    .child(div().text_sm().child(reference.trim().to_string())),
            );
        } else {
            right = right.child(
                div()
                    .h_flex()
                    .flex_wrap()
                    .gap_2()
                    .px_4()
                    .py_3()
                    .rounded_md()
                    .bg(cx.theme().muted)
                    .child(ui::muted("No reference text for this page. Compare against", cx))
                    .child(div().w(px(240.)).child(Select::new(&self.against_select).small())),
            );
        }
        match &view {
            None => {
                right = right.child(div().h_flex().gap_2().py_6().child(Spinner::new().small()).child(ui::muted("Loading the readings", cx)));
            }
            Some(v) if v.reads.is_empty() => {
                right = right.child(div().py_6().child(ui::muted("No model has read this page yet.", cx)));
            }
            Some(v) => {
                let mut list = div().v_flex().gap_2();
                for r in &v.reads {
                    let chip = if r.error.is_some() {
                        Some(gpui_kit::component::tag::Tag::danger().small().child("Failed"))
                    } else {
                        r.slips.map(|n| if n == 0 { ui::fit_chip(true, "Exact") } else { ui::fit_chip(false, format::plural(n as usize, "slip", "slips")) })
                    };
                    list = list.child(
                        ui::card(cx)
                            .px_4()
                            .py_3()
                            .gap_1()
                            .child(
                                div()
                                    .h_flex()
                                    .flex_wrap()
                                    .gap_2()
                                    .child(div().flex_1().min_w_0().font_medium().truncate().child(r.name.clone()))
                                    .when_some(chip, |d, c| d.child(c))
                                    .when_some(r.seconds, |d, s| d.child(ui::small_muted(format!("{s:.2} s"), cx))),
                            )
                            .child(match (&r.error, r.diff.is_empty()) {
                                (Some(err), _) => ui::error_text(err.clone(), cx),
                                (None, false) => Self::diff_text(&r.diff, cx),
                                (None, true) => div().text_sm().child(if r.text.trim().is_empty() { "No text found.".to_string() } else { r.text.trim().to_string() }),
                            }),
                    );
                }
                right = right.child(list);
                let lines = v.reference.as_ref().map_or(0, |r| r.lines().filter(|l| !l.trim().is_empty()).count());
                let mut foot = div().h_flex().flex_wrap().justify_between().gap_3().child(ui::small_muted(
                    format!(
                        "{}{}",
                        format::plural(v.reads.len(), "model", "models"),
                        if lines > 0 { format!(" · {} compared", format::plural(lines, "line", "lines")) } else { String::new() }
                    ),
                    cx,
                ));
                if let Some(best) = best.filter(|b| Some(&b.model_id) != default_id.as_ref()) {
                    let state = self.state.clone();
                    let id = best.model_id.clone();
                    foot = foot.child(Button::new("compare-default").small().outline().label(format!("Set {} as default", best.name)).on_click(move |_, _, cx| {
                        let patch = SettingsUpdate { default_model_id: Some(id.clone()), ..Default::default() };
                        state.update(cx, |s, cx| s.update_settings(patch, cx));
                    }));
                }
                right = right.child(foot);
            }
        }
        Some(
            div()
                .v_flex()
                .gap_2()
                .child(header)
                .when_some(self.compare_error.clone(), |d, err| d.child(ui::notice(err, cx)))
                .child(ui::card(cx).h_flex().flex_wrap().items_start().gap_5().p_5().child(image).child(right)),
        )
    }
}

impl Render for BenchRunPanel {
    fn render(&mut self, _: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        let run = self.run.clone();
        let busy = self.busy();
        let total = run.pages_total * run.models.len() as u32;
        let current = run.models.iter().find(|m| Some(&m.model_id) == run.current_model_id.as_ref());
        let created = format_time(run.created_at);
        let source = match run.source.as_str() {
            "app" => Some("started here"),
            "cli" => Some("from the command line"),
            "mcp" => Some("from an AI agent"),
            _ => None,
        };
        let meta = [
            Some(format::plural(run.files.len(), "file", "files")),
            Some(format::plural(run.pages_total as usize, "page", "pages")),
            Some(format::plural(run.models.len(), "model", "models")),
            Some(created),
            source.map(str::to_string),
        ]
        .into_iter()
        .flatten()
        .collect::<Vec<_>>()
        .join(" · ");

        let mut actions = div().h_flex().flex_wrap().gap_1();
        actions = actions.child(if busy {
            Button::new("bench-stop").small().outline().icon(IconName::Square).label("Stop").on_click(cx.listener(|this, _, _, cx| this.act(cx, "cancel")))
        } else {
            Button::new("bench-rerun").small().outline().icon(IconName::RotateCw).label("Run again").on_click(cx.listener(|this, _, _, cx| this.act(cx, "rerun")))
        });
        if !busy {
            actions = actions.child(
                Button::new("bench-report").small().outline().icon(IconName::FileText).label("Report").on_click(cx.listener(|this, _, _, cx| this.act(cx, "report"))),
            );
        }
        if self.confirm_delete {
            actions = actions.child(
                div()
                    .h_flex()
                    .gap_1()
                    .pl_3()
                    .rounded_full()
                    .bg(cx.theme().muted)
                    .text_sm()
                    .child("Delete this benchmark and its results?")
                    .child(Button::new("bench-delete-yes").small().danger().label("Delete").on_click(cx.listener(|this, _, _, cx| this.act(cx, "delete"))))
                    .child(Button::new("bench-delete-no").small().ghost().label("Keep").on_click(cx.listener(|this, _, _, cx| {
                        this.confirm_delete = false;
                        cx.notify();
                    }))),
            );
        } else if !busy {
            actions = actions.child(Button::new("bench-delete").small().ghost().icon(IconName::Trash).tooltip("Delete benchmark").on_click(cx.listener(|this, _, _, cx| {
                this.confirm_delete = true;
                cx.notify();
            })));
        }
        actions = actions.child(Button::new("bench-close").small().ghost().icon(IconName::X).tooltip("Close").on_click(cx.listener(|_, _, _, cx| cx.emit(RunEvent::Closed))));

        // Models that failed, or read none of their pages, say why they aren't ranked.
        let problems: Vec<(String, String)> = run
            .models
            .iter()
            .filter_map(|m| {
                if m.error.as_deref() == Some("Cancelled") {
                    return None;
                }
                if let Some(err) = &m.error {
                    return Some((m.name.clone(), err.lines().next().unwrap_or("").to_string()));
                }
                let row = run.summary.as_ref()?.leaderboard.iter().find(|r| r.model_id == m.model_id)?;
                (m.state == ModelRunState::Done && row.pages_read == 0 && row.pages_failed > 0)
                    .then(|| (m.name.clone(), format!("read none of its {}", format::plural(row.pages_failed as usize, "page", "pages"))))
            })
            .collect();

        let leaderboard = self.leaderboard(cx);
        let compare = self.compare(cx);
        let mut body = div().v_flex().gap_5().px_5().py_4();
        if let Some(err) = &self.error {
            body = body.child(ui::notice(err.clone(), cx));
        }
        if busy {
            let doing = match current {
                Some(m) if m.state == ModelRunState::Installing => format!("Installing {}", m.name),
                Some(m) => format!("{} is reading · {} of {total} pages", m.name, run.pages_done),
                None => "Starting".into(),
            };
            body = body.child(
                div()
                    .v_flex()
                    .gap_2()
                    .child(div().h_flex().gap_2().child(Spinner::new().small()).child(ui::muted(doing, cx)))
                    .child(ui::progress_bar("bench-progress", if total > 0 { 100.0 * run.pages_done as f64 / total as f64 } else { 0.0 })),
            );
        }
        if run.state == BenchState::Error {
            body = body.child(ui::notice(run.error.clone().unwrap_or_else(|| "The benchmark failed.".into()), cx));
        }
        if run.state == BenchState::Interrupted {
            body = body.child(ui::notice("DocBox stopped before this benchmark finished. Run it again to finish it.", cx));
        }
        if !problems.is_empty() {
            let mut list = div().v_flex().gap_0p5();
            for (name, text) in problems {
                list = list.child(div().h_flex().gap_1().text_sm().child(div().font_medium().child(format!("{name}:"))).child(text));
            }
            body = body.child(div().px_4().py_3().rounded_lg().border_1().border_color(cx.theme().warning).child(list));
        }
        if run.summary.as_ref().is_some_and(|s| s.ranked_by == "speed") {
            body = body.child(ui::small_muted(
                "No reference text, so models are ranked by speed. Add name.gt.txt files with the correct text to rank by accuracy.",
                cx,
            ));
        }
        body = body.child(leaderboard);
        if let Some(compare) = compare {
            body = body.child(compare);
        }

        ui::card(cx)
            .child(
                div()
                    .h_flex()
                    .flex_wrap()
                    .items_start()
                    .gap_3()
                    .px_5()
                    .py_4()
                    .border_b_1()
                    .border_color(cx.theme().border)
                    .child(div().v_flex().flex_basis(px(240.)).flex_grow(1.).flex_shrink(1.).min_w_0().child(div().text_xl().font_semibold().child(run.name.clone())).child(ui::small_muted(meta, cx)))
                    .child(actions),
            )
            .child(body)
    }
}

/// A Unix time as the local date and time, "21 Nov 2026, 16:05".
fn format_time(secs: f64) -> String {
    use chrono::TimeZone as _;
    chrono::Local
        .timestamp_opt(secs as i64, 0)
        .single()
        .map_or_else(String::new, |t| t.format("%-d %b %Y, %H:%M").to_string())
}
