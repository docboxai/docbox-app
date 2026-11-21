//! The controls for one model's setup: the compact table cell (Install / progress + Pause /
//! Resume / Installed) and the full panel (progress, the main action, Remove with an inline
//! confirm, and Use as default).

use gpui_kit::assets::IconName;
use gpui_kit::component::button::{Button, ButtonVariants};
use gpui_kit::component::spinner::Spinner;
use gpui_kit::component::{ActiveTheme, Disableable, Icon, Sizable, StyledExt};
use gpui_kit::prelude::FluentBuilder as _;
use gpui_kit::*;

use crate::api::{ModelInfo, ModelStatus, SettingsUpdate};
use crate::format;
use crate::jobs::{JobPhase, ModelJob};
use crate::state::{AppState, View};
use crate::ui;

pub fn is_cloud(model: &ModelInfo) -> bool {
    model.engine == "nvidia-nim"
}

pub fn size_label(model: &ModelInfo) -> String {
    if is_cloud(model) { "Cloud".into() } else { format::mb(model.approx_download_mb) }
}

/// The button for a model that needs something set up under Connections first, named for
/// what clicking it lets you do; None when nothing outside DocBox is missing.
pub fn setup_action_label(model: &ModelInfo) -> Option<String> {
    match model.status {
        ModelStatus::Ready => None,
        ModelStatus::NeedsPrerequisite => Some(format!(
            "Set up {}",
            format::prerequisite_label(model.prerequisite.as_deref().unwrap_or(""))
        )),
        _ if is_cloud(model) => Some("Add a key".into()),
        _ => None,
    }
}

fn install_label(model: &ModelInfo) -> &'static str {
    if model.engine == "ollama" { "Pull" } else { "Install" }
}

fn install_icon(model: &ModelInfo) -> IconName {
    if model.status == ModelStatus::NeedsEngine { IconName::PackagePlus } else { IconName::Download }
}

fn open_connections(state: &Entity<AppState>) -> impl Fn(&ClickEvent, &mut Window, &mut App) + 'static {
    let state = state.clone();
    move |_, _, cx| state.update(cx, |s, cx| s.navigate(View::Connections, cx))
}

fn job_action(
    job: &Entity<ModelJob>,
    f: fn(&mut ModelJob, &mut Context<ModelJob>),
) -> impl Fn(&ClickEvent, &mut Window, &mut App) + 'static {
    let job = job.clone();
    move |_, _, cx| job.update(cx, |j, cx| f(j, cx))
}

/// The compact control for a table row.
pub fn action_cell(job: &Entity<ModelJob>, state: &Entity<AppState>, cx: &App) -> AnyElement {
    let j = job.read(cx);
    let model = &j.model;
    let id = SharedString::from(format!("cell-{}", model.id));
    if j.busy() {
        return div()
            .h_flex()
            .gap_2()
            .text_sm()
            .text_color(cx.theme().muted_foreground)
            .child(Spinner::new().small())
            .child(format!("{}%", j.progress.round() as i64))
            .child(
                Button::new(id)
                    .ghost()
                    .small()
                    .icon(IconName::Pause)
                    .tooltip(if j.phase == JobPhase::Pausing { "Pausing after the current step" } else { "Pause" })
                    .disabled(j.phase == JobPhase::Pausing)
                    .on_click(job_action(job, ModelJob::pause)),
            )
            .into_any_element();
    }
    if j.phase == JobPhase::Paused {
        return Button::new(id)
            .outline()
            .small()
            .icon(IconName::Play)
            .label(format!("Resume · {}%", j.progress.round() as i64))
            .on_click(job_action(job, ModelJob::start))
            .into_any_element();
    }
    if model.status == ModelStatus::Ready {
        return div()
            .h_flex()
            .gap_1()
            .text_sm()
            .font_medium()
            .text_color(cx.theme().success)
            .child(Icon::new(IconName::Check).small())
            .child(if is_cloud(model) { "Connected" } else { "Installed" })
            .into_any_element();
    }
    if let Some(label) = setup_action_label(model) {
        return Button::new(id)
            .small()
            .outline()
            .label(label)
            .tooltip("Opens Connections")
            .on_click(open_connections(state))
            .into_any_element();
    }
    Button::new(id)
        .small()
        .primary()
        .icon(install_icon(model))
        .label(install_label(model))
        .when(model.status == ModelStatus::NeedsEngine, |b| {
            b.tooltip("Installs this engine once, then the model")
        })
        .on_click(job_action(job, ModelJob::start))
        .into_any_element()
}

/// The full control. Under a table row, which has its own action cell and size column,
/// `in_row` leaves out the main action and the size, so they aren't there twice.
pub fn setup_panel(job: &Entity<ModelJob>, state: &Entity<AppState>, in_row: bool, cx: &App) -> Div {
    let j = job.read(cx);
    let model = &j.model;
    let key = model.id.clone();
    let is_default = state.read(cx).default_model_id() == Some(model.id.as_str());
    let busy = j.busy();

    let mut panel = div().v_flex().gap_3();

    if busy || j.phase == JobPhase::Paused {
        let status = match j.phase {
            JobPhase::Paused => "Paused".to_string(),
            JobPhase::Pausing => "Pausing after the current step…".to_string(),
            _ => j.message.clone().unwrap_or_else(|| "Working…".into()),
        };
        panel = panel.child(
            div()
                .v_flex()
                .gap_1()
                .child(ui::progress_bar(SharedString::from(format!("progress-{key}")), j.progress))
                .child(
                    div()
                        .h_flex()
                        .gap_2()
                        .text_xs()
                        .when(busy, |d| d.child(Spinner::new().xsmall()))
                        .child(div().flex_1().min_w_0().truncate().child(status))
                        .child(format!("{}%", j.progress.round() as i64)),
                ),
        );
    }

    if j.confirm_remove {
        let question = if model.engine == "ollama" {
            "Remove this model? Ollama deletes it from its own store.".to_string()
        } else {
            format!("Remove this model? Frees about {}.", format::mb(model.approx_download_mb))
        };
        let keep = job.clone();
        panel = panel.child(
            div()
                .h_flex()
                .flex_wrap()
                .gap_2()
                .px_3()
                .py_2()
                .rounded_md()
                .bg(cx.theme().muted)
                .child(div().flex_1().min_w_0().text_sm().child(question))
                .child(
                    Button::new(SharedString::from(format!("remove-yes-{key}")))
                        .small()
                        .danger()
                        .label(if j.removing { "Removing…" } else { "Remove" })
                        .disabled(j.removing)
                        .on_click(job_action(job, ModelJob::remove)),
                )
                .child(
                    Button::new(SharedString::from(format!("remove-no-{key}")))
                        .small()
                        .outline()
                        .label("Keep")
                        .on_click(move |_, _, cx| keep.update(cx, |j, cx| j.ask_remove(false, cx))),
                ),
        );
    } else {
        let mut row = div().h_flex().flex_wrap().gap_2();
        if !in_row {
            row = row.child(div().mr_auto().text_xs().text_color(cx.theme().muted_foreground).child(size_label(model)));
        }
        if busy && !in_row {
            row = row.child(
                Button::new(SharedString::from(format!("pause-{key}")))
                    .small()
                    .outline()
                    .icon(IconName::Pause)
                    .label("Pause")
                    .disabled(j.phase == JobPhase::Pausing)
                    .on_click(job_action(job, ModelJob::pause)),
            );
        }
        if j.phase == JobPhase::Paused && !in_row {
            row = row.child(
                Button::new(SharedString::from(format!("resume-{key}")))
                    .small()
                    .primary()
                    .icon(IconName::Play)
                    .label("Resume")
                    .on_click(job_action(job, ModelJob::start)),
            );
        }
        if j.phase == JobPhase::Idle && model.status == ModelStatus::Ready {
            let state2 = state.clone();
            let id = model.id.clone();
            row = row.child(
                Button::new(SharedString::from(format!("default-{key}")))
                    .small()
                    .outline()
                    .icon(if is_default { IconName::Check } else { IconName::Star })
                    .label(if is_default { "Default" } else { "Use as default" })
                    .disabled(is_default)
                    .on_click(move |_, _, cx| {
                        let patch = SettingsUpdate { default_model_id: Some(id.clone()), ..Default::default() };
                        state2.update(cx, |s, cx| s.update_settings(patch, cx));
                    }),
            );
            if !is_cloud(model) {
                let ask = job.clone();
                row = row.child(
                    Button::new(SharedString::from(format!("remove-{key}")))
                        .small()
                        .ghost()
                        .icon(IconName::Trash)
                        .label("Remove")
                        .on_click(move |_, _, cx| ask.update(cx, |j, cx| j.ask_remove(true, cx))),
                );
            }
        }
        if j.phase == JobPhase::Idle && model.status != ModelStatus::Ready && !in_row {
            row = row.child(match setup_action_label(model) {
                Some(label) => Button::new(SharedString::from(format!("setup-{key}")))
                    .small()
                    .outline()
                    .label(label)
                    .tooltip("Opens Connections")
                    .on_click(open_connections(state)),
                None => Button::new(SharedString::from(format!("install-{key}")))
                    .small()
                    .primary()
                    .icon(install_icon(model))
                    .label(if model.status == ModelStatus::NeedsEngine {
                        "Install engine + model"
                    } else {
                        install_label(model)
                    })
                    .on_click(job_action(job, ModelJob::start)),
            });
        }
        panel = panel.child(row);
    }
    if let Some(err) = &j.error {
        panel = panel.child(ui::error_text(err.clone(), cx));
    }
    panel
}
