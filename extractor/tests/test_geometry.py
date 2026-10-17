import math

import pytest

from drawing_extractor.geometry import angle_diff, circle_through, fit_arcs_into_circles
from drawing_extractor.model import Arc, Line
from drawing_extractor.reader import _bezier_to_geometry

K = 0.5522847498  # Bézier-Kontrollpunktfaktor für Viertelkreise


def test_circle_through_three_points():
    center, r = circle_through((10, 0), (0, 10), (-10, 0))
    assert center == pytest.approx((0, 0), abs=1e-9)
    assert r == pytest.approx(10)


def test_circle_through_collinear_is_none():
    assert circle_through((0, 0), (1, 1), (2, 2)) is None


def test_angle_diff_wraps_at_180():
    assert angle_diff(179.0, 1.0) == pytest.approx(2.0)


def _quarter(cx, cy, r, quadrant):
    a0 = math.radians(90 * quadrant)
    a1 = a0 + math.pi / 2
    p0 = (cx + r * math.cos(a0), cy + r * math.sin(a0))
    p3 = (cx + r * math.cos(a1), cy + r * math.sin(a1))
    c1 = (p0[0] - K * r * math.sin(a0), p0[1] + K * r * math.cos(a0))
    c2 = (p3[0] + K * r * math.sin(a1), p3[1] - K * r * math.cos(a1))
    return p0, c1, c2, p3


def test_four_bezier_quarters_become_one_circle():
    parts = [g for q in range(4) for g in _bezier_to_geometry(*_quarter(50, 40, 7.5, q))]
    assert all(isinstance(g, Arc) for g in parts)
    merged = fit_arcs_into_circles([(g, 0.35, 0) for g in parts])
    assert len(merged) == 1
    circle = merged[0][0]
    assert circle.is_circle
    assert circle.center == pytest.approx((50, 40), abs=1e-3)
    assert circle.radius == pytest.approx(7.5, abs=1e-3)


def test_dashed_circle_stays_in_pieces():
    arcs = [Arc((0, 0), 5, start, 60) for start in (0, 90, 180, 270)]
    merged = fit_arcs_into_circles([(a, 0.13, 0) for a in arcs])
    assert len(merged) == 4


def test_non_circular_bezier_becomes_polyline():
    parts = _bezier_to_geometry((0, 0), (10, 0), (10, 2), (20, 30))
    assert all(isinstance(g, Line) for g in parts)
