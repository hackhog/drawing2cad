"""Durable job tests use controlled dispatchers, not CAD acceptance data."""

from concurrent.futures import ThreadPoolExecutor
import json
import multiprocessing
import os
import sqlite3
import threading
import time

import pytest

from drawing2cad_mcp.domain_jobs import JobCancelled, JobService, TERMINAL_STATES
from drawing2cad_mcp.domain_store import AccessContext, DomainError


OWNER = AccessContext("owner")
OTHER = AccessContext("other")


def crash_worker(root, entered):
    """Keep a job active until the test terminates this process."""
    def dispatch(*args):
        entered.set()
        threading.Event().wait(60)
        return {}

    service = JobService(root, dispatch)
    service.start()
    threading.Event().wait(60)


def arguments(**changes):
    return {"run_id": "run_test", "expected_revision": 1, **changes}


def wait_for(service, job_id, states=TERMINAL_STATES):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = service.get(OWNER, job_id)
        if job["state"] in states:
            return job
        time.sleep(0.01)
    pytest.fail(f"Job did not enter {states}: {job['state']}")


def test_job_result_persists_across_service_restart(tmp_path):
    calls = []

    def dispatch(context, operation, values, event):
        calls.append((context.subject, operation, values))
        return {"artifact_id": "artifact_test"}

    service = JobService(tmp_path, dispatch)
    job = service.submit(OWNER, "drawing_render", arguments(), "first")
    assert job["state"] == "queued"
    service.start()
    try:
        finished = wait_for(service, job["job_id"])
        assert finished["state"] == "succeeded"
        assert finished["result"] == {"artifact_id": "artifact_test"}
        assert finished["started_at"] <= finished["finished_at"]
        assert "owner" not in finished
        assert str(tmp_path) not in json.dumps(finished)
    finally:
        service.close()
    restarted = JobService(tmp_path, dispatch)
    restarted.start()
    try:
        assert restarted.get(OWNER, job["job_id"]) == finished
        assert len(calls) == 1
    finally:
        restarted.close()


@pytest.mark.parametrize("orphan_state", ["running", "cancel_requested"])
def test_restart_marks_orphan_interrupted_and_resumes_only_queued(tmp_path, orphan_state):
    calls = []
    service = JobService(tmp_path, lambda ctx, op, values, token: calls.append(values["run_id"]) or {"ok": True})
    orphan = service.submit(OWNER, "drawing_render", arguments(run_id="orphan"), "orphan")
    queued = service.submit(OWNER, "drawing_render", arguments(run_id="queued"), "queued")
    with sqlite3.connect(tmp_path / "jobs.sqlite3") as database:
        database.execute("UPDATE jobs SET state=? WHERE job_id=?", (orphan_state, orphan["job_id"]))
    service.start()
    try:
        assert service.get(OWNER, orphan["job_id"])["state"] == "interrupted"
        assert service.get(OWNER, orphan["job_id"])["error"]["code"] == "JOB_INTERRUPTED"
        assert wait_for(service, queued["job_id"])["state"] == "succeeded"
        assert calls == ["queued"]
    finally:
        service.close()


def test_another_live_service_cannot_recover_or_claim_jobs(tmp_path):
    entered, release = threading.Event(), threading.Event()

    def dispatch(*args):
        entered.set()
        assert release.wait(5)
        return {"ok": True}

    first, second = JobService(tmp_path, dispatch), JobService(tmp_path, dispatch)
    first.start()
    try:
        job = first.submit(OWNER, "drawing_render", arguments(), "first")
        assert entered.wait(5)
        with pytest.raises(DomainError, match="Another job service"):
            second.start()
        assert first.get(OWNER, job["job_id"])["state"] == "running"
    finally:
        release.set()
        first.close()
    second.start()
    second.close()


def test_process_crash_releases_lock_and_does_not_repeat_effects(tmp_path):
    service = JobService(tmp_path, lambda *args: pytest.fail("An uncertain job must not be repeated."))
    job = service.submit(OWNER, "drawing_render", arguments(), "first")
    context = multiprocessing.get_context("spawn")
    entered = context.Event()
    process = context.Process(target=crash_worker, args=(tmp_path, entered))
    process.start()
    try:
        assert entered.wait(10)
        with pytest.raises(DomainError, match="Another job service"):
            service.start()
        assert service.get(OWNER, job["job_id"])["state"] == "running"
    finally:
        process.terminate()
        process.join(10)
        assert not process.is_alive()
    service.start()
    try:
        assert service.get(OWNER, job["job_id"])["state"] == "interrupted"
    finally:
        service.close()


def test_close_waits_for_running_dispatcher_before_releasing_lock(tmp_path):
    entered, release, closed = threading.Event(), threading.Event(), threading.Event()

    def dispatch(*args):
        entered.set()
        assert release.wait(5)
        return {"ok": True}

    service, other = JobService(tmp_path, dispatch), JobService(tmp_path, dispatch)
    service.start()
    job = service.submit(OWNER, "drawing_render", arguments(), "first")
    assert entered.wait(5)
    closing = threading.Thread(target=lambda: (service.close(), closed.set()))
    closing.start()
    try:
        assert not closed.wait(0.1)
        with pytest.raises(DomainError):
            other.start()
    finally:
        release.set()
        closing.join(5)
    assert closed.is_set()
    assert service.get(OWNER, job["job_id"])["state"] == "succeeded"
    other.start()
    other.close()


def test_queued_cancellation_prevents_dispatch(tmp_path):
    calls = []
    service = JobService(tmp_path, lambda *args: calls.append(args) or {})
    job = service.submit(OWNER, "drawing_render", arguments(), "first")
    cancelled = service.cancel(OWNER, job["job_id"])
    assert cancelled["state"] == "cancelled"
    assert cancelled["started_at"] is None
    service.start()
    service.close()
    assert calls == []
    assert service.cancel(OWNER, job["job_id"]) == cancelled


@pytest.mark.parametrize("outcome", ["success", "failure", "cancelled"])
def test_running_cancellation_preserves_actual_outcome(tmp_path, outcome):
    entered, release, observed = threading.Event(), threading.Event(), threading.Event()

    def dispatch(ctx, operation, values, event):
        entered.set()
        assert event.wait(5)
        observed.set()
        assert release.wait(5)
        if outcome == "cancelled":
            raise JobCancelled()
        if outcome == "failure":
            raise RuntimeError("private C:/secret/file.pdf")
        return {"side_effect_completed": True}

    service = JobService(tmp_path, dispatch)
    service.start()
    try:
        job = service.submit(OWNER, "drawing_render", arguments(), "first")
        assert entered.wait(5)
        requested = service.cancel(OWNER, job["job_id"])
        assert requested["state"] == "cancel_requested"
        assert requested["finished_at"] is None
        assert observed.wait(5)
        release.set()
        finished = wait_for(service, job["job_id"])
        assert finished["state"] == {"success": "succeeded", "failure": "failed", "cancelled": "cancelled"}[outcome]
        assert finished["cancellation_requested_at"] is not None
        assert "secret" not in json.dumps(finished)
    finally:
        release.set()
        service.close()


def test_cancel_through_another_service_instance_reaches_active_token(tmp_path):
    entered = threading.Event()

    def dispatch(ctx, operation, values, event):
        entered.set()
        assert event.wait(5)
        raise JobCancelled()

    service = JobService(tmp_path, dispatch)
    service.start()
    try:
        job = service.submit(OWNER, "drawing_render", arguments(), "first")
        assert entered.wait(5)
        other_interface = JobService(tmp_path, dispatch)
        assert other_interface.cancel(OWNER, job["job_id"])["state"] == "cancel_requested"
        assert wait_for(service, job["job_id"])["state"] == "cancelled"
    finally:
        service.close()


def test_worker_failure_is_safe_and_next_job_runs(tmp_path):
    def dispatch(ctx, operation, values, event):
        if values["run_id"] == "bad":
            raise RuntimeError("Traceback: C:/secret/file.pdf; password=hidden")
        return {"ok": True}

    service = JobService(tmp_path, dispatch)
    service.start()
    try:
        bad = service.submit(OWNER, "drawing_render", arguments(run_id="bad"), "bad")
        good = service.submit(OWNER, "drawing_render", arguments(), "good")
        failed = wait_for(service, bad["job_id"])
        assert failed["state"] == "failed"
        assert failed["error"]["code"] == "JOB_EXECUTION_FAILED"
        assert "secret" not in json.dumps(failed)
        assert "password" not in json.dumps(failed)
        assert wait_for(service, good["job_id"])["state"] == "succeeded"
    finally:
        service.close()


def test_idempotency_is_atomic_across_instances_and_scoped_to_owner(tmp_path):
    services = [JobService(tmp_path, lambda *args: {}) for _ in range(4)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda index: services[index % 4].submit(OWNER, "drawing_render", arguments(), "same-key"), range(20)))
    assert len({item["job_id"] for item in results}) == 1
    assert len(services[0].list(OWNER)) == 1
    other = services[0].submit(OTHER, "drawing_render", arguments(), "same-key")
    assert other["job_id"] != results[0]["job_id"]
    with pytest.raises(DomainError, match="different job request"):
        services[0].submit(OWNER, "drawing_render", arguments(expected_revision=2), "same-key")


def test_owner_isolation_and_bounded_lists(tmp_path):
    service = JobService(tmp_path, lambda *args: {})
    first = service.submit(OWNER, "drawing_render", arguments(), "first")
    service.submit(OWNER, "drawing_render", arguments(run_id="second"), "second")
    assert service.list(OTHER) == []
    assert len(service.list(OWNER, limit=1)) == 1
    assert service.list(OWNER, run_id="run_test")[0]["job_id"] == first["job_id"]
    for call in (service.get, service.cancel):
        with pytest.raises(DomainError, match="not accessible"):
            call(OTHER, first["job_id"])
    for limit in (0, 101, True, 1.5):
        with pytest.raises(DomainError):
            service.list(OWNER, limit=limit)


@pytest.mark.parametrize("values", [
    {}, {"run_id": "run"}, arguments(expected_revision=True), arguments(expected_revision=0),
    arguments(expected_revision=2**63), arguments(value=float("nan")), arguments(value="x" * 262_144),
    arguments(value="\ud800"),
])
def test_job_argument_bounds(tmp_path, values):
    service = JobService(tmp_path, lambda *args: {})
    with pytest.raises(DomainError):
        service.submit(OWNER, "drawing_render", values, "first")
    assert service.list(OWNER) == []


@pytest.mark.parametrize("result", [None, {"too_large": "x" * 1_048_576}, {"infinite": float("inf")}])
def test_result_bounds_preserve_worker_availability(tmp_path, result):
    service = JobService(tmp_path, lambda *args: result)
    service.start()
    try:
        job = service.submit(OWNER, "drawing_render", arguments(), "first")
        finished = wait_for(service, job["job_id"])
        assert finished["state"] == "failed"
        assert finished["error"]["code"] == "JOB_RESULT_INVALID"
        assert finished["result"] is None
    finally:
        service.close()


def test_concurrency_bound_and_once_only_claim(tmp_path):
    lock, entered, release = threading.Lock(), threading.Event(), threading.Event()
    active = 0
    maximum = 0
    calls = []

    def dispatch(ctx, operation, values, event):
        nonlocal active, maximum
        with lock:
            calls.append(values["run_id"])
            active += 1
            maximum = max(maximum, active)
            if active == 2:
                entered.set()
        assert release.wait(5)
        with lock:
            active -= 1
        return {}

    service = JobService(tmp_path, dispatch, concurrency=2)
    jobs = [service.submit(OWNER, "drawing_render", arguments(run_id=str(index)), str(index)) for index in range(6)]
    service.start()
    try:
        assert entered.wait(5)
        assert len(calls) == 2
        release.set()
        for job in jobs:
            assert wait_for(service, job["job_id"])["state"] == "succeeded"
        assert maximum == 2
        assert sorted(calls) == [str(index) for index in range(6)]
    finally:
        release.set()
        service.close()


def test_removed_operation_is_not_replayed_after_restart(tmp_path):
    calls = []
    first = JobService(tmp_path, lambda *args: {}, operations=("old_operation",))
    job = first.submit(OWNER, "old_operation", arguments(), "first")
    updated = JobService(tmp_path, lambda *args: calls.append(args) or {})
    updated.start()
    try:
        finished = wait_for(updated, job["job_id"])
        assert finished["state"] == "failed"
        assert finished["error"]["code"] == "JOB_OPERATION_UNSUPPORTED"
        assert calls == []
    finally:
        updated.close()


def test_domain_error_details_are_bounded(tmp_path):
    def dispatch(*args):
        raise DomainError("CUSTOM_ERROR", "x" * 20_000)

    service = JobService(tmp_path, dispatch)
    service.start()
    try:
        job = service.submit(OWNER, "drawing_render", arguments(), "first")
        failed = wait_for(service, job["job_id"])
        assert failed["state"] == "failed"
        assert failed["error"]["code"] == "JOB_EXECUTION_FAILED"
        assert len(json.dumps(failed)) < 2048
    finally:
        service.close()


def test_queue_limit_is_atomic_and_idempotent_retries_remain_available(tmp_path):
    services = [JobService(tmp_path, lambda *args: {}, max_pending=2) for _ in range(4)]

    def submit(index):
        try:
            return services[index % 4].submit(OWNER, "drawing_render", arguments(), str(index))
        except DomainError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(submit, range(20)))
    accepted = [item for item in results if isinstance(item, dict)]
    assert len(accepted) == 2
    assert results.count("JOB_QUEUE_FULL") == 18
    first_index = next(index for index, value in enumerate(results) if isinstance(value, dict))
    retry = services[0].submit(OWNER, "drawing_render", arguments(), str(first_index))
    assert retry["job_id"] == results[first_index]["job_id"]
    services[0].cancel(OWNER, accepted[0]["job_id"])
    assert services[0].submit(OWNER, "drawing_render", arguments(), "new")["state"] == "queued"


def test_running_and_cancel_requested_jobs_count_toward_limit(tmp_path):
    entered, release = threading.Event(), threading.Event()

    def dispatch(*args):
        entered.set()
        assert release.wait(5)
        return {}

    service = JobService(tmp_path, dispatch, max_pending=1)
    service.start()
    try:
        job = service.submit(OWNER, "drawing_render", arguments(), "first")
        assert entered.wait(5)
        for cancel in (False, True):
            if cancel:
                service.cancel(OWNER, job["job_id"])
            with pytest.raises(DomainError) as caught:
                service.submit(OWNER, "drawing_render", arguments(), "second")
            assert caught.value.code == "JOB_QUEUE_FULL"
        release.set()
        assert wait_for(service, job["job_id"])["state"] == "succeeded"
        assert service.submit(OWNER, "drawing_render", arguments(), "second")["state"] == "queued"
    finally:
        release.set()
        service.close()


@pytest.mark.parametrize("filename", ["jobs.sqlite3", "jobs.lock", "jobs.sqlite3-journal"])
def test_linked_job_storage_is_rejected(tmp_path, filename):
    root = tmp_path / "jobs"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.write_bytes(b"must remain unchanged")
    os.link(outside, root / filename)
    with pytest.raises(DomainError) as caught:
        JobService(root, lambda *args: {})
    assert caught.value.code == "UNSAFE_PATH"
    assert outside.read_bytes() == b"must remain unchanged"


def test_symlink_job_root_is_rejected(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    linked = tmp_path / "linked"
    try:
        linked.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("The host does not permit symbolic links.")
    with pytest.raises(DomainError) as caught:
        JobService(linked, lambda *args: {})
    assert caught.value.code == "UNSAFE_PATH"
    assert list(outside.iterdir()) == []
