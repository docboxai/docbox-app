//! One model's download/install job: start, follow its progress, pause, resume, remove.

use std::collections::HashSet;
use std::time::Duration;

use gpui_kit::*;

use crate::api::{Api, DownloadState, ModelInfo};
use crate::state::AppState;

const POLL: Duration = Duration::from_secs(1);

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum JobPhase {
    Idle,
    Running,
    Pausing,
    Paused,
}

pub struct ModelJob {
    pub model: ModelInfo,
    pub phase: JobPhase,
    pub progress: f64,
    pub message: Option<String>,
    pub error: Option<String>,
    pub removing: bool,
    /// The inline "Remove this model?" question is showing.
    pub confirm_remove: bool,
    job_id: Option<String>,
    // Jobs this one saw end. A listing fetched before one ended still shows it running;
    // adopting it again would see it end again and refresh again, over and over.
    ended: HashSet<String>,
    api: Api,
    state: WeakEntity<AppState>,
    _poll: Option<Task<()>>,
}

impl ModelJob {
    pub fn new(model: ModelInfo, api: Api, state: WeakEntity<AppState>, cx: &mut Context<Self>) -> Self {
        let mut this = Self {
            phase: JobPhase::Idle,
            progress: 0.0,
            message: None,
            error: None,
            removing: false,
            confirm_remove: false,
            job_id: None,
            ended: HashSet::new(),
            api,
            state,
            _poll: None,
            model: model.clone(),
        };
        this.adopt(cx);
        this
    }

    pub fn busy(&self) -> bool {
        matches!(self.phase, JobPhase::Running | JobPhase::Pausing)
    }

    /// A refreshed listing: new status, and maybe a job started elsewhere.
    pub fn set_model(&mut self, model: ModelInfo, cx: &mut Context<Self>) {
        self.model = model;
        self.adopt(cx);
    }

    fn adopt(&mut self, cx: &mut Context<Self>) {
        let Some(job) = self.model.active_job.clone() else { return };
        if self.phase != JobPhase::Idle
            || self.job_id.as_deref() == Some(job.job_id.as_str())
            || self.ended.contains(&job.job_id)
        {
            return;
        }
        self.job_id = Some(job.job_id);
        self.progress = job.progress_pct.unwrap_or(0.0);
        self.message = job.message;
        if job.state == DownloadState::Paused {
            self.phase = JobPhase::Paused;
        } else {
            self.phase = JobPhase::Running;
            self.poll(cx);
        }
        cx.notify();
    }

    fn changed(&self, cx: &mut Context<Self>) {
        if let Some(state) = self.state.upgrade() {
            state.update(cx, |state, cx| state.bump(cx));
        }
    }

    fn poll(&mut self, cx: &mut Context<Self>) {
        let Some(job_id) = self.job_id.clone() else { return };
        let api = self.api.clone();
        let model_id = self.model.id.clone();
        self._poll = Some(cx.spawn(async move |this, cx| {
            loop {
                let (api2, model_id2, job_id2) = (api.clone(), model_id.clone(), job_id.clone());
                let result = cx
                    .background_spawn(async move { api2.download_status(&model_id2, &job_id2) })
                    .await;
                let keep_going = this
                    .update(cx, |job, cx| {
                        let go = match result {
                            Ok(s) => {
                                job.progress = s.progress_pct.unwrap_or(0.0);
                                job.message = if s.state == DownloadState::Installing {
                                    Some(format!("Installing engine · {}", s.message.clone().unwrap_or_default()))
                                } else {
                                    s.message.clone()
                                };
                                match s.state {
                                    DownloadState::Paused => {
                                        job.phase = JobPhase::Paused;
                                        false
                                    }
                                    DownloadState::Done | DownloadState::Error => {
                                        job.ended.insert(job_id.clone());
                                        if s.state == DownloadState::Error {
                                            job.error = Some(s.message.unwrap_or_else(|| "Setup failed".into()));
                                        }
                                        job.phase = JobPhase::Idle;
                                        job.job_id = None;
                                        job.changed(cx);
                                        false
                                    }
                                    _ => true,
                                }
                            }
                            Err(err) => {
                                job.error = Some(err);
                                job.phase = JobPhase::Idle;
                                job.job_id = None;
                                false
                            }
                        };
                        cx.notify();
                        go
                    })
                    .unwrap_or(false);
                if !keep_going {
                    break;
                }
                cx.background_executor().timer(POLL).await;
            }
        }));
    }

    pub fn start(&mut self, cx: &mut Context<Self>) {
        self.error = None;
        let model_id = self.model.id.clone();
        crate::state::call(cx, self.api.clone(), move |api| api.start_download(&model_id), |job, result, cx| {
            match result {
                Ok(started) => {
                    job.job_id = Some(started.job_id);
                    job.phase = JobPhase::Running;
                    job.poll(cx);
                }
                Err(err) => job.error = Some(err),
            }
        })
        .detach();
    }

    pub fn pause(&mut self, cx: &mut Context<Self>) {
        let Some(job_id) = self.job_id.clone() else { return };
        self.phase = JobPhase::Pausing;
        cx.notify();
        let model_id = self.model.id.clone();
        crate::state::call(cx, self.api.clone(), move |api| api.pause_download(&model_id, &job_id), |job, result, _| {
            if let Err(err) = result {
                job.error = Some(err);
            }
        })
        .detach();
    }

    pub fn remove(&mut self, cx: &mut Context<Self>) {
        self.removing = true;
        self.error = None;
        cx.notify();
        let model_id = self.model.id.clone();
        crate::state::call(cx, self.api.clone(), move |api| api.delete_model(&model_id), |job, result, cx| {
            job.removing = false;
            match result {
                Ok(()) => {
                    job.phase = JobPhase::Idle;
                    job.job_id = None;
                    job.confirm_remove = false;
                    job.changed(cx);
                }
                Err(err) => job.error = Some(err),
            }
        })
        .detach();
    }

    pub fn ask_remove(&mut self, ask: bool, cx: &mut Context<Self>) {
        self.confirm_remove = ask;
        cx.notify();
    }
}
