//! Benchmarks: the local OCR test bench. Drop documents (a folder is one batch), pick
//! models, and every model reads every page; each run is a card under Batches, and opening
//! one shows the leaderboard and the page-by-page Compare. Runs started from the CLI or by
//! an AI agent (MCP) appear here too.

use std::collections::BTreeSet;
use std::path::{Path, PathBuf};
use std::time::Duration;

use gpui_kit::assets::IconName;
use gpui_kit::component::button::{Button, ButtonVariants};
use gpui_kit::component::checkbox::Checkbox;
use gpui_kit::component::input::{Input, InputState};
use gpui_kit::component::{ActiveTheme, Disableable, Icon, Sizable, StyledExt};
use gpui_kit::prelude::FluentBuilder as _;
use gpui_kit::*;

use crate::api::{BenchRun, BenchState, ModelInfo, ModelRunState, ModelStatus};
use crate::format;
use crate::state::{AppState, View, call};
use crate::ui;
use crate::views::bench_run::{BenchRunPanel, RunEvent};

pub use crate::views::bench_run::short_name;

const POLL: Duration = Duration::from_secs(1);
const BATCH_COUNT: usize = 8;

/// A document to read, or a reference text next to one (invoice.gt.txt, invoice.p2.gt.txt),
/// with its path relative to what was picked, so references stay next to their documents.
#[derive(Clone, Debug, PartialEq)]
struct Picked {
    file: PathBuf,
    path: String,
}

fn is_reference(path: &str) -> bool {
    path.to_ascii_lowercase().ends_with(".gt.txt")
}

fn is_document(path: &str) -> bool {
    crate::api::is_readable(Path::new(path))
}

/// Everything useful under the picked paths: files as they are, folders walked (named after
/// the folder, so `Invoices/march/a.pdf`).
fn collect(paths: &[PathBuf]) -> Vec<Picked> {
    fn walk(dir: &Path, prefix: &str, out: &mut Vec<Picked>) {
        let Ok(entries) = std::fs::read_dir(dir) else { return };
        let mut entries: Vec<_> = entries.flatten().map(|e| e.path()).collect();
        entries.sort();
        for path in entries {
            let name = path.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default();
            if path.is_dir() {
                walk(&path, &format!("{prefix}{name}/"), out);
            } else {
                out.push(Picked { file: path, path: format!("{prefix}{name}") });
            }
        }
    }
    let mut out = Vec::new();
    for path in paths {
        let name = path.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default();
        if path.is_dir() {
            walk(path, &format!("{name}/"), &mut out);
        } else {
            out.push(Picked { file: path.clone(), path: name });
        }
    }
    out.retain(|p| is_document(&p.path) || is_reference(&p.path));
    out
}

fn state_label(run: &BenchRun) -> String {
    let total = run.pages_total * run.models.len() as u32;
    match run.state {
        BenchState::Queued => "Starting".into(),
        BenchState::Running => {
            let current = run.models.iter().find(|m| Some(&m.model_id) == run.current_model_id.as_ref());
            match current {
                Some(m) if m.state == ModelRunState::Installing => format!("Running · installing {}", m.name),
                _ => format!("Running · {} of {total} pages", run.pages_done),
            }
        }
        BenchState::Done => format!(
            "Done · {} · {}",
            format::plural(run.files.len(), "file", "files"),
            format::plural(run.pages_total as usize, "page", "pages")
        ),
        BenchState::Cancelled => "Stopped".into(),
        BenchState::Interrupted => "Interrupted".into(),
        BenchState::Error => "Failed".into(),
    }
}

fn best_line(run: &BenchRun) -> Option<String> {
    let s = run.summary.as_ref()?;
    let best = s.leaderboard.iter().find(|r| Some(&r.model_id) == s.best_model_id.as_ref())?;
    if s.ranked_by == "cer" {
        if let Some(a) = best.accuracy {
            return Some(format!("Best read: {} · {:.1}%", best.name, a * 100.0));
        }
    }
    best.seconds_per_page.map(|s| format!("Fastest: {} · {s:.1} s/page", best.name))
}

pub struct BenchmarksView {
    state: Entity<AppState>,
    models: Option<Vec<ModelInfo>>,
    chosen: BTreeSet<String>,
    picked: Vec<Picked>,
    name: Entity<InputState>,
    runs: Vec<BenchRun>,
    selected: Option<Entity<BenchRunPanel>>,
    selected_id: Option<String>,
    show_all: bool,
    starting: bool,
    error: Option<String>,
    was_working: bool,
    _poll: Option<Task<()>>,
    _panel: Option<Subscription>,
}

impl BenchmarksView {
    pub fn new(state: Entity<AppState>, window: &mut Window, cx: &mut Context<Self>) -> Self {
        let name = cx.new(|cx| InputState::new(window, cx).placeholder("Named after the folder"));
        let mut this = Self {
            state,
            models: None,
            chosen: BTreeSet::new(),
            picked: Vec::new(),
            name,
            runs: Vec::new(),
            selected: None,
            selected_id: None,
            show_all: false,
            starting: false,
            error: None,
            was_working: false,
            _poll: None,
            _panel: None,
        };
        let api = this.state.read(cx).api.clone();
        call(cx, api, |api| api.list_models(), |this, result, _| match result {
            Ok(list) => {
                let ready: Vec<ModelInfo> = list.into_iter().filter(|m| m.status == ModelStatus::Ready).collect();
                this.chosen = ready.iter().map(|m| m.id.clone()).collect();
                this.models = Some(ready);
            }
            Err(err) => {
                this.error = Some(err);
                this.models = Some(Vec::new());
            }
        })
        .detach();
        this.load_runs(cx);
        this
    }

    fn load_runs(&mut self, cx: &mut Context<Self>) {
        let api = self.state.read(cx).api.clone();
        call(cx, api, |api| api.list_benchmarks(), |this, result, cx| {
            // The model list already reports an unreachable backend.
            let Ok(runs) = result else { return };
            this.runs = runs;
            let working = this.runs.iter().any(|r| r.state.active());
            // Tell the rest of the app (the header's count) when a run finishes.
            if this.was_working && !working {
                this.state.update(cx, |s, cx| s.bump(cx));
            }
            this.was_working = working;
            if working && this._poll.is_none() {
                this._poll = Some(cx.spawn(async move |this, cx| {
                    cx.background_executor().timer(POLL).await;
                    this.update(cx, |this, cx| {
                        this._poll = None;
                        this.load_runs(cx);
                    })
                    .ok();
                }));
            }
        })
        .detach();
    }

    fn select(&mut self, id: Option<String>, window: &mut Window, cx: &mut Context<Self>) {
        self.selected_id = id.clone();
        self.selected = None;
        self._panel = None;
        if let Some(run) = id.and_then(|id| self.runs.iter().find(|r| r.id == id).cloned()) {
            let state = self.state.clone();
            let panel = cx.new(|cx| BenchRunPanel::new(state, run, window, cx));
            self._panel = Some(cx.subscribe_in(&panel, window, |this, _, event: &RunEvent, window, cx| match event {
                RunEvent::Closed => this.select(None, window, cx),
                RunEvent::Changed(next) => {
                    let next = next.clone().or_else(|| this.selected_id.clone());
                    this.reload_then_select(next, window, cx);
                }
                RunEvent::Deleted => {
                    this.select(None, window, cx);
                    this.load_runs(cx);
                    this.state.update(cx, |s, cx| s.bump(cx));
                }
            }));
            self.selected = Some(panel);
        }
        cx.notify();
    }

    fn reload_then_select(&mut self, id: Option<String>, window: &mut Window, cx: &mut Context<Self>) {
        let api = self.state.read(cx).api.clone();
        cx.spawn_in(window, async move |this, cx| {
            let runs = cx.background_spawn(async move { api.list_benchmarks() }).await;
            this.update_in(cx, |this, window, cx| {
                if let Ok(runs) = runs {
                    this.runs = runs;
                }
                this.select(id, window, cx);
                this.load_runs(cx);
            })
            .ok();
        })
        .detach();
    }

    fn add(&mut self, paths: Vec<PathBuf>, cx: &mut Context<Self>) {
        for p in collect(&paths) {
            if !self.picked.iter().any(|q| q.path == p.path) {
                self.picked.push(p);
            }
        }
        cx.notify();
    }

    fn pick(&mut self, folder: bool, cx: &mut Context<Self>) {
        let paths = cx.prompt_for_paths(PathPromptOptions {
            files: !folder,
            directories: folder,
            multiple: true,
            prompt: Some("Add".into()),
        });
        cx.spawn(async move |this, cx| {
            match paths.await {
                Ok(Ok(Some(paths))) => {
                    this.update(cx, |this, cx| this.add(paths, cx)).ok();
                }
                // Linux can't always open a file picker (no desktop portal): say so.
                Ok(Err(err)) => {
                    this.update(cx, |this, cx| {
                        this.error = Some(format!("Couldn't open the file picker: {err}. Drop the folder here instead."));
                        cx.notify();
                    })
                    .ok();
                }
                _ => {}
            }
        })
        .detach();
    }

    fn start(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        self.starting = true;
        self.error = None;
        let files: Vec<(PathBuf, String)> = self.picked.iter().map(|p| (p.file.clone(), p.path.clone())).collect();
        let models: Vec<String> = self.chosen.iter().cloned().collect();
        let name = self.name.read(cx).value().trim().to_string();
        let api = self.state.read(cx).api.clone();
        cx.spawn_in(window, async move |this, cx| {
            let result = cx.background_spawn(async move { api.start_benchmark(&files, &models, &name) }).await;
            this.update_in(cx, |this, window, cx| {
                this.starting = false;
                match result {
                    Ok(run) => {
                        this.picked.clear();
                        this.name.update(cx, |n, cx| n.set_value("", window, cx));
                        this.reload_then_select(Some(run.id), window, cx);
                    }
                    Err(err) => this.error = Some(err),
                }
                cx.notify();
            })
            .ok();
        })
        .detach();
        cx.notify();
    }

    fn drop_zone(&self, cx: &mut Context<Self>) -> impl IntoElement {
        let documents = self.picked.iter().filter(|p| is_document(&p.path)).count();
        let drop_bg = cx.theme().drop_target;
        let hover = cx.theme().accent;
        let mut zone = ui::card(cx)
            .id("bench-drop")
            .flex_1()
            .min_h(px(290.))
            .items_center()
            .justify_center()
            .gap_3()
            .p_6()
            .cursor_pointer()
            .hover(move |s| s.bg(hover))
            .drag_over::<ExternalPaths>(move |style, _, _, _| style.bg(drop_bg))
            .on_drop(cx.listener(|this, paths: &ExternalPaths, _, cx| this.add(paths.paths().to_vec(), cx)))
            .on_click(cx.listener(|this, _, _, cx| this.pick(true, cx)))
            .child(
                div()
                    .size(px(52.))
                    .rounded_full()
                    .bg(cx.theme().primary)
                    .h_flex()
                    .justify_center()
                    .child(Icon::new(IconName::FolderUp).text_color(cx.theme().primary_foreground)),
            )
            .child(
                div()
                    .v_flex()
                    .items_center()
                    .gap_1()
                    .child(div().text_2xl().font_semibold().text_center().child(if documents > 0 {
                        format!("{} in this batch", format::plural(documents, "document", "documents"))
                    } else {
                        "Drop a folder of documents".into()
                    }))
                    .child(div().max_w(px(460.)).text_center().child(ui::small_muted(
                        "Every page goes to every model you pick. Add invoice.gt.txt next to invoice.pdf with the correct text to score accuracy.",
                        cx,
                    ))),
            );
        if !self.picked.is_empty() {
            let mut chips = div().id("bench-picked").max_h(px(84.)).overflow_y_scroll().h_flex().flex_wrap().justify_center().gap_1();
            for (i, p) in self.picked.iter().enumerate() {
                let reference = is_reference(&p.path);
                chips = chips.child(
                    div()
                        .h_flex()
                        .gap_1()
                        .pl_2()
                        .pr_1()
                        .rounded_full()
                        .max_w(px(240.))
                        .text_xs()
                        .bg(if reference { cx.theme().success.opacity(0.15) } else { cx.theme().muted })
                        .when(reference, |d| d.text_color(cx.theme().success))
                        .child(div().truncate().child(p.path.clone()))
                        .child(Button::new(("bench-remove", i)).ghost().xsmall().icon(IconName::X).on_click(cx.listener(move |this, _, _, cx| {
                            cx.stop_propagation();
                            if i < this.picked.len() {
                                this.picked.remove(i);
                            }
                            cx.notify();
                        }))),
                );
            }
            zone = zone.child(chips);
        }
        zone.child(
            div()
                .h_flex()
                .flex_wrap()
                .justify_center()
                .gap_2()
                .child(Button::new("bench-folder").primary().icon(IconName::FolderOpen).label("Choose a folder").on_click(cx.listener(|this, _, _, cx| {
                    cx.stop_propagation();
                    this.pick(true, cx)
                })))
                .child(Button::new("bench-files").outline().icon(IconName::FileUp).label("Choose files").on_click(cx.listener(|this, _, _, cx| {
                    cx.stop_propagation();
                    this.pick(false, cx)
                })))
                .when(!self.picked.is_empty(), |d| {
                    d.child(Button::new("bench-clear").ghost().label("Clear").on_click(cx.listener(|this, _, _, cx| {
                        cx.stop_propagation();
                        this.picked.clear();
                        cx.notify();
                    })))
                }),
        )
    }

    fn compare_card(&self, cx: &mut Context<Self>) -> Div {
        let card = ui::card(cx).flex_1().min_h(px(290.)).justify_between().gap_4().p_5().bg(cx.theme().secondary);
        let ready = self.models.clone().unwrap_or_default();
        if self.models.is_some() && ready.is_empty() {
            let state = self.state.clone();
            return card
                .justify_center()
                .items_start()
                .gap_3()
                .child(div().text_xl().font_semibold().child("No models are ready yet"))
                .child(ui::muted("A benchmark compares the models you have installed. Set up two or more.", cx))
                .child(Button::new("bench-setup").small().primary().icon(IconName::ArrowRight).label("Go to Setup").on_click(move |_, _, cx| {
                    state.update(cx, |s, cx| s.navigate(View::Setup, cx))
                }));
        }
        let default_id = self.state.read(cx).default_model_id().map(str::to_string);
        let mut list = div().id("bench-models").max_h(px(176.)).overflow_y_scroll().v_flex().gap_1();
        for m in &ready {
            let id = m.id.clone();
            let chosen = self.chosen.contains(&m.id);
            let tail = format!(
                "{}{}",
                if Some(&m.id) == default_id.as_ref() { "default · " } else { "" },
                if m.engine == "nvidia-nim" { "cloud".to_string() } else { m.fit.summary.clone() }
            );
            list = list.child(
                div()
                    .h_flex()
                    .gap_3()
                    .min_h(px(36.))
                    .px_3()
                    .rounded_md()
                    .bg(if chosen { cx.theme().background } else { cx.theme().muted })
                    .child(
                        Checkbox::new(SharedString::from(format!("pick-{}", m.id)))
                            .checked(chosen)
                            .label(m.name.clone())
                            .on_change(cx.listener(move |this, checked: &bool, _, cx| {
                                if *checked {
                                    this.chosen.insert(id.clone());
                                } else {
                                    this.chosen.remove(&id);
                                }
                                cx.notify();
                            })),
                    )
                    .child(div().ml_auto().child(ui::small_muted(tail, cx))),
            );
        }
        let documents = self.picked.iter().filter(|p| is_document(&p.path)).count();
        let references = self.picked.iter().filter(|p| is_reference(&p.path)).count();
        let hint = if documents == 0 {
            "Nothing selected yet".to_string()
        } else {
            format!(
                "{}{}",
                format::plural(documents, "document", "documents"),
                if references > 0 { format!(" · {references} with reference text") } else { " · no reference text: ranked by speed".into() }
            )
        };
        card.child(div().v_flex().gap_2().child(div().text_sm().font_medium().child("Models to compare")).child(list))
            .child(
                div()
                    .v_flex()
                    .gap_1()
                    .child(div().h_flex().gap_1().text_sm().child(div().font_medium().child("Name")).child(ui::small_muted("(optional)", cx)))
                    .child(Input::new(&self.name)),
            )
            .child(
                div()
                    .h_flex()
                    .justify_between()
                    .gap_3()
                    .child(div().min_w_0().truncate().text_sm().text_color(cx.theme().muted_foreground).child(hint))
                    .child(
                        Button::new("bench-start")
                            .primary()
                            .icon(IconName::Gauge)
                            .label("Start benchmark")
                            .loading(self.starting)
                            .disabled(documents == 0 || self.chosen.is_empty() || self.starting)
                            .on_click(cx.listener(|this, _, window, cx| this.start(window, cx))),
                    ),
            )
    }

    fn batches(&self, cx: &mut Context<Self>) -> Div {
        let mut header = div().h_flex().justify_between().child(ui::section_label("Batches", cx));
        if self.runs.len() > BATCH_COUNT {
            header = header.child(
                Button::new("bench-show-all")
                    .ghost()
                    .small()
                    .label(if self.show_all { "Show fewer".to_string() } else { format!("Show all {}", self.runs.len()) })
                    .on_click(cx.listener(|this, _, _, cx| {
                        this.show_all = !this.show_all;
                        cx.notify();
                    })),
            );
        }
        if self.runs.is_empty() {
            return div().v_flex().gap_2().child(header).child(
                ui::card(cx).min_h(px(140.)).items_center().justify_center().px_5().child(ui::muted(
                    "Each benchmark becomes a batch here, ready to re-run. Runs from the command line and from AI agents show up too.",
                    cx,
                )),
            );
        }
        let visible = if self.show_all { self.runs.len() } else { BATCH_COUNT };
        let mut grid = ui::wrap_row();
        for run in self.runs.iter().take(visible) {
            let busy = run.state.active();
            let done = run.state == BenchState::Done;
            let selected = self.selected_id.as_ref() == Some(&run.id);
            let (icon, color) = match run.state {
                BenchState::Done => (IconName::ArrowUpRight, cx.theme().foreground),
                BenchState::Queued | BenchState::Running => (IconName::LoaderCircle, cx.theme().muted_foreground),
                BenchState::Cancelled => (IconName::Ban, cx.theme().muted_foreground),
                _ => (IconName::TriangleAlert, cx.theme().danger),
            };
            let total = run.pages_total * run.models.len() as u32;
            let sub = if busy {
                None
            } else {
                Some(best_line(run).unwrap_or_else(|| match run.source.as_str() {
                    "cli" => "from the command line".into(),
                    "mcp" => "from an AI agent".into(),
                    _ => format::plural(run.models.len(), "model", "models"),
                }))
            };
            let id = run.id.clone();
            let hover = cx.theme().accent;
            grid = grid.child(
                ui::card(cx)
                    .id(SharedString::from(format!("batch-{}", run.id)))
                    .flex_basis(px(220.))
                    .flex_grow(1.)
                    .flex_shrink(1.)
                    .min_w_0()
                    .max_w(px(320.))
                    .min_h(px(132.))
                    .justify_between()
                    .gap_2()
                    .p_4()
                    .cursor_pointer()
                    .when(done, |d| d.bg(cx.theme().secondary))
                    .when(selected, |d| d.border_2().border_color(cx.theme().ring))
                    .hover(move |s| s.bg(hover))
                    .when_some(run.error.clone(), |d, err| {
                        d.tooltip(move |window, cx| gpui_kit::component::tooltip::Tooltip::new(err.clone()).build(window, cx))
                    })
                    .on_click(cx.listener(move |this, _, window, cx| {
                        let next = (this.selected_id.as_ref() != Some(&id)).then(|| id.clone());
                        this.select(next, window, cx);
                    }))
                    .child(
                        div()
                            .h_flex()
                            .justify_between()
                            .gap_2()
                            .child(ui::small_muted(state_label(run), cx).truncate())
                            .child(Icon::new(icon).small().text_color(color)),
                    )
                    .child(div().text_base().font_semibold().truncate().child(run.name.clone()))
                    .when_some(sub, |d, s| d.child(ui::small_muted(s, cx).truncate()))
                    .when(busy, |d| {
                        d.child(ui::progress_bar(
                            SharedString::from(format!("batch-progress-{}", run.id)),
                            if total > 0 { 100.0 * run.pages_done as f64 / total as f64 } else { 0.0 },
                        ))
                    }),
            );
        }
        div().v_flex().gap_2().child(header).child(grid)
    }
}

impl Render for BenchmarksView {
    fn render(&mut self, _: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        let zone = self.drop_zone(cx).into_any_element();
        let compare = self.compare_card(cx);
        let batches = self.batches(cx);
        div()
            .v_flex()
            .gap_5()
            .when_some(self.error.clone(), |d, err| d.child(ui::notice(err, cx)))
            .child(
                ui::wrap_row()
                    .gap_4()
                    .items_stretch()
                    .child(div().flex_basis(px(420.)).flex_grow(1.).flex_shrink(1.).min_w_0().v_flex().child(ui::section("New benchmark", zone, cx).flex_1()))
                    .child(div().flex_basis(px(420.)).flex_grow(1.).flex_shrink(1.).min_w_0().v_flex().child(ui::section("Compare with", compare, cx).flex_1())),
            )
            .child(batches)
            .when_some(self.selected.clone(), |d, panel| d.child(panel))
    }
}

#[cfg(test)]
mod tests {
    use super::{collect, short_name};

    #[test]
    fn a_picked_folder_keeps_references_next_to_documents() {
        let dir = std::env::temp_dir().join(format!("docbox-bench-{}", std::process::id()));
        let inner = dir.join("Invoices").join("march");
        std::fs::create_dir_all(&inner).unwrap();
        for name in ["a.pdf", "a.gt.txt", "notes.docx"] {
            std::fs::write(inner.join(name), b"x").unwrap();
        }
        let picked = collect(&[dir.join("Invoices")]);
        let paths: Vec<&str> = picked.iter().map(|p| p.path.as_str()).collect();
        assert_eq!(paths, ["Invoices/march/a.gt.txt", "Invoices/march/a.pdf"]);
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn short_names_keep_the_engine_and_size() {
        assert_eq!(short_name("PaddleOCR Balanced — Chinese + English"), "PaddleOCR Balanced");
        assert_eq!(short_name("Tesseract — French"), "Tesseract French");
        assert_eq!(short_name("Granite Vision — 2B"), "Granite Vision");
        assert_eq!(short_name("Tesseract"), "Tesseract");
    }
}
