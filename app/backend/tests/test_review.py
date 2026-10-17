from drawing_demo.review import review_flags


def _drawing(strokes=(), texts=(), views=({"id": 1},)):
    return {"strokes": list(strokes), "text_blocks": list(texts), "views": list(views)}


def _line(i, x0, y0, x1, y1, kind="unclear"):
    return {"id": i, "kind": kind, "type": "line", "p0": [x0, y0], "p1": [x1, y1]}


def test_nearby_unclear_strokes_form_one_flag():
    flags = review_flags(_drawing([_line(1, 0, 0, 5, 0), _line(2, 6, 0, 10, 0), _line(3, 100, 100, 105, 100)]))
    assert [f["stroke_ids"] for f in flags] == [[1, 2], [3]]
    assert flags[0]["bbox"] == [0, 0, 10, 0]


def test_chain_of_strokes_is_merged_transitively():
    # 1–2 und 2–3 liegen nah, 1–3 nicht: trotzdem eine Stelle
    flags = review_flags(_drawing([_line(1, 0, 0, 1, 0), _line(3, 8, 0, 9, 0), _line(2, 4, 0, 5, 0)]))
    assert [f["stroke_ids"] for f in flags] == [[1, 2, 3]]


def test_classified_strokes_are_not_flagged():
    assert review_flags(_drawing([_line(1, 0, 0, 5, 0, kind="contour")])) == []


def test_circle_uses_its_full_extent():
    circle = {"id": 7, "kind": "unclear", "type": "circle", "center": [10, 20], "radius": 2}
    assert review_flags(_drawing([circle]))[0]["bbox"] == [8, 18, 12, 22]


def test_unreadable_text_and_missing_views_are_flagged():
    text = {"id": 1, "text": "Ø3?5", "bbox": [1, 2, 3, 4]}
    kinds = [f["kind"] for f in review_flags(_drawing(texts=[text], views=[]))]
    assert kinds == ["no_views", "unreadable_text"]
