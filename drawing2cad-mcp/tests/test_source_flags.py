"""Test review flags of a source page and the user decisions on them, with a synthetic analysis."""

import pytest

from drawing2cad_mcp.config import Settings
from drawing2cad_mcp.domain_service import DomainService
from drawing2cad_mcp.domain_store import DomainError
from drawing2cad_mcp.source_flags import review_flags
from test_domain_service import CTX, OTHER, upload


def _drawing(strokes=(), texts=(), views=({"id": 1},)):
    return {"strokes": list(strokes), "text_blocks": list(texts), "views": list(views)}


def _line(i, x0, y0, x1, y1, kind="unclear"):
    return {"id": i, "kind": kind, "type": "line", "p0": [x0, y0], "p1": [x1, y1]}


def test_nearby_unclear_strokes_form_one_flag():
    flags = review_flags(_drawing([_line(1, 0, 0, 5, 0), _line(2, 6, 0, 10, 0), _line(3, 100, 100, 105, 100)]))
    assert [f["stroke_ids"] for f in flags] == [[1, 2], [3]]
    assert [f["flag_id"] for f in flags] == ["strokes-1", "strokes-3"]
    assert flags[0]["bbox"] == [0, 0, 10, 0]


def test_chain_of_strokes_is_merged_transitively():
    # 1-2 and 2-3 are near, 1-3 are not: one flag.
    flags = review_flags(_drawing([_line(1, 0, 0, 1, 0), _line(3, 8, 0, 9, 0), _line(2, 4, 0, 5, 0)]))
    assert [f["stroke_ids"] for f in flags] == [[1, 2, 3]]


def test_classified_strokes_are_not_flagged():
    assert review_flags(_drawing([_line(1, 0, 0, 5, 0, kind="contour")])) == []


def test_circle_uses_its_full_extent():
    circle = {"id": 7, "kind": "unclear", "type": "circle", "center": [10, 20], "radius": 2}
    assert review_flags(_drawing([circle]))[0]["bbox"] == [8, 18, 12, 22]


def test_unreadable_text_and_missing_views_are_flagged():
    text = {"id": 4, "text": "Ø3?5", "bbox": [1, 2, 3, 4]}
    flags = review_flags(_drawing(texts=[text], views=[]))
    assert [(f["flag_id"], f["kind"], f["text"]) for f in flags] == [("views", "no_views", None),
                                                                        ("text-4", "unreadable_text", "Ø3?5")]


ANALYSIS = _drawing([_line(1, 0, 0, 5, 0), _line(2, 50, 50, 55, 50, kind="contour")],
                    [{"id": 3, "text": "Ø?4", "bbox": [10, 10, 14, 13]}])


@pytest.fixture
def flags(tmp_path, monkeypatch):
    settings = Settings.model_validate({"pdf": {"allowed_roots": [str(tmp_path)], "output_root": str(tmp_path / "output")},
                                        "domain": {"enabled": True}})
    service = DomainService(settings)
    source = upload(service)
    calls = []

    def extract(path, **kwargs):
        calls.append(kwargs)
        return {**ANALYSIS, "source": {}}

    monkeypatch.setattr(service._backend(CTX)[1], "extract_drawing", extract)
    yield service, source["source_id"], calls
    service.close()


def decide(service, source_id, flag_id, action, **args):
    return service.call(CTX, "source_flags_decide", {"source_id": source_id, "flag_id": flag_id, "action": action, **args})


def test_decisions_are_stored_per_flag_and_reopen_removes_them(flags):
    service, source_id, calls = flags
    page = service.call(CTX, "source_flags_read", {"source_id": source_id})
    assert [(f["flag_id"], f["decision"]) for f in page["flags"]] == [("strokes-1", None), ("text-3", None)]

    page = decide(service, source_id, "strokes-1", "classify", stroke_class="table", note="Fit tolerance table")
    decision = page["flags"][0]["decision"]
    assert (decision["action"], decision["stroke_class"], decision["note"]) == ("classify", "table", "Fit tolerance table")
    assert decision["flag"]["strokes"] == [ANALYSIS["strokes"][0]]
    page = decide(service, source_id, "text-3", "correct", text="Ø14")
    assert page["flags"][1]["decision"]["text"] == "Ø14"

    page = decide(service, source_id, "strokes-1", "reopen")
    assert page["flags"][0]["decision"] is None
    # Source bytes are immutable, so one analysis serves all calls.
    assert len(calls) == 1


@pytest.mark.parametrize("flag_id, action, args", [
    ("text-3", "classify", {"stroke_class": "table"}),
    ("strokes-1", "classify", {}),
    ("strokes-1", "correct", {"text": "R2"}),
    ("text-3", "correct", {"text": "Ø?4"}),
    ("strokes-1", "ignore", {"text": "R2"}),
])
def test_a_decision_must_fit_its_flag(flags, flag_id, action, args):
    service, source_id, _ = flags
    with pytest.raises(DomainError) as caught:
        decide(service, source_id, flag_id, action, **args)
    assert caught.value.code == "INVALID_ARGUMENT"


def test_unknown_flags_and_other_principals_are_rejected(flags):
    service, source_id, _ = flags
    with pytest.raises(DomainError) as caught:
        decide(service, source_id, "strokes-9", "ignore")
    assert caught.value.code == "NOT_FOUND"
    with pytest.raises(DomainError) as caught:
        service.call(OTHER, "source_flags_decide", {"source_id": source_id, "flag_id": "strokes-1", "action": "ignore"})
    assert caught.value.code == "NOT_FOUND"


def test_export_collects_decisions_and_source_deletion_removes_them(flags):
    service, source_id, _ = flags
    decide(service, source_id, "strokes-1", "ignore", note="Frame zone mark")
    exported = service.call(CTX, "source_flags_export", {})
    assert [(d["source_id"], d["filename"], d["flag_id"], d["action"]) for d in exported["decisions"]] == [
        (source_id, "synthetic.pdf", "strokes-1", "ignore")]
    assert service.call(OTHER, "source_flags_export", {})["decisions"] == []

    service.source_delete(CTX, source_id)
    assert service.call(CTX, "source_flags_export", {})["decisions"] == []
