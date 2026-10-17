"""Test annotation rules with synthetic strokes and text blocks."""

from drawing2cad_mcp.vector.annotations import mark_annotations
from drawing2cad_mcp.vector.model import Kind, Line, Stroke, TextBlock


def _line(i, p0, p1, width=0.17):
    return Stroke(i, Line(p0, p1), width, i, Kind.CONTOUR)


def _text(i, box, value):
    return TextBlock(i, box, 0, value, 0.0, 1.0, "native_pdf_text")


def _table_texts():
    # Two columns with three stacked rows between separators at x=0, 20, and 40.
    return [_text(n, (x + 2, y, x + 12, y + 3), "3,000") for n, (x, y) in
            enumerate(((x, y) for x in (0, 20) for y in (1, 5, 9)))]


def test_free_table_separators_with_stacked_text_are_annotation():
    strokes = [_line(i, (x, 0), (x, 13), 0.34) for i, x in enumerate((0, 20, 40))]
    mark_annotations(strokes, _table_texts())
    assert {s.kind for s in strokes} == {Kind.ANNOTATION}


def test_separator_that_touches_part_geometry_stays_contour():
    strokes = [_line(i, (x, 0), (x, 13), 0.34) for i, x in enumerate((0, 20, 40))]
    strokes.append(_line(3, (40, 13), (60, 13), 0.34))  # A part edge meets the third line.
    mark_annotations(strokes, _table_texts())
    assert strokes[2].kind is Kind.CONTOUR and strokes[3].kind is Kind.CONTOUR


def test_parallel_lines_with_one_text_row_stay_contour():
    strokes = [_line(i, (x, 0), (x, 6), 0.17) for i, x in enumerate((0, 6))]
    mark_annotations(strokes, [_text(0, (1, 1, 5, 4), "6")])
    assert {s.kind for s in strokes} == {Kind.CONTOUR}


def _corner():
    return [_line(0, (0, 0), (0, 4.2)), _line(1, (0, 4.2), (4.2, 4.2))]


def test_edge_condition_corner_next_to_signed_value_is_annotation():
    strokes = _corner()
    mark_annotations(strokes, [_text(0, (1, -3, 6, 0), "+0,4")])
    assert {s.kind for s in strokes} == {Kind.ANNOTATION}


def test_corner_without_signed_value_stays_contour():
    strokes = _corner()
    mark_annotations(strokes, [_text(0, (1, -3, 6, 0), "0,4")])
    assert {s.kind for s in strokes} == {Kind.CONTOUR}


def _bracket(start_id, x, bulge):
    """Four short segments from y=0 to y=3. A negative bulge gives '(', a positive bulge gives ')'."""
    pts = [(x, 0), (x + bulge * 0.5, 0.75), (x + bulge * 0.6, 1.5), (x + bulge * 0.5, 2.25), (x, 3)]
    return [_line(start_id + n, a, b) for n, (a, b) in enumerate(zip(pts, pts[1:]))]


def test_drawn_parentheses_around_text_are_annotation_and_wrap_the_text():
    strokes = _bracket(0, 0.4, -0.5) + _bracket(4, 7.6, 0.5)
    text = _text(0, (0.9, 0.2, 7.1, 2.9), "0,07")
    mark_annotations(strokes, [text])
    assert {s.kind for s in strokes} == {Kind.ANNOTATION}
    assert text.text == "(0,07)"


def test_one_sided_bracket_shape_stays_contour():
    strokes = _bracket(0, 0.4, -0.5)
    text = _text(0, (0.9, 0.2, 7.1, 2.9), "0,07")
    mark_annotations(strokes, [text])
    assert {s.kind for s in strokes} == {Kind.CONTOUR}
    assert text.text == "0,07"
