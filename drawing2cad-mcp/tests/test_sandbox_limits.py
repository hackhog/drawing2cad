"""Check the worker task limit without the Linux sandbox."""

import os
import sys
import threading

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


@pytest.mark.skipif(sys.platform != "linux", reason="The task count reads /proc.")
def test_task_limit_follows_the_current_user_tasks():
    before = sandbox.task_limit()
    stop = threading.Event()
    threads = [threading.Thread(target=stop.wait) for _ in range(20)]
    for thread in threads:
        thread.start()
    try:
        during = sandbox.task_limit()
    finally:
        stop.set()
        for thread in threads:
            thread.join()
    assert before >= threading.active_count() + sandbox.WORKER_TASKS
    assert during >= before + 20
