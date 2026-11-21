use gpui_kit::*;

use crate::state::AppState;

pub struct BenchmarksView {
    _state: Entity<AppState>,
}

impl BenchmarksView {
    pub fn new(state: Entity<AppState>, _: &mut Window, _: &mut Context<Self>) -> Self {
        Self { _state: state }
    }
}

impl Render for BenchmarksView {
    fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
        div().child("Coming in this rewrite")
    }
}

/// "PaddleOCR (PP-OCRv5 server)" -> "PaddleOCR": a model's name without its size.
pub fn short_name(name: &str) -> String {
    name.split(" (").next().unwrap_or(name).trim().to_string()
}
