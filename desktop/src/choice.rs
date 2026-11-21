//! An item for the dropdown pickers: a label shown, a value kept.

use gpui_kit::SharedString;
use gpui_kit::component::searchable_list::SearchableListItem;

#[derive(Clone)]
pub struct Choice {
    value: SharedString,
    title: SharedString,
}

impl Choice {
    pub fn new(value: impl Into<SharedString>, title: impl Into<SharedString>) -> Self {
        Self { value: value.into(), title: title.into() }
    }
}

impl SearchableListItem for Choice {
    type Value = SharedString;

    fn title(&self) -> SharedString {
        self.title.clone()
    }

    fn value(&self) -> &Self::Value {
        &self.value
    }
}
