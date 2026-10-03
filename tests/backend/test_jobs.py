from docbox.backend.core.jobs import DownloadJobStore


def test_create_and_get() -> None:
    store = DownloadJobStore()
    job = store.create("some-model")

    assert job.model_id == "some-model"
    assert job.state == "pending"

    fetched = store.get(job.job_id)
    assert fetched is not None
    assert fetched.job_id == job.job_id


def test_get_unknown_job_returns_none() -> None:
    store = DownloadJobStore()
    assert store.get("does-not-exist") is None


def test_update_transitions_state_and_progress() -> None:
    store = DownloadJobStore()
    job = store.create("some-model")

    store.update(job.job_id, state="downloading", progress_pct=50.0, message="halfway")
    updated = store.get(job.job_id)
    assert updated is not None
    assert updated.state == "downloading"
    assert updated.progress_pct == 50.0
    assert updated.message == "halfway"

    store.update(job.job_id, state="done", progress_pct=100.0)
    finished = store.get(job.job_id)
    assert finished is not None
    assert finished.state == "done"
    assert finished.progress_pct == 100.0
    # message wasn't passed on the last update, so it should be unchanged
    assert finished.message == "halfway"


def test_update_unknown_job_is_a_noop() -> None:
    store = DownloadJobStore()
    store.update("does-not-exist", state="done")  # should not raise
