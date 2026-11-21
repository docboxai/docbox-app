//! Shared building blocks: cards, section labels, stat cards, chips, notices.

use gpui_kit::assets::IconName;
use gpui_kit::component::tag::Tag;
use gpui_kit::component::{ActiveTheme, Icon, Sizable, StyledExt};
use gpui_kit::prelude::FluentBuilder as _;
use gpui_kit::*;

/// A bordered surface, the base of every panel.
pub fn card(cx: &App) -> Div {
    div()
        .v_flex()
        .rounded_lg()
        .border_1()
        .border_color(cx.theme().border)
        .bg(cx.theme().background)
}

/// A small uppercase heading above a group of cards.
pub fn section_label(text: impl Into<SharedString>, cx: &App) -> Div {
    div()
        .text_xs()
        .font_medium()
        .text_color(cx.theme().muted_foreground)
        .child(text.into().to_uppercase())
}

/// A labelled group: the label, then its content.
pub fn section(label: impl Into<SharedString>, content: impl IntoElement, cx: &App) -> Div {
    div().v_flex().gap_2().min_w_0().child(section_label(label, cx)).child(content)
}

pub fn muted(text: impl Into<SharedString>, cx: &App) -> Div {
    div().text_sm().text_color(cx.theme().muted_foreground).child(text.into())
}

pub fn small_muted(text: impl Into<SharedString>, cx: &App) -> Div {
    div().text_xs().text_color(cx.theme().muted_foreground).child(text.into())
}

pub fn error_text(text: impl Into<SharedString>, cx: &App) -> Div {
    div().text_xs().text_color(cx.theme().danger).child(text.into())
}

/// A card with a label on top, a large value and an optional line under it.
pub fn stat_card(
    label: impl Into<SharedString>,
    value: impl Into<SharedString>,
    sub: Option<SharedString>,
    cx: &App,
) -> Div {
    card(cx)
        .gap_1()
        .px_4()
        .py_3()
        .min_w_0()
        .child(small_muted(label, cx))
        .child(div().text_xl().font_semibold().truncate().child(value.into()))
        .when_some(sub, |this, sub| this.child(small_muted(sub, cx)))
}

/// A stat card you can click (it opens another view or does one thing), with an arrow.
pub fn stat_button(
    id: impl Into<ElementId>,
    label: impl Into<SharedString>,
    value: impl Into<SharedString>,
    icon: IconName,
    on_click: impl Fn(&ClickEvent, &mut Window, &mut App) + 'static,
    cx: &App,
) -> Stateful<Div> {
    let hover = cx.theme().accent;
    card(cx)
        .id(id.into())
        .gap_1()
        .px_4()
        .py_3()
        .min_w_0()
        .cursor_pointer()
        .hover(move |s| s.bg(hover))
        .on_click(on_click)
        .child(
            div()
                .h_flex()
                .justify_between()
                .gap_2()
                .child(small_muted(label, cx))
                .child(Icon::new(icon).small().text_color(cx.theme().muted_foreground)),
        )
        .child(div().text_xl().font_semibold().truncate().child(value.into()))
}

/// A green chip when it's good news, amber otherwise.
pub fn fit_chip(ok: bool, text: impl Into<SharedString>) -> Tag {
    let tag = if ok { Tag::success() } else { Tag::warning() };
    tag.small().child(text.into())
}

pub fn chip(text: impl Into<SharedString>) -> Tag {
    Tag::secondary().small().child(text.into())
}

/// A line that something went wrong, in the warning colour.
pub fn notice(text: impl Into<SharedString>, cx: &App) -> Div {
    div()
        .h_flex()
        .gap_2()
        .px_4()
        .py_3()
        .rounded_lg()
        .border_1()
        .border_color(cx.theme().warning)
        .text_sm()
        .child(Icon::new(IconName::TriangleAlert).small().text_color(cx.theme().warning))
        .child(div().min_w_0().flex_1().child(text.into()))
}

/// A thin progress bar.
pub fn progress_bar(id: impl Into<ElementId>, pct: f64) -> gpui_kit::component::progress::Progress {
    gpui_kit::component::progress::Progress::new(id).value(pct.clamp(0.0, 100.0) as f32)
}

/// A row of cards that wrap onto new lines as the window narrows; each grows to fill.
pub fn wrap_row() -> Div {
    div().flex().flex_row().flex_wrap().gap_3().w_full()
}
