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


def test_task_limit_adds_the_worker_margin_to_the_user_tasks(monkeypatch):
    monkeypatch.setattr(sandbox, "user_task_count", lambda: 70)
    import resource
    _, hard = resource.getrlimit(resource.RLIMIT_NPROC)
    expected = 70 + sandbox.WORKER_TASKS
    assert sandbox.task_limit() == (expected if hard == resource.RLIM_INFINITY else min(expected, hard))


def test_task_count_errors_are_sandbox_errors(monkeypatch):
    def fail():
        raise FileNotFoundError("/proc")

    monkeypatch.setattr(sandbox, "user_task_count", fail)
    with pytest.raises(sandbox.SandboxError):
        sandbox.task_limit()
