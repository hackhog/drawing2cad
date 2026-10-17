"""Pfeilerkennung an synthetischen Strichen (läuft ohne Beispielzeichnungen)."""

import pytest

from drawing_extractor.classify import classify
from drawing_extractor.model import Kind, Line, Stroke

# Maßpfeil wie bei BCT: Basis 0,92 mm, Schenkel 3,53 mm, Spitze bei (3,5 | 0), dazu ein Füllstrich
BASE, LEG0, LEG1, FILL = ((0, -0.46), (0, 0.46)), ((0, -0.46), (3.5, 0)), ((0, 0.46), (3.5, 0)), ((0, 0), (3.5, 0))


def _arrow(paths: tuple[int, int, int, int]) -> list[Stroke]:
    return [Stroke(i, Line(*seg), 0.13, pid) for i, (seg, pid) in enumerate(zip((BASE, LEG0, LEG1, FILL), paths))]


@pytest.mark.parametrize("paths", [(0, 0, 0, 0), (1, 1, 0, 0), (1, 0, 1, 1)])
def test_arrow_may_span_two_consecutive_paths(paths):
    """NX verteilt manche Pfeilspitzen auf zwei aufeinanderfolgende PDF-Pfade."""
    strokes = _arrow(paths)
    arrows = classify(strokes)
    assert len(arrows) == 1 and arrows[0].tip == pytest.approx((3.5, 0))
    assert all(s.kind is Kind.ARROW for s in strokes)


@pytest.mark.parametrize("paths", [(0, 2, 0, 0), (0, 1, 2, 1)])
def test_arrow_is_not_assembled_from_distant_paths(paths):
    strokes = _arrow(paths)
    assert classify(strokes) == []
    assert Kind.ARROW not in {s.kind for s in strokes}
