//! Read a file: add documents (drop, pick, paste), choose the model and output, read them,
//! then the recent reads and the text of the one picked.

use std::path::PathBuf;
use std::time::Duration;

use gpui_kit::assets::IconName;
use gpui_kit::component::button::{Button, ButtonVariants};
use gpui_kit::component::select::{Select, SelectEvent, SelectState};
use gpui_kit::component::spinner::Spinner;
use gpui_kit::component::switch::Switch;
use gpui_kit::component::{ActiveTheme, Disableable, Icon, Selectable, Sizable, StyledExt};
use gpui_kit::prelude::FluentBuilder as _;
use gpui_kit::*;

use crate::api::{self, ModelInfo, ModelStatus, OutputFormat, PageSource, ReadDetail, ReadState, ReadSummary};
use crate::choice::Choice;
use crate::format;
use crate::state::{AppState, View, call};
use crate::ui;

const RECENT_COUNT: usize = 4;
const POLL: Duration = Duration::from_secs(1);

#[derive(Clone, Copy, PartialEq)]
enum Flash {
    Copied,
    Opened,
    Shown,
}

pub struct ReadView {
    state: Entity<AppState>,
    models: Option<Vec<ModelInfo>>,
    model_select: Entity<SelectState<Vec<Choice>>>,
    model_id: Option<String>,
    files: Vec<PathBuf>,
    format: OutputFormat,
    use_pdf_text: bool,
    reads: Vec<ReadSummary>,
    finished: Option<Vec<String>>,
    selected: Option<String>,
    detail: Option<ReadDetail>,
    show_all: bool,
    starting: bool,
    error: Option<String>,
    hint: Option<String>,
    panel_error: Option<String>,
    confirm_delete: bool,
    flash: Option<Flash>,
    _poll: Option<Task<()>>,
    _flash: Option<Task<()>>,
    _subscriptions: Vec<Subscription>,
}

fn read_label(r: &ReadSummary) -> String {
    match r.state {
        ReadState::Queued => "Waiting to start".into(),
        ReadState::Reading => match r.pages_total {
            Some(total) => format!("Reading · page {} of {total}", (r.pages_done + 1).min(total)),
            None => "Reading".into(),
        },
        ReadState::Done => {
            let mut parts = vec!["Done".to_string()];
            if let Some(total) = r.pages_total {
                parts.push(format::plural(total as usize, "page", "pages"));
            }
            if let Some(s) = r.seconds {
                parts.push(format::seconds(s));
            }
            parts.join(" · ")
        }
        ReadState::Cancelled => "Stopped".into(),
        ReadState::Error => "Failed".into(),
    }
}

fn file_name(path: &std::path::Path) -> String {
    path.file_name().map_or_else(|| path.display().to_string(), |n| n.to_string_lossy().into_owned())
}

impl ReadView {
    pub fn new(state: Entity<AppState>, window: &mut Window, cx: &mut Context<Self>) -> Self {
        let model_select = cx.new(|cx| SelectState::new(Vec::<Choice>::new(), None, window, cx));
        let subscriptions = vec![
            cx.subscribe(&model_select, |this: &mut Self, _, event: &SelectEvent<Vec<Choice>>, cx| {
                let SelectEvent::Confirm(value) = event;
                if let Some(value) = value {
                    this.model_id = Some(value.to_string());
                    cx.notify();
                }
            }),
            // Settings arrive after the view: start on the default model once both are known.
            cx.observe_in(&state, window, |this: &mut Self, _, window, cx| this.pick_default(window, cx)),
        ];
        let mut this = Self {
            state,
            models: None,
            model_select,
            model_id: None,
            files: Vec::new(),
            format: OutputFormat::Txt,
            use_pdf_text: true,
            reads: Vec::new(),
            finished: None,
            selected: None,
            detail: None,
            show_all: false,
            starting: false,
            error: None,
            hint: None,
            panel_error: None,
            confirm_delete: false,
            flash: None,
            _poll: None,
            _flash: None,
            _subscriptions: subscriptions,
        };
        this.load_models(window, cx);
        this.load_reads(cx);
        this
    }

    fn load_models(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        let api = self.state.read(cx).api.clone();
        cx.spawn_in(window, async move |this, cx| {
            let result = cx.background_spawn(async move { api.list_models() }).await;
            this.update_in(cx, |this, window, cx| {
                match result {
                    // "Ready" rather than "downloaded": a model whose engine was uninstalled,
                    // or whose Ollama isn't running, has files on disk but can't run.
                    Ok(list) => this.models = Some(list.into_iter().filter(|m| m.status == ModelStatus::Ready).collect()),
                    Err(err) => {
                        this.error = Some(err);
                        this.models = Some(Vec::new());
                    }
                }
                let default = this.state.read(cx).default_model_id().map(str::to_string);
                let choices: Vec<Choice> = this
                    .models
                    .iter()
                    .flatten()
                    .map(|m| {
                        let mut title = format!("{} · {}", m.name, if m.engine == "nvidia-nim" { "cloud" } else { "installed" });
                        if Some(&m.id) == default.as_ref() {
                            title.push_str(" · default");
                        }
                        Choice::new(m.id.clone(), title)
                    })
                    .collect();
                this.model_select.update(cx, |s, cx| s.set_items(choices, window, cx));
                this.pick_default(window, cx);
                cx.notify();
            })
            .ok();
        })
        .detach();
    }

    fn pick_default(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        if self.model_id.is_some() {
            return;
        }
        let Some(models) = &self.models else { return };
        let default = self.state.read(cx).default_model_id().map(str::to_string);
        let preferred = models.iter().find(|m| Some(&m.id) == default.as_ref()).or(models.first());
        if let Some(m) = preferred {
            let id = SharedString::from(m.id.clone());
            self.model_id = Some(m.id.clone());
            self.model_select.update(cx, |s, cx| s.set_selected_value(&id, window, cx));
        }
    }

    fn load_reads(&mut self, cx: &mut Context<Self>) {
        let api = self.state.read(cx).api.clone();
        call(cx, api, |api| api.list_reads(), |this, result, cx| {
            // The model list already reports an unreachable backend.
            let Ok(list) = result else { return };
            let finished: Vec<String> = list.iter().filter(|r| r.state == ReadState::Done).map(|r| r.id.clone()).collect();
            // Tell the rest of the app (the header's count) when a read finishes.
            if let Some(before) = &this.finished {
                if finished.iter().any(|id| !before.contains(id)) {
                    this.state.update(cx, |s, cx| s.bump(cx));
                }
            }
            this.finished = Some(finished);
            let progressed = this.selected.as_ref().and_then(|id| {
                let now = list.iter().find(|r| &r.id == id)?;
                let before = this.reads.iter().find(|r| &r.id == id);
                Some(before.is_none_or(|b| b.state != now.state || b.pages_done != now.pages_done))
            });
            this.reads = list;
            if progressed == Some(true) {
                this.load_detail(cx);
            }
            let working = this.reads.iter().any(|r| matches!(r.state, ReadState::Queued | ReadState::Reading));
            if working && this._poll.is_none() {
                this._poll = Some(cx.spawn(async move |this, cx| {
                    cx.background_executor().timer(POLL).await;
                    this.update(cx, |this, cx| {
                        this._poll = None;
                        this.load_reads(cx);
                    })
                    .ok();
                }));
            }
        })
        .detach();
    }

    fn load_detail(&mut self, cx: &mut Context<Self>) {
        let Some(id) = self.selected.clone() else {
            self.detail = None;
            return;
        };
        let api = self.state.read(cx).api.clone();
        call(cx, api, move |api| api.get_read(&id), |this, result, _| {
            this.detail = result.ok().filter(|d| Some(&d.summary.id) == this.selected.as_ref());
        })
        .detach();
    }

    fn select(&mut self, id: Option<String>, cx: &mut Context<Self>) {
        self.selected = id;
        self.confirm_delete = false;
        self.panel_error = None;
        self.detail = None;
        self.load_detail(cx);
        cx.notify();
    }

    fn add_files(&mut self, incoming: Vec<PathBuf>, cx: &mut Context<Self>) {
        let total = incoming.len();
        let accepted: Vec<PathBuf> = incoming.into_iter().filter(|p| api::is_readable(p)).collect();
        self.hint = (accepted.len() < total).then(|| "Only PDFs and images can be read; the rest were skipped.".into());
        self.files.extend(accepted);
        cx.notify();
    }

    fn choose_files(&mut self, cx: &mut Context<Self>) {
        let paths = cx.prompt_for_paths(PathPromptOptions {
            files: true,
            directories: false,
            multiple: true,
            prompt: Some("Read".into()),
        });
        cx.spawn(async move |this, cx| {
            if let Ok(Ok(Some(paths))) = paths.await {
                this.update(cx, |this, cx| this.add_files(paths, cx)).ok();
            }
        })
        .detach();
    }

    /// An image on the clipboard (a screenshot), saved to a file so it can be read like one.
    fn paste(&mut self, cx: &mut Context<Self>) {
        self.hint = None;
        let image = cx.read_from_clipboard().and_then(|item| {
            item.entries().iter().find_map(|entry| match entry {
                ClipboardEntry::Image(image) => Some(image.clone()),
                _ => None,
            })
        });
        let files = cx.read_from_clipboard().and_then(|item| {
            item.entries().iter().find_map(|entry| match entry {
                ClipboardEntry::ExternalPaths(paths) => Some(paths.paths().to_vec()),
                _ => None,
            })
        });
        if let Some(paths) = files {
            self.add_files(paths, cx);
            return;
        }
        let Some(image) = image else {
            self.hint = Some("There's no image on the clipboard. Copy a screenshot or picture first.".into());
            cx.notify();
            return;
        };
        let saved = crate::backend::data_dir().and_then(|dir| {
            let dir = dir.join("pasted");
            std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
            let stamp = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map_or(0, |d| d.as_millis());
            let path = dir.join(format!("pasted-{stamp}.{}", image.format.extension()));
            std::fs::write(&path, &image.bytes).map_err(|e| e.to_string())?;
            Ok(path)
        });
        match saved {
            Ok(path) => self.add_files(vec![path], cx),
            Err(err) => {
                self.hint = Some(format!("Couldn't save the pasted image: {err}"));
                cx.notify();
            }
        }
    }

    fn run(&mut self, cx: &mut Context<Self>) {
        let Some(model_id) = self.model_id.clone() else { return };
        if self.files.is_empty() {
            return;
        }
        self.starting = true;
        self.error = None;
        let files = self.files.clone();
        let (format, use_pdf_text) = (self.format, self.use_pdf_text);
        let api = self.state.read(cx).api.clone();
        call(cx, api, move |api| api.start_reads(&model_id, &files, format, use_pdf_text), |this, result, cx| {
            this.starting = false;
            match result {
                Ok(started) => {
                    this.files.clear();
                    let first = started.reads.first().map(|r| r.id.clone());
                    this.select(first, cx);
                    this.load_reads(cx);
                }
                Err(err) => this.error = Some(err),
            }
        })
        .detach();
    }

    fn flash(&mut self, what: Flash, cx: &mut Context<Self>) {
        self.flash = Some(what);
        self._flash = Some(cx.spawn(async move |this, cx| {
            cx.background_executor().timer(Duration::from_millis(1800)).await;
            this.update(cx, |this, cx| {
                if this.flash == Some(what) {
                    this.flash = None;
                    cx.notify();
                }
            })
            .ok();
        }));
        cx.notify();
    }

    fn open_read(&mut self, target: &'static str, cx: &mut Context<Self>) {
        let Some(id) = self.selected.clone() else { return };
        self.panel_error = None;
        let api = self.state.read(cx).api.clone();
        call(cx, api, move |api| api.open_read(&id, target), move |this, result, cx| match result {
            Ok(()) => this.flash(if target == "file" { Flash::Opened } else { Flash::Shown }, cx),
            Err(err) => this.panel_error = Some(err),
        })
        .detach();
    }

    fn delete_read(&mut self, cx: &mut Context<Self>) {
        let Some(id) = self.selected.clone() else { return };
        let api = self.state.read(cx).api.clone();
        call(cx, api, move |api| api.delete_read(&id), |this, result, cx| match result {
            Ok(()) => {
                this.select(None, cx);
                this.load_reads(cx);
                this.state.update(cx, |s, cx| s.bump(cx));
            }
            Err(err) => this.panel_error = Some(err),
        })
        .detach();
    }

    fn drop_zone(&self, cx: &mut Context<Self>) -> impl IntoElement {
        let n = self.files.len();
        let drop_bg = cx.theme().drop_target;
        let hover = cx.theme().accent;
        let mut zone = ui::card(cx)
            .id("drop-zone")
            .min_h(px(262.))
            .items_center()
            .justify_center()
            .gap_3()
            .p_6()
            .cursor_pointer()
            .hover(move |s| s.bg(hover))
            .drag_over::<ExternalPaths>(move |style, _, _, _| style.bg(drop_bg))
            .on_drop(cx.listener(|this, paths: &ExternalPaths, _, cx| this.add_files(paths.paths().to_vec(), cx)))
            .on_click(cx.listener(|this, _, _, cx| this.choose_files(cx)))
            .child(
                div()
                    .size(px(52.))
                    .rounded_full()
                    .bg(cx.theme().primary)
                    .h_flex()
                    .justify_center()
                    .child(Icon::new(IconName::FileUp).text_color(cx.theme().primary_foreground)),
            )
            .child(
                div()
                    .v_flex()
                    .items_center()
                    .gap_1()
                    .child(div().text_2xl().font_semibold().text_center().child(if n > 0 {
                        format!("{} ready to read", format::plural(n, "file", "files"))
                    } else {
                        "Drop a PDF or image here".into()
                    }))
                    .child(ui::small_muted("PDF, PNG, JPG, TIFF · every page is read", cx)),
            );
        if n > 0 {
            let mut chips = div().h_flex().flex_wrap().justify_center().gap_1();
            for (i, path) in self.files.iter().enumerate() {
                chips = chips.child(
                    div()
                        .h_flex()
                        .gap_1()
                        .pl_2()
                        .pr_1()
                        .py_0p5()
                        .rounded_full()
                        .bg(cx.theme().muted)
                        .text_xs()
                        .max_w(px(220.))
                        .child(div().truncate().child(file_name(path)))
                        .child(
                            Button::new(("remove-file", i))
                                .ghost()
                                .xsmall()
                                .icon(IconName::X)
                                .tooltip(format!("Remove {}", file_name(path)))
                                .on_click(cx.listener(move |this, _, _, cx| {
                                    if i < this.files.len() {
                                        this.files.remove(i);
                                    }
                                    cx.notify();
                                })),
                        ),
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
                .child(
                    Button::new("choose-files")
                        .primary()
                        .icon(IconName::FolderOpen)
                        .label(if n > 0 { "Add more" } else { "Choose files" })
                        .on_click(cx.listener(|this, _, _, cx| {
                            cx.stop_propagation();
                            this.choose_files(cx)
                        })),
                )
                .child(
                    Button::new("paste")
                        .outline()
                        .icon(IconName::Clipboard)
                        .label("Paste from clipboard")
                        .on_click(cx.listener(|this, _, _, cx| {
                            cx.stop_propagation();
                            this.paste(cx)
                        })),
                ),
        )
        .when_some(self.hint.clone(), |d, hint| d.child(div().text_xs().text_color(cx.theme().warning).child(hint)))
    }

    fn run_card(&self, cx: &mut Context<Self>) -> Div {
        let card = ui::card(cx).min_h(px(262.)).justify_between().gap_4().p_5().bg(cx.theme().secondary);
        if self.models.as_ref().is_some_and(|m| m.is_empty()) {
            let state = self.state.clone();
            return card.justify_center().items_start().gap_3().child(div().text_xl().font_semibold().child("No models are ready yet"))
                .child(ui::muted("Set one up first; it takes one click.", cx))
                .child(
                    Button::new("go-setup")
                        .small()
                        .primary()
                        .icon(IconName::ArrowRight)
                        .label("Go to Setup")
                        .on_click(move |_, _, cx| state.update(cx, |s, cx| s.navigate(View::Setup, cx))),
                );
        }
        let output_dir = self.state.read(cx).settings.as_ref().map(|s| s.output_dir.clone());
        let hint = if self.files.is_empty() {
            "Nothing selected yet".to_string()
        } else {
            let mut hint = format!("{} selected", format::plural(self.files.len(), "file", "files"));
            if let Some(dir) = &output_dir {
                hint.push_str(&format!(" · saves to {}", format::short_path(dir, 2)));
            }
            hint
        };
        let mut formats = div().h_flex().flex_wrap().gap_1();
        for f in OutputFormat::ALL {
            formats = formats.child(
                Button::new(SharedString::from(format!("format-{}", f.as_str())))
                    .small()
                    .outline()
                    .label(f.label())
                    .selected(self.format == f)
                    .on_click(cx.listener(move |this, _, _, cx| {
                        this.format = f;
                        cx.notify();
                    })),
            );
        }
        card.child(
            div()
                .v_flex()
                .gap_1()
                .child(div().text_sm().font_medium().child("Engine and model"))
                .child(Select::new(&self.model_select).placeholder(if self.models.is_none() { "Loading…" } else { "Choose a model" })),
        )
        .child(div().v_flex().gap_1().child(div().text_sm().font_medium().child("Save the text as")).child(formats))
        .child(
            div()
                .h_flex()
                .justify_between()
                .gap_3()
                .child(
                    div()
                        .v_flex()
                        .min_w_0()
                        .child(div().text_sm().font_medium().child("Use text already in PDFs"))
                        .child(ui::small_muted(
                            if self.use_pdf_text {
                                "Pages that carry their own text skip OCR"
                            } else {
                                "Every page is read by the model"
                            },
                            cx,
                        )),
                )
                .child(
                    Switch::new("use-pdf-text")
                        .checked(self.use_pdf_text)
                        .accessibility_label("Use text already in PDFs")
                        .on_change(cx.listener(|this, next: &bool, _, cx| {
                            this.use_pdf_text = *next;
                            cx.notify();
                        })),
                ),
        )
        .child(
            div()
                .h_flex()
                .justify_between()
                .gap_3()
                .child(div().min_w_0().truncate().text_sm().text_color(cx.theme().muted_foreground).child(hint))
                .child(
                    Button::new("read-text")
                        .primary()
                        .icon(IconName::Play)
                        .label("Read text")
                        .loading(self.starting)
                        .disabled(self.model_id.is_none() || self.files.is_empty() || self.starting)
                        .on_click(cx.listener(|this, _, _, cx| this.run(cx))),
                ),
        )
    }

    fn recent(&self, cx: &mut Context<Self>) -> Div {
        let visible: Vec<&ReadSummary> =
            if self.show_all { self.reads.iter().collect() } else { self.reads.iter().take(RECENT_COUNT).collect() };
        let mut header = div().h_flex().justify_between().child(ui::section_label("Recent files", cx));
        if self.reads.len() > RECENT_COUNT {
            let label = if self.show_all { "Show fewer".to_string() } else { format!("Show all {}", self.reads.len()) };
            header = header.child(
                Button::new("show-all").ghost().small().label(label).on_click(cx.listener(|this, _, _, cx| {
                    this.show_all = !this.show_all;
                    cx.notify();
                })),
            );
        }
        let body = if self.reads.is_empty() {
            ui::card(cx)
                .min_h(px(124.))
                .items_center()
                .justify_center()
                .child(ui::muted("Files you read show up here. Their text stays on this computer.", cx))
        } else {
            let mut grid = ui::wrap_row();
            for r in visible {
                let selected = self.selected.as_deref() == Some(r.id.as_str());
                let (icon, color) = match r.state {
                    ReadState::Done => (IconName::ArrowUpRight, cx.theme().foreground),
                    ReadState::Queued | ReadState::Reading => (IconName::LoaderCircle, cx.theme().muted_foreground),
                    ReadState::Cancelled => (IconName::Ban, cx.theme().muted_foreground),
                    ReadState::Error => (IconName::TriangleAlert, cx.theme().danger),
                };
                let id = r.id.clone();
                let hover = cx.theme().accent;
                grid = grid.child(
                    ui::card(cx)
                        .id(SharedString::from(format!("recent-{}", r.id)))
                        .flex_basis(px(200.))
                        .flex_grow(1.)
                        .flex_shrink(1.)
                        .min_w_0()
                        .max_w(px(320.))
                        .min_h(px(116.))
                        .justify_between()
                        .gap_2()
                        .p_4()
                        .cursor_pointer()
                        .when(r.state == ReadState::Done, |d| d.bg(cx.theme().secondary))
                        .when(selected, |d| d.border_2().border_color(cx.theme().ring))
                        .hover(move |s| s.bg(hover))
                        .when_some(r.error.clone().filter(|_| r.state == ReadState::Error), |d, err| {
                            d.tooltip(move |window, cx| gpui_kit::component::tooltip::Tooltip::new(err.clone()).build(window, cx))
                        })
                        .on_click(cx.listener(move |this, _, _, cx| {
                            let next = (this.selected.as_ref() != Some(&id)).then(|| id.clone());
                            this.select(next, cx);
                        }))
                        .child(
                            div()
                                .h_flex()
                                .justify_between()
                                .gap_2()
                                .child(ui::small_muted(read_label(r), cx).truncate())
                                .child(Icon::new(icon).small().text_color(color)),
                        )
                        .child(div().text_base().font_semibold().truncate().child(r.file_name.clone())),
                );
            }
            grid
        };
        div().v_flex().gap_2().child(header).child(body)
    }

    fn result_panel(&self, read: &ReadDetail, cx: &mut Context<Self>) -> Div {
        let s = &read.summary;
        let own_text = read.pages.iter().filter(|p| p.source == PageSource::PdfText).count();
        let mut meta: Vec<String> = Vec::new();
        meta.push(if own_text == read.pages.len() && own_text > 0 { "the PDF's own text".into() } else { s.model_name.clone() });
        if let Some(total) = s.pages_total {
            meta.push(format::plural(total as usize, "page", "pages"));
        }
        if own_text > 0 && own_text < read.pages.len() {
            meta.push(format!("{own_text} of {} used the PDF's own text", read.pages.len()));
        }
        if let Some(secs) = s.seconds {
            meta.push(format::seconds(secs));
        }
        if let Some(path) = &s.output_path {
            meta.push(format!("saved as {}", format::short_path(path, 2)));
        }
        let busy = matches!(s.state, ReadState::Reading | ReadState::Queued);

        let mut actions = div().h_flex().flex_wrap().gap_1();
        if s.state == ReadState::Done {
            let text = read.text.clone();
            actions = actions.child(
                Button::new("copy-text")
                    .small()
                    .outline()
                    .icon(IconName::Copy)
                    .label(if self.flash == Some(Flash::Copied) { "Copied" } else { "Copy text" })
                    .on_click(cx.listener(move |this, _, _, cx| {
                        cx.write_to_clipboard(ClipboardItem::new_string(text.clone()));
                        this.flash(Flash::Copied, cx);
                    })),
            );
            if s.output_path.is_some() {
                actions = actions
                    .child(
                        Button::new("open-file")
                            .small()
                            .outline()
                            .icon(IconName::ExternalLink)
                            .label(if self.flash == Some(Flash::Opened) { "Opened" } else { "Open file" })
                            .on_click(cx.listener(|this, _, _, cx| this.open_read("file", cx))),
                    )
                    .child(
                        Button::new("show-folder")
                            .small()
                            .outline()
                            .icon(IconName::FolderOpen)
                            .label(if self.flash == Some(Flash::Shown) { "Opened the folder" } else { "Show in folder" })
                            .on_click(cx.listener(|this, _, _, cx| this.open_read("folder", cx))),
                    );
            }
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
                    .child(if busy {
                        "Stop reading and remove it from recent files?"
                    } else {
                        "Remove from recent files? The saved file stays."
                    })
                    .child(
                        Button::new("delete-yes")
                            .small()
                            .danger()
                            .label(if busy { "Stop and remove" } else { "Remove" })
                            .on_click(cx.listener(|this, _, _, cx| this.delete_read(cx))),
                    )
                    .child(Button::new("delete-no").small().ghost().label("Keep").on_click(cx.listener(|this, _, _, cx| {
                        this.confirm_delete = false;
                        cx.notify();
                    }))),
            );
        } else {
            actions = actions.child(
                Button::new("delete")
                    .small()
                    .ghost()
                    .icon(IconName::Trash)
                    .tooltip("Remove from recent files")
                    .on_click(cx.listener(|this, _, _, cx| {
                        this.confirm_delete = true;
                        cx.notify();
                    })),
            );
        }
        actions = actions.child(
            Button::new("close-read")
                .small()
                .ghost()
                .icon(IconName::X)
                .tooltip("Close")
                .on_click(cx.listener(|this, _, _, cx| this.select(None, cx))),
        );

        let body = match s.state {
            ReadState::Error | ReadState::Cancelled => div().py_4().child(ui::muted(
                if s.state == ReadState::Cancelled {
                    "This read was stopped.".to_string()
                } else {
                    format!("This file couldn't be read: {}", s.error.clone().unwrap_or_else(|| "unknown error".into()))
                },
                cx,
            )),
            ReadState::Queued | ReadState::Reading => div()
                .h_flex()
                .gap_2()
                .py_4()
                .child(Spinner::new().small())
                .child(ui::muted(read_label(s), cx)),
            ReadState::Done if read.pages.iter().all(|p| p.lines.is_empty()) => {
                div().py_4().child(ui::muted("No text was found in this file.", cx))
            }
            ReadState::Done => {
                let mut pages = div().v_flex();
                let many = read.pages.len() > 1;
                for (p, page) in read.pages.iter().enumerate() {
                    let mut block = div().v_flex().py_1();
                    if many {
                        block = block.child(
                            div()
                                .pt_3()
                                .pb_1()
                                .text_xs()
                                .font_medium()
                                .text_color(cx.theme().muted_foreground)
                                .child(format!(
                                    "PAGE {}{}",
                                    p + 1,
                                    if page.source == PageSource::PdfText { " · the PDF's own text" } else { "" }
                                )),
                        );
                    }
                    let count = page.lines.len();
                    for (i, line) in page.lines.iter().enumerate() {
                        let mut row = div()
                            .h_flex()
                            .min_h(px(36.))
                            .gap_3()
                            .when(i + 1 < count, |d| d.border_b_1().border_color(cx.theme().border))
                            .child(
                                div()
                                    .w(px(24.))
                                    .text_xs()
                                    .text_color(cx.theme().muted_foreground)
                                    .child(format!("{:02}", i + 1)),
                            )
                            .child(div().flex_1().min_w_0().text_sm().child(line.text.clone()));
                        if let Some(conf) = line.confidence {
                            let pct = (conf * 100.0).round();
                            row = row
                                .child(
                                    div()
                                        .w(px(80.))
                                        .h(px(6.))
                                        .rounded_full()
                                        .bg(cx.theme().muted)
                                        .child(div().h_full().rounded_full().bg(cx.theme().primary).w(relative((conf as f32).clamp(0.0, 1.0)))),
                                )
                                .child(div().w(px(40.)).text_right().text_xs().font_medium().child(format!("{pct}%")));
                        }
                        block = block.child(row);
                    }
                    pages = pages.child(block);
                }
                pages
            }
        };

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
                    .child(
                        div()
                            .v_flex()
                            .flex_basis(px(240.))
                            .flex_grow(1.)
                            .flex_shrink(1.)
                            .min_w_0()
                            .child(div().text_xl().font_semibold().child(s.file_name.clone()))
                            .child(ui::small_muted(meta.join(" · "), cx)),
                    )
                    .child(actions),
            )
            .when_some(self.panel_error.clone(), |d, err| d.child(div().px_5().pt_4().child(ui::notice(err, cx))))
            .child(div().px_5().py_3().child(body))
    }
}

impl Render for ReadView {
    fn render(&mut self, _: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        let zone = self.drop_zone(cx).into_any_element();
        let run = self.run_card(cx);
        let recent = self.recent(cx);
        let panel = self.detail.clone().map(|d| self.result_panel(&d, cx));
        div()
            .v_flex()
            .gap_5()
            .when_some(self.error.clone(), |d, err| d.child(ui::notice(err, cx)))
            .child(
                ui::wrap_row()
                    .gap_4()
                    .items_end()
                    .child(div().flex_basis(px(420.)).flex_grow(1.).flex_shrink(1.).min_w_0().child(ui::section("Add documents", zone, cx)))
                    .child(div().flex_basis(px(420.)).flex_grow(1.).flex_shrink(1.).min_w_0().child(ui::section("Run with", run, cx))),
            )
            .child(recent)
            .when_some(panel, |d, p| d.child(p))
    }
}
