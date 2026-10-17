"""Kommandozeile: `drawing-extract <pdf>… -o <ordner>` schreibt pro Zeichnung JSON und Overlay-PNG."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import extract
from .export import to_dict
from .render import render_overlay


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="drawing-extract", description=__doc__)
    ap.add_argument("pdfs", nargs="+", type=Path, help="Zeichnungs-PDF(s)")
    ap.add_argument("-o", "--out", type=Path, default=Path("out"), help="Ausgabeordner (Standard: out)")
    ap.add_argument("--no-overlay", action="store_true", help="kein Overlay-PNG erzeugen")
    args = ap.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    for pdf in args.pdfs:
        drawing = extract(pdf)
        stem = pdf.stem.removesuffix("_dwg")
        data = to_dict(drawing)
        (args.out / f"{stem}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        if not args.no_overlay:
            render_overlay(drawing, pdf, args.out / f"{stem}_overlay.png")
        s = data["summary"]
        print(f"{stem}: {s['views']} Ansichten, {s['strokes']} Striche {s['by_kind']}, {s['text_blocks']} Textblöcke")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
