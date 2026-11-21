//! App-wide state every view reads: the backend client, the current view, this computer's
//! hardware, the settings, model download jobs, and a revision counter that views refetch
//! on when something app-wide changes (a setting, an install, a finished read).

use std::collections::HashMap;

use gpui_kit::*;

use crate::api::{Api, ApiResult, DeviceCapabilities, ModelInfo, Settings, SettingsUpdate};
use crate::jobs::ModelJob;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum View {
    Setup,
    Models,
    Read,
    Benchmarks,
    Connections,
    Device,
}

impl View {
    pub const ALL: [View; 6] =
        [View::Setup, View::Models, View::Read, View::Benchmarks, View::Connections, View::Device];

    pub fn label(self) -> &'static str {
        match self {
            View::Setup => "Setup",
            View::Models => "Models",
            View::Read => "Read a file",
            View::Benchmarks => "Benchmarks",
            View::Connections => "Connections",
            View::Device => "This device",
        }
    }

    pub fn eyebrow(self) -> &'static str {
        match self {
            View::Setup => "STEP 1 OF 3",
            View::Models => "STEP 2 OF 3",
            View::Read => "STEP 3 OF 3",
            View::Benchmarks => "THE LOCAL OCR TEST BENCH",
            View::Connections => "OUTSIDE PROGRAMS",
            View::Device => "HARDWARE",
        }
    }

    pub fn title(self) -> &'static str {
        match self {
            View::Setup => "Choose an engine",
            View::Models => "Your models",
            View::Read => "Read a file",
            View::Benchmarks => "Benchmarks",
            View::Connections => "Connections",
            View::Device => "This device",
        }
    }

    pub fn icon(self) -> gpui_kit::assets::IconName {
        use gpui_kit::assets::IconName;
        match self {
            View::Setup => IconName::SlidersHorizontal,
            View::Models => IconName::Box,
            View::Read => IconName::FileText,
            View::Benchmarks => IconName::Gauge,
            View::Connections => IconName::Plug,
            View::Device => IconName::Monitor,
        }
    }
}

pub struct AppState {
    pub api: Api,
    pub view: View,
    pub caps: Option<DeviceCapabilities>,
    pub settings: Option<Settings>,
    pub settings_error: Option<String>,
    /// Bumped whenever something app-wide changes, so views that show derived numbers
    /// refetch.
    pub revision: u64,
    /// One download/install job per model, shared by every view that shows the model, so
    /// progress survives switching views.
    jobs: HashMap<String, Entity<ModelJob>>,
    _tasks: Vec<Task<()>>,
}

/// Run a blocking backend call off the UI thread, then hand its result to `done` on the
/// view that asked, if it's still open.
pub fn call<V: 'static, T: Send + 'static>(
    cx: &mut Context<V>,
    api: Api,
    work: impl FnOnce(&Api) -> ApiResult<T> + Send + 'static,
    done: impl FnOnce(&mut V, ApiResult<T>, &mut Context<V>) + 'static,
) -> Task<()> {
    cx.spawn(async move |this, cx| {
        let result = cx.background_spawn(async move { work(&api) }).await;
        this.update(cx, |view, cx| {
            done(view, result, cx);
            cx.notify();
        })
        .ok();
    })
}

impl AppState {
    pub fn new(api: Api, cx: &mut Context<Self>) -> Self {
        let mut this = Self {
            api,
            view: View::Setup,
            caps: None,
            settings: None,
            settings_error: None,
            revision: 0,
            jobs: HashMap::new(),
            _tasks: Vec::new(),
        };
        this.refresh_caps(cx);
        let task = call(cx, this.api.clone(), |api| api.get_settings(), |this, result, _| {
            match result {
                Ok(settings) => this.settings = Some(settings),
                Err(err) => this.settings_error = Some(err),
            }
        });
        this._tasks.push(task);
        this
    }

    pub fn navigate(&mut self, view: View, cx: &mut Context<Self>) {
        if self.view != view {
            self.view = view;
            cx.notify();
        }
    }

    pub fn bump(&mut self, cx: &mut Context<Self>) {
        self.revision += 1;
        cx.notify();
    }

    pub fn refresh_caps(&mut self, cx: &mut Context<Self>) {
        call(cx, self.api.clone(), |api| api.device_capabilities(), |this, result, _| {
            // Views that need the numbers show their own "couldn't reach" message.
            if let Ok(caps) = result {
                this.caps = Some(caps);
            }
        })
        .detach();
    }

    pub fn update_settings(&mut self, patch: SettingsUpdate, cx: &mut Context<Self>) {
        self.settings_error = None;
        call(cx, self.api.clone(), move |api| api.update_settings(&patch), |this, result, cx| {
            match result {
                Ok(settings) => {
                    this.settings = Some(settings);
                    this.bump(cx);
                }
                Err(err) => this.settings_error = Some(err),
            }
        })
        .detach();
    }

    pub fn default_model_id(&self) -> Option<&str> {
        self.settings.as_ref().and_then(|s| s.default_model_id.as_deref())
    }

    pub fn cloud_enabled(&self) -> bool {
        self.settings.as_ref().is_some_and(|s| s.cloud_enabled)
    }

    /// The job for `model`, created on first use and refreshed with the latest listing
    /// (which may carry a job started elsewhere, by the CLI or before a view switch).
    pub fn job(&mut self, model: &ModelInfo, cx: &mut Context<Self>) -> Entity<ModelJob> {
        if let Some(job) = self.jobs.get(&model.id) {
            let job = job.clone();
            let model = model.clone();
            job.update(cx, |job, cx| job.set_model(model, cx));
            return job;
        }
        let state = cx.entity().downgrade();
        let api = self.api.clone();
        let model = model.clone();
        let id = model.id.clone();
        let job = cx.new(|cx| ModelJob::new(model, api, state, cx));
        self.jobs.insert(id, job.clone());
        job
    }
}
