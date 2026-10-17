"""Erzeugt die Zeichenvorlagen `src/drawing_extractor/glyph_templates.json`.

Zwei Schritte, weil ein Mensch (oder Claude) dazwischen die Zeichen benennt:

    uv run python scripts/build_glyph_templates.py dump ../resources/Drawing2CAD/*/*_dwg.pdf
        → scripts/glyphs/clusters.json + clusters_<n>.png (je Zeile eine Gruppe mit allen Mitgliedern)
    # scripts/glyphs/labels.json anlegen: {"<Cluster-Nr>": "<Zeichen>", …}, "" = verwerfen
    uv run python scripts/build_glyph_templates.py build
        → src/drawing_extractor/glyph_templates.json

Die Leserichtung wird beim Dump ohne Vorlagen bestimmt (Achse + DIN-Regel). Falsch gedrehte
Gruppen im Kontaktbogen deshalb verwerfen statt benennen.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

from drawing_extractor.classify import classify
from drawing_extractor.reader import read_pdf
from drawing_extractor.text import BITMAP, Features, _readable, block_features, distance, group_glyphs, reading_axis

HERE = Path(__file__).resolve().parent
OUT = HERE / "glyphs"
TEMPLATES = HERE.parent / "src" / "drawing_extractor" / "glyph_templates.json"
_CLUSTER_DIST = 0.03  # „3“ und „8“ unterscheiden sich nur um ~0,03
_DEDUP_DIST = 0.03


def _to_json(f: Features) -> dict:
    return {
        "bitmap": "".join(f"{round(v * 15):x}" for v in f.bitmap),
        "aspect": f.aspect,
        "rel_height": f.rel_height,
        "rel_bottom": f.rel_bottom,
    }


def _from_json(d: dict) -> Features:
    return Features(tuple(int(c, 16) / 15 for c in d["bitmap"]), d["aspect"], d["rel_height"], d["rel_bottom"])


def dump(pdfs: list[Path]) -> None:
    items: list[tuple[str, Features]] = []
    for pdf in pdfs:
        strokes, glyphs, _, _ = read_pdf(pdf)
        classify(strokes)
        for b, members in enumerate(group_glyphs(glyphs)):
            axis = reading_axis(members, strokes)
            phi = axis if _readable(axis) else axis + 180.0
            feats, _ = block_features(members, phi)
            items += [(f"{pdf.stem}#{b}#{k}", f) for k, (f, _, _) in enumerate(feats)]

    clusters: list[list[tuple[str, Features]]] = []
    for ref, f in items:
        for c in clusters:
            if distance(f, c[0][1]) < _CLUSTER_DIST:
                c.append((ref, f))
                break
        else:
            clusters.append([(ref, f)])
    clusters.sort(key=len, reverse=True)

    OUT.mkdir(exist_ok=True)
    data = {str(i): [{"ref": r, **_to_json(f)} for r, f in c] for i, c in enumerate(clusters)}
    (OUT / "clusters.json").write_text(json.dumps(data, indent=0), encoding="utf-8")

    # Kontaktbögen: eine Zeile je Gruppe mit allen Mitgliedern, damit Mischgruppen auffallen
    cell, per_row, rows_per_sheet = 30, 24, 45
    for old in OUT.glob("clusters*.png"):
        old.unlink()
    for n in range(0, len(clusters), rows_per_sheet):
        chunk = clusters[n:n + rows_per_sheet]
        sheet = Image.new("RGB", (60 + per_row * cell, len(chunk) * cell), "white")
        draw = ImageDraw.Draw(sheet)
        for r, c in enumerate(chunk):
            y = r * cell
            draw.text((4, y + 8), str(n + r), fill=(200, 0, 0), font_size=14)
            for k, (_, f) in enumerate(c[:per_row]):
                img = Image.new("L", (BITMAP, BITMAP))
                img.putdata([255 - int(v * 255) for v in f.bitmap])
                sheet.paste(img.resize((26, 26), Image.Resampling.NEAREST), (60 + k * cell, y + 2))
            draw.line([(0, y + cell - 1), (sheet.width, y + cell - 1)], fill=(225, 225, 225))
        sheet.save(OUT / f"clusters_{n // rows_per_sheet + 1}.png")
    print(f"{len(items)} Zeichen in {len(clusters)} Gruppen → {OUT}")


def build() -> None:
    clusters = json.loads((OUT / "clusters.json").read_text(encoding="utf-8"))
    labels = json.loads((OUT / "labels.json").read_text(encoding="utf-8"))
    missing = sorted(set(clusters) - set(labels), key=int)
    if missing:
        sys.exit(f"Ohne Label: Gruppen {', '.join(missing)}")
    templates: list[tuple[str, Features]] = []
    for cid, members in clusters.items():
        char = labels[cid]
        if not char:
            continue
        for m in members:
            f = _from_json(m)
            if not any(c == char and distance(f, t) < _DEDUP_DIST for c, t in templates):
                templates.append((char, f))
    TEMPLATES.write_text(
        json.dumps({"bitmap_size": BITMAP, "templates": [{"char": c, **_to_json(f)} for c, f in templates]},
                   ensure_ascii=False, indent=0),
        encoding="utf-8",
    )
    print(f"{len(templates)} Vorlagen für {len({c for c, _ in templates})} Zeichen → {TEMPLATES}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dump")
    d.add_argument("pdfs", nargs="+", type=Path)
    sub.add_parser("build")
    args = ap.parse_args()
    dump(args.pdfs) if args.cmd == "dump" else build()


if __name__ == "__main__":
    main()
