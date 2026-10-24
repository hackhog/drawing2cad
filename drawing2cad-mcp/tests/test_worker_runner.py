"""Run the actual Linux sandbox and fresh-process CAD validation."""

from pathlib import Path
import json
import os
import sys
import threading

import pytest

from drawing2cad_mcp.worker_runner import WorkerLimits, WorkerRunner
from test_part_schema import sample_description


pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Restricted CAD workers require Linux.")


@pytest.fixture
def runner(tmp_path):
    capability = WorkerRunner.capabilities()
    if os.environ.get("DRAWING2CAD_REQUIRE_SANDBOX") == "1":
        assert capability["available"], capability
    if not capability["available"]:
        pytest.skip(capability["reason"])
    return WorkerRunner(tmp_path / "workers", WorkerLimits(timeout_seconds=60))


def test_restrictions_resource_failures_and_recovery(runner):
    result = runner.probe()
    assert result["status"] == "pass", result
    assert {"network_denial", "outside_write_denial", "outside_read_denial",
            "outside_metadata_denial", "process_creation_denial", "session_escape_denial",
            "timeout", "memory", "crash", "recovery"} <= {row["check"] for row in result["checks"]}


def test_log_limit_is_bounded_and_server_can_recover(runner):
    result = runner.run("probe_logs")
    assert result["error"]["code"] == "WORKER_LOG_LIMIT"
    assert len(result["worker"]["logs"]["stdout"]) <= 8192
    assert runner.run("probe")["status"] == "pass"


def test_build_and_reimport_in_distinct_restricted_workers(runner):
    description = sample_description()
    built = runner.run("build", description=description)
    assert built["status"] == "pass", built
    imported = runner.run("validate", description=description, input_step=Path(built["candidate_step"]))
    assert imported["status"] == "pass", imported
    assert built["worker"]["worker_id"] != imported["worker"]["worker_id"]
    assert imported["measured"]["volume_mm3"] == pytest.approx(built["measured"]["volume_mm3"])
    assert imported["measured"]["bbox_size"] == pytest.approx(built["measured"]["bbox_size"])
    assert built["sandbox"]["process_creation"] == "threads_only"


def test_build_passes_while_the_service_has_many_threads(runner):
    # RLIMIT_NPROC counts all tasks of the user. The service threads must not stop worker threads.
    stop = threading.Event()
    threads = [threading.Thread(target=stop.wait) for _ in range(80)]
    for thread in threads:
        thread.start()
    try:
        built = runner.run("build", description=sample_description())
    finally:
        stop.set()
        for thread in threads:
            thread.join()
    assert built["status"] == "pass", built


def test_concurrent_builds_pass_while_the_service_has_many_threads(runner):
    # Two workers that run at the same time must not use the task margin of each other.
    concurrent = WorkerRunner(runner.storage, WorkerLimits(timeout_seconds=60, concurrent_workers=2))
    stop = threading.Event()
    threads = [threading.Thread(target=stop.wait) for _ in range(80)]
    for thread in threads:
        thread.start()
    results = [None, None]

    def build(index):
        results[index] = concurrent.run("build", description=sample_description())

    builds = [threading.Thread(target=build, args=(index,)) for index in range(2)]
    try:
        for thread in builds:
            thread.start()
        for thread in builds:
            thread.join()
    finally:
        stop.set()
        for thread in threads:
            thread.join()
    for result in results:
        assert result["status"] == "pass", result


# Start threads until thread creation fails, then report the number and the error. The threads are
# daemons, so the worker can stop while they wait. A small stack keeps the address space limit
# (RLIMIT_AS) from stopping thread creation before the task limit does.
THREAD_COUNT_CODE = """import threading
threading.stack_size(256 * 1024)
stop = threading.Event()
started = 0
reason = "none"
try:
    while started < 1000:
        threading.Thread(target=stop.wait, daemon=True).start()
        started += 1
except RuntimeError as error:
    reason = str(error)
raise ValueError(f"started_threads={started};reason={reason}")
"""


def started_threads(result):
    assert result["status"] == "fail", result
    message = result["error"]["message"]
    assert message.startswith("started_threads="), result
    count, reason = message.removeprefix("started_threads=").split(";reason=", 1)
    # Thread creation must stop, and Python reports a failed pthread_create as "can't start new thread".
    assert reason != "none", result
    return int(count)


@pytest.mark.parametrize("workers", [1, 2])
def test_worker_cannot_add_more_tasks_than_its_margin(runner, workers):
    from drawing2cad_mcp.sandbox import WORKER_TASKS

    limited = WorkerRunner(runner.storage, WorkerLimits(timeout_seconds=60, concurrent_workers=workers))
    started = started_threads(limited.run("build_code", description=sample_description(), code=THREAD_COUNT_CODE))
    # The user task count at the worker start includes the worker itself. Threads that the CAD kernel
    # starts later also use the margin.
    assert 0 < started <= WORKER_TASKS * workers
    if workers > 1:
        # A larger margin permits more threads than the margin of one worker.
        assert started > WORKER_TASKS

def test_failed_feature_retains_identifier(runner):
    description = sample_description()
    description["features"].append({"id": "outside", "type": "hole", "position": [100, 100, 5],
                                    "diameter": 3, "evidence_ids": ["drawing"]})
    result = runner.run("build", description=description)
    assert result["error"]["code"] == "HOLE_ENTRY", result
    assert result["error"]["feature_id"] == "outside"
    assert result["checks"] == [
        {"check": "feature_execution", "feature_id": "base", "status": "pass"},
        {"check": "feature_execution", "feature_id": "outside", "status": "fail"},
    ]


def test_worker_cannot_redirect_parent_record(runner):
    victim = runner.storage.parent / "victim.txt"
    victim.write_text("unchanged", encoding="utf-8")
    code = "from pathlib import Path\nPath('worker-record.json').symlink_to('../../victim.txt')\nraise ValueError('stop')"
    result = runner.run("build_code", description=sample_description(), code=code)
    assert result["status"] == "fail", result
    assert victim.read_text(encoding="utf-8") == "unchanged"
    record_path = runner.storage / (result["worker"]["worker_id"] + ".json")
    assert json.loads(record_path.read_text())["result"]["status"] == "fail"


def test_nonfinite_worker_result_is_a_protocol_error(runner):
    code = "import sys, os\nsys.stdout.write('D2C_RESULT:{\"status\":\"pass\",\"value\":NaN}\\n')\nsys.stdout.flush()\nos._exit(0)"
    result = runner.run("build_code", description=sample_description(), code=code)
    assert result["error"]["code"] == "WORKER_PROTOCOL_ERROR"
    assert runner.run("probe")["status"] == "pass"


def test_inline_code_uses_current_description_without_changing_validation(runner):
    description = sample_description()
    code = ("length = description['parameters'][0]['value']\n"
            "result = build123d.Box(length, 10, 5, align=(build123d.Align.MIN,) * 3)\n"
            "description['measurements'][0]['expected'] = [999, 10, 5]\n")
    first = runner.run("build_code", description=description, code=code)
    assert first["status"] == "pass", first
    description["parameters"][0]["value"] = 25
    description["measurements"][0]["expected"] = [25, 10, 5]
    second = runner.run("build_code", description=description, code=code)
    assert second["status"] == "pass", second
    assert second["measured"]["bbox_size"] == pytest.approx([25, 10, 5])
    assert first["measured"]["bbox_size"] == pytest.approx([20, 10, 5])


def test_projection_completes_and_keeps_timeout_failure_and_recovery(runner):
    from drawing2cad_mcp.drawing_contract import description_digest
    from test_drafting import drawing_fixture

    description, spec = drawing_fixture()
    description["features"] = [feature for feature in description["features"] if feature["id"] != "hole"]
    spec["views"][0]["geometry"] = [primitive for primitive in spec["views"][0]["geometry"] if primitive["id"] != "hole_circle"]
    spec["views"][0]["dimensions"] = [dimension for dimension in spec["views"][0]["dimensions"] if dimension["id"] != "hole_diameter"]
    spec["description_sha256"] = description_digest(description)
    built = runner.run("build", description=description)
    assert built["status"] == "pass", built
    drawn = runner.run("drawing", description=description, drawing_spec=spec, revision=1)
    assert drawn["status"] == "pass", drawn
    pdf = next(Path(item["path"]) for item in drawn["artifacts"] if item["name"] == "drawing.pdf")
    views = [{"view_id": "top", "toward_viewer": "+Z", "up": "+Y", "region": [15, 20, 150, 125], "mm_per_sheet_mm": 1.0},
             {"view_id": "front", "toward_viewer": "-Y", "up": "+Z", "region": [155, 20, 280, 125], "mm_per_sheet_mm": 1.0}]
    inputs = {"input_step": Path(built["candidate_step"]), "input_pdf": pdf, "page": 1, "views": views}
    result = runner.run("projection_check", **inputs)
    assert result["status"] == "pass", result
    assert all(view["status"] == "pass" for view in result["views"])
    assert result["sandbox"]["network"] == "socket_syscalls_denied"
    assert '"stage": "result_generation", "event": "completed"' in result["worker"]["logs"]["stderr"]
    limited = runner.run("projection_check", timeout=1, **inputs)
    assert limited["error"]["code"] == "WORKER_TIMEOUT", limited
    assert "views" not in limited and "artifacts" not in limited
    assert limited["worker"]["duration_seconds"] < 5
    assert '"stage": "dependencies", "event": "started"' in limited["worker"]["logs"]["stderr"]
    assert len(limited["worker"]["logs"]["stderr"]) <= 8192
    assert runner.run("probe")["status"] == "pass"
