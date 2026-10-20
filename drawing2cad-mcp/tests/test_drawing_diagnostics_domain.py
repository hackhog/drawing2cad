"""Check diagnostic publication, revision bindings, and drawing input safety."""

from copy import deepcopy
import hashlib
import json

import pytest

from drawing2cad_mcp.domain_store import DomainError
from drawing2cad_mcp.drawing_contract import description_digest, drawing_validate
from test_domain_service import (CTX, OTHER, artifact_bytes, call, coverage, domain,
                                 render_and_build, review)


def overlapping_spec(spec):
    value = deepcopy(spec)
    value["notes"].append(deepcopy(value["notes"][0]))
    return value


def test_layout_diagnostics_are_bound_private_and_not_deliverable(domain):
    service, source, description, spec, _ = domain
    render_and_build(domain)
    call(service, "export_step", coverage=coverage(source))
    bad = overlapping_spec(spec)
    result = call(service, "drawing_render", drawing_spec=bad)
    drawing = result["drawing"]
    assert result["status"] == drawing["status"] == "fail"
    assert drawing["diagnostic_only"] is True
    assert drawing["review"] is None
    assert drawing["drawing_sha256"] == description_digest(bad)
    assert drawing["description_sha256"] == description_digest(description)
    assert drawing["part_revision"] == 1
    assert {item["role"] for item in drawing["artifacts"]} == {
        "drawing_diagnostic_preview", "drawing_diagnostic_report"}
    for item in drawing["artifacts"]:
        assert item["revision"] == 1
        raw = artifact_bytes(service, item)
        if item["role"] == "drawing_diagnostic_preview":
            assert raw.startswith(b"%PDF-")
            preview = service.call(CTX, "artifact_preview", {"artifact_id": item["artifact_id"], "dpi": 36})
            assert preview
        else:
            report = json.loads(raw)
            assert report["diagnostic_only"] is True
            assert report["status"] == "fail"
            assert report["drawing_sha256"] == description_digest(bad)
            assert report["description_sha256"] == description_digest(description)
            assert report["part_revision"] == 1
            assert '"path"' not in raw.decode()
        with pytest.raises(DomainError):
            service.call(OTHER, "artifact_read", {"artifact_id": item["artifact_id"]})
        with pytest.raises(DomainError):
            service.call(OTHER, "artifact_preview", {"artifact_id": item["artifact_id"]})
    pairs = drawing["report"]["diagnostics"]["collision_pairs"]
    assert any({pair["first_id"], pair["second_id"]} == {"note_0", "note_1"} for pair in pairs)
    with pytest.raises(DomainError) as error:
        review(service, source, drawing["drawing_sha256"])
    assert error.value.code == "DRAWING_REVIEW_CONFLICT"
    # The STEP release states the failed drawing and links its diagnostic files.
    failed = call(service, "export_step", coverage=coverage(source))["release"]["drawing"]
    assert failed["status"] == "failed" and failed["defects"]
    assert {item["role"] for item in failed["artifacts"]} == {"drawing_diagnostic_preview", "drawing_diagnostic_report"}
    state = service.call(CTX, "part_read", {"run_id": "plate"})
    assert state["part"]["release"]["drawing"]["status"] == "failed"
    corrected = call(service, "drawing_render", drawing_spec=spec)
    assert corrected["status"] == "pass"
    assert not corrected["drawing"].get("diagnostic_only", False)
    review(service, source, corrected["drawing"]["drawing_sha256"])
    assert call(service, "export_step", coverage=coverage(source))["release"]["drawing"]["status"] == "unverified"


@pytest.mark.parametrize("change", ["unknown", "coordinate", "scale", "dimension", "stale", "nan"])
def test_invalid_drawing_input_preserves_previous_drawing_and_release(domain, change):
    service, source, _, spec, runner = domain
    render_and_build(domain)
    call(service, "export_step", coverage=coverage(source))
    before = service.call(CTX, "part_read", {"run_id": "plate"})
    worker_calls = len(runner.calls)
    bad = deepcopy(spec)
    private = "C:/sensitive/secret-source.pdf"
    if change == "unknown":
        bad[private] = private
    elif change == "coordinate":
        bad["views"][0]["origin"] = [private, 120]
    elif change == "scale":
        bad["views"][0]["scale"] = True
    elif change == "dimension":
        bad["views"][0]["dimensions"][0]["expected"] = 999
    elif change == "stale":
        bad["description_sha256"] = "a" * 64
    else:
        bad["views"][0]["scale"] = float("nan")
    if change == "nan":
        with pytest.raises(DomainError) as error:
            call(service, "drawing_render", drawing_spec=bad)
        assert error.value.code == "INVALID_ARGUMENT"
    else:
        result = call(service, "drawing_render", drawing_spec=bad)
        assert result["status"] == "fail"
        assert result.get("diagnostic_eligible") is False
        assert private not in json.dumps(result)
        assert not result.get("artifacts")
    after = service.call(CTX, "part_read", {"run_id": "plate"})
    assert after["drawing"] == before["drawing"]
    assert after["part"]["release"] == before["part"]["release"]
    assert len(runner.calls) == worker_calls


@pytest.mark.parametrize("fault", ["binding", "path", "hash", "role", "report_binding", "report_path"])
def test_bad_worker_diagnostics_are_never_published(domain, monkeypatch, fault):
    service, source, _, spec, runner = domain
    render_and_build(domain)
    before = service.call(CTX, "artifact_list", {"run_id": "plate"})
    original = runner.run

    def tamper(operation, **kwargs):
        result = original(operation, **kwargs)
        assert result.get("diagnostic_only") is True
        if fault == "binding":
            result["part_revision"] += 1
        elif fault == "path":
            result["artifacts"][0]["path"] += "/wrong.pdf"
        elif fault == "hash":
            result["artifacts"][0]["sha256"] = "0" * 64
        elif fault == "role":
            result["artifacts"][0]["role"] = "technical_drawing"
        else:
            from pathlib import Path
            item = next(item for item in result["artifacts"] if item["name"].endswith(".json"))
            path = Path(item["path"])
            report = json.loads(path.read_text(encoding="utf-8"))
            if fault == "report_binding":
                report["drawing_sha256"] = "0" * 64
            else:
                report["path"] = str(path)
            raw = json.dumps(report).encode()
            path.write_bytes(raw)
            item.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        return result

    monkeypatch.setattr(runner, "run", tamper)
    with pytest.raises(DomainError):
        call(service, "drawing_render", drawing_spec=overlapping_spec(spec))
    assert service.call(CTX, "artifact_list", {"run_id": "plate"}) == before
    # The release states the failed drawing and links no unverified diagnostic file.
    drawing = call(service, "export_step", coverage=coverage(source))["release"]["drawing"]
    assert drawing["status"] == "failed" and drawing["artifacts"] == []


def test_preview_eligibility_uses_all_defects_before_truncation(domain):
    _, _, description, spec, _ = domain
    bad = deepcopy(spec)
    for index in range(110):
        primitive = deepcopy(bad["views"][0]["geometry"][0])
        primitive.update(id=f"clipped_{index}", start=[1000, index], end=[1100, index])
        bad["views"][0]["geometry"].append(primitive)
    bad["notes"][0]["evidence_ids"] = ["missing_evidence"]
    report = drawing_validate(bad, description, 1)
    assert report["total_defects"] > 100
    assert report["defects_truncated"] is True
    assert {item["code"] for item in report["defects"]} == {"geometry_clipping"}
    assert report["diagnostic_eligible"] is False
