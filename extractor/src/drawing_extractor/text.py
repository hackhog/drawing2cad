"""Text lesen ohne Textebene: Die Schrift liegt als gefüllte Glyphen-Umrisse einer einzigen
NX-Schrift vor. Jedes Zeichen wird in Leserichtung gedreht, gerastert und mit gelabelten
Vorlagen (`glyph_templates.json`) verglichen. Deterministisch, ohne OCR-Programm oder Modell.

Leserichtung: bei mehreren Zeichen aus der Lage der Zeichenmittelpunkte, bei einem einzelnen
Zeichen aus der nächstgelegenen Maßlinie (Maßzahlen stehen parallel zur Maßlinie). Welche der
zwei Richtungen auf dieser Achse gilt, entscheidet der Vorlagenvergleich; bei Gleichstand gilt
DIN 406: lesbar von unten oder von rechts.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import cache
from importlib import resources

from PIL import Image, ImageChops, ImageDraw

from .geometry import Grid, UnionFind, expand, overlaps, point_segment_distance, union
from .model import Glyph, Kind, Line, Point, Stroke, TextBlock

BITMAP = 16  # Kantenlänge des Vergleichsrasters
_SUPERSAMPLE = 4
_UNKNOWN = "?"
_MAX_DISTANCE = 0.22  # schlechtere Treffer gelten als nicht erkannt
_SPACE_GAP = 0.30  # Lücke in Schrifthöhen: Zeichenabstand ≤ 0,26, Wortabstand ≥ 0,35 (gemessen)
# Schmale Zeichen haben in der NX-Schrift breite Ränder; neben „1“ misst die Lücke bis 0,35.
_SIDE_BEARING = {"1": 0.15}


@dataclass(slots=True)
class Features:
    bitmap: tuple[float, ...]  # BITMAP×BITMAP Grauwerte 0..1, Zeichen seitenverhältnistreu zentriert
    aspect: float  # Breite / Höhe
    rel_height: float  # Höhe / Schrifthöhe des Blocks
    rel_bottom: float  # Unterkante relativ zur Grundlinie, in Schrifthöhen (Komma > 0)


@dataclass(slots=True)
class Template:
    char: str
    features: Features


def distance(a: Features, b: Features) -> float:
    pix = sum(abs(x - y) for x, y in zip(a.bitmap, b.bitmap)) / len(a.bitmap)
    return (
        pix
        + 0.3 * abs(a.rel_height - b.rel_height)
        + 0.3 * abs(a.rel_bottom - b.rel_bottom)
        + 0.1 * abs(min(a.aspect, 3.0) - min(b.aspect, 3.0))
    )


# --- Gruppieren -------------------------------------------------------------------------------


def is_section_bar(g: Glyph) -> bool:
    """Gefüllte Balken am Schnittverlauf (Enden, Knicke) sind keine Schrift: einzelnes Viereck
    mit langer Seite ≥ 3 mm. Der Bindestrich in „A-A“ ist nur 1,3 mm lang."""
    if len(g.contours) != 1 or len(g.contours[0]) > 5:
        return False
    return max(g.bbox[2] - g.bbox[0], g.bbox[3] - g.bbox[1]) >= 3.0


def group_glyphs(glyphs: list[Glyph]) -> list[list[Glyph]]:
    """Zeichen, deren Boxen nah beieinander liegen, bilden einen Block. Schnittbalken fallen weg."""
    glyphs = [g for g in glyphs if not is_section_bar(g)]
    uf = UnionFind(len(glyphs))
    grid = Grid(cell=3.0)
    for i, g in enumerate(glyphs):
        grid.insert(i, g.bbox)
    for i, g in enumerate(glyphs):
        size = max(g.bbox[2] - g.bbox[0], g.bbox[3] - g.bbox[1])
        reach = expand(g.bbox, 0.6 * size)
        for j in grid.query(reach):
            if j != i and overlaps(reach, glyphs[j].bbox):
                uf.union(i, j)
    groups = [[glyphs[m] for m in members] for members in uf.groups(range(len(glyphs))).values()]
    groups.sort(key=lambda gs: (round(union(g.bbox for g in gs)[1] / 10), union(g.bbox for g in gs)[0]))
    return groups


# --- Geometrie in Leserichtung ----------------------------------------------------------------


def _center(g: Glyph) -> Point:
    return (g.bbox[0] + g.bbox[2]) / 2, (g.bbox[1] + g.bbox[3]) / 2


def _axis_from_glyphs(members: list[Glyph]) -> float | None:
    """Hauptachse der Zeichenmittelpunkte in Grad [0, 180), None bei nur einem Zeichen."""
    if len(members) < 2:
        return None
    pts = [_center(g) for g in members]
    mx = sum(p[0] for p in pts) / len(pts)
    my = sum(p[1] for p in pts) / len(pts)
    sxx = sum((p[0] - mx) ** 2 for p in pts)
    syy = sum((p[1] - my) ** 2 for p in pts)
    sxy = sum((p[0] - mx) * (p[1] - my) for p in pts)
    return math.degrees(0.5 * math.atan2(2 * sxy, sxx - syy)) % 180.0


def _axis_from_dimension(members: list[Glyph], strokes: list[Stroke]) -> float | None:
    """Richtung der nächstgelegenen Maßlinie (höchstens 6 mm entfernt)."""
    c = _center(members[0])
    best, best_d = None, 6.0
    for s in strokes:
        if s.kind is Kind.DIMENSION and isinstance(s.geom, Line) and s.geom.length > 2.0:
            d = point_segment_distance(c, s.geom.p0, s.geom.p1)[0]
            if d < best_d:
                best, best_d = s.geom.angle, d
    return best


def _readable(phi: float) -> bool:
    """DIN 406: von unten (Richtung nach rechts) oder von rechts (Richtung nach oben) lesbar.
    phi in Blattkoordinaten (y nach unten)."""
    c, s = math.cos(math.radians(phi)), math.sin(math.radians(phi))
    return c > 1e-3 or (abs(c) <= 1e-3 and s < 0)


def _local(p: Point, phi: float) -> Point:
    """(u, v): u entlang der Leserichtung, v quer dazu nach „unten“ der Schrift."""
    c, s = math.cos(math.radians(phi)), math.sin(math.radians(phi))
    return p[0] * c + p[1] * s, -p[0] * s + p[1] * c


def _extent(g: Glyph, phi: float) -> tuple[float, float, float, float]:
    pts = [_local(p, phi) for contour in g.contours for p in contour]
    us, vs = [p[0] for p in pts], [p[1] for p in pts]
    return min(us), min(vs), max(us), max(vs)


def _rasterize(g: Glyph, phi: float, ext: tuple[float, float, float, float]) -> tuple[float, ...]:
    u0, v0, u1, v1 = ext
    w, h = max(u1 - u0, 1e-6), max(v1 - v0, 1e-6)
    size = BITMAP * _SUPERSAMPLE
    scale = (size - 2 * _SUPERSAMPLE) / max(w, h)
    off_u = (size - w * scale) / 2
    off_v = (size - h * scale) / 2
    img = Image.new("1", (size, size), 0)
    for contour in g.contours:
        mask = Image.new("1", (size, size), 0)
        pts = [_local(p, phi) for p in contour]
        ImageDraw.Draw(mask).polygon([((u - u0) * scale + off_u, (v - v0) * scale + off_v) for u, v in pts], fill=1)
        img = ImageChops.logical_xor(img, mask)  # Even-Odd: Innenkonturen stanzen aus
    small = img.convert("L").resize((BITMAP, BITMAP), Image.Resampling.BOX)
    return tuple(round(v / 255, 3) for v in small.get_flattened_data())


def block_features(members: list[Glyph], phi: float) -> tuple[list[tuple[Features, float, float]], float]:
    """Features je Zeichen in Leserichtung sortiert, mit (u0, u1) für die Leerzeichen-Erkennung,
    dazu die Schrifthöhe des Blocks in mm."""
    exts = [_extent(g, phi) for g in members]
    height = max(e[3] - e[1] for e in exts)
    bottoms = sorted(e[3] for e in exts)
    baseline = bottoms[len(bottoms) // 2]
    out = []
    for g, e in sorted(zip(members, exts), key=lambda ge: ge[1][0]):
        w, h = e[2] - e[0], e[3] - e[1]
        f = Features(_rasterize(g, phi, e), round(w / max(h, 1e-6), 3), round(h / height, 3),
                     round((e[3] - baseline) / height, 3))
        out.append((f, e[0], e[2]))
    return out, height


def reading_axis(members: list[Glyph], strokes: list[Stroke]) -> float:
    axis = _axis_from_glyphs(members)
    if axis is None:
        axis = _axis_from_dimension(members, strokes)
    return 0.0 if axis is None else axis


# --- Erkennen ---------------------------------------------------------------------------------


@cache
def load_templates() -> tuple[Template, ...]:
    raw = json.loads(resources.files(__package__).joinpath("glyph_templates.json").read_text(encoding="utf-8"))
    return tuple(
        Template(t["char"], Features(tuple(int(c, 16) / 15 for c in t["bitmap"]), t["aspect"],
                                     t["rel_height"], t["rel_bottom"]))
        for t in raw["templates"]
    )


def _match(f: Features, templates: tuple[Template, ...]) -> tuple[str, float]:
    best = min(templates, key=lambda t: distance(f, t.features))
    d = distance(f, best.features)
    return (best.char if d <= _MAX_DISTANCE else _UNKNOWN), d


def _read(members: list[Glyph], phi: float, templates: tuple[Template, ...]) -> tuple[str, float]:
    feats, height = block_features(members, phi)
    matches = [_match(f, templates) for f, _, _ in feats]
    text = matches[0][0]
    for (prev, _), (ch, _), (_, _, end), (_, start, _) in zip(matches, matches[1:], feats, feats[1:]):
        gap = (start - end) / height - _SIDE_BEARING.get(prev, 0.0) - _SIDE_BEARING.get(ch, 0.0)
        text += (" " if gap > _SPACE_GAP else "") + ch
    return text, sum(d for _, d in matches) / len(matches)


def read_blocks(glyphs: list[Glyph], strokes: list[Stroke]) -> list[TextBlock]:
    """Gruppiert die Zeichen zu Blöcken und liest jeden Block."""
    templates = load_templates()
    blocks = []
    for i, members in enumerate(group_glyphs(glyphs)):
        axis = reading_axis(members, strokes)
        candidates = []
        for phi in (axis, axis + 180.0):
            text, cost = _read(members, phi, templates)
            # Bei (fast) gleichen Kosten gewinnt die normgerechte Leserichtung
            candidates.append((round(cost, 2), not _readable(phi), text, phi))
        _, _, text, phi = min(candidates)
        bbox = union(g.bbox for g in members)
        blocks.append(TextBlock(i + 1, bbox, len(members), text, round(-phi % 360.0, 1)))
    return blocks
