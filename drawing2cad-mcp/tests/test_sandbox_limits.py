"""Check the worker task limit without the Linux sandbox."""

import os

import pytest

from drawing2cad_mcp import sandbox


pytestmark = pytest.mark.skipif(not hasattr(os, "getuid"), reason="Task limits use POSIX user IDs.")


def write_status(proc, pid, uid, threads):
    (proc / pid).mkdir()
    (proc / pid / "status").write_text(f"Name:\tworker\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\nThreads:\t{threads}\n")


def test_user_task_count_adds_the_threads_of_own_processes(tmp_path):
    uid = os.getuid()
    write_status(tmp_path, "10", uid, 70)
    write_status(tmp_path, "11", uid, 3)
    write_status(tmp_path, "12", uid + 1, 500)
    (tmp_path / "self").mkdir()
    (tmp_path / "13").mkdir()  # A process that ended has no status file.
    assert sandbox.user_task_count(tmp_path) == 73


def test_task_limit_adds_one_worker_margin_for_each_concurrent_worker(monkeypatch):
    import resource
    monkeypatch.setattr(sandbox, "user_task_count", lambda: 70)
    monkeypatch.setattr(resource, "getrlimit", lambda kind: (1024, resource.RLIM_INFINITY))
    assert sandbox.task_limit() == 70 + sandbox.WORKER_TASKS
    assert sandbox.task_limit(3) == 70 + 3 * sandbox.WORKER_TASKS


def test_task_limit_accepts_a_hard_limit_with_the_complete_margin(monkeypatch):
    import resource
    monkeypatch.setattr(sandbox, "user_task_count", lambda: 70)
    monkeypatch.setattr(resource, "getrlimit", lambda kind: (1024, 70 + 2 * sandbox.WORKER_TASKS))
    assert sandbox.task_limit(2) == 70 + 2 * sandbox.WORKER_TASKS


def test_task_limit_fails_when_the_hard_limit_is_too_small(monkeypatch):
    import resource
    monkeypatch.setattr(sandbox, "user_task_count", lambda: 70)
    monkeypatch.setattr(resource, "getrlimit", lambda kind: (1024, 70 + 2 * sandbox.WORKER_TASKS - 1))
    with pytest.raises(sandbox.SandboxError, match="hard RLIMIT_NPROC limit 197 is too small.*70 tasks.*2 concurrent workers need 128"):
        sandbox.task_limit(2)


@pytest.mark.parametrize("workers", [0, -1, 1.0, True])
def test_task_limit_rejects_invalid_worker_counts(workers):
    with pytest.raises(sandbox.SandboxError):
        sandbox.task_limit(workers)


def test_task_count_errors_are_sandbox_errors(monkeypatch):
    def fail():
        raise FileNotFoundError("/proc")

    monkeypatch.setattr(sandbox, "user_task_count", fail)
    with pytest.raises(sandbox.SandboxError):
        sandbox.task_limit()
