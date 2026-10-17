// Das Blatt als SVG in Blatt-mm: blasses Seitenbild, darüber die klassifizierten Striche, Texte und Ansichten.
// Zoom per Rad, Verschieben per Ziehen, Doppelklick = ganzes Blatt. Ein Prüf-Flag als `focus` zoomt auf seine Stelle.
import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import type { Box, ExtractResult, ReviewFlag, StrokeKind } from "../lib/api";
import { boxToViewBox, strokePath } from "../lib/geometry";
import { KINDS, OFF_BY_DEFAULT } from "../lib/kinds";

interface Props {
  result: ExtractResult;
  focus: ReviewFlag | null;
  fitKey: number; // jede Änderung = zurück aufs ganze Blatt
  dropProps: object;
}

export function SheetViewer({ result, focus, fitKey, dropProps }: Props) {
  const d = result.drawing;
  const [w, h] = d.sheet_size_mm;
  const sheetBox: Box = useMemo(() => boxToViewBox([0, 0, w, h], 4), [w, h]);
  const [viewBox, setViewBox] = useState<Box>(sheetBox);
  const [off, setOff] = useState(() => new Set(OFF_BY_DEFAULT));
  const svgRef = useRef<SVGSVGElement>(null);
  const vbRef = useRef(viewBox);
  vbRef.current = viewBox;

  const byKind = useMemo(() => {
    const paths = new Map<StrokeKind, string[]>();
    for (const s of d.strokes) {
      if (!paths.has(s.kind)) paths.set(s.kind, []);
      paths.get(s.kind)!.push(strokePath(s));
    }
    return paths;
  }, [d.strokes]);

  const focusPath = useMemo(() => {
    if (!focus?.stroke_ids.length) return "";
    const wanted = new Set(focus.stroke_ids);
    return d.strokes.filter((s) => wanted.has(s.id)).map(strokePath).join("");
  }, [focus, d.strokes]);

  useEffect(() => {
    if (focus?.bbox) {
      const [x0, y0, x1, y1] = focus.bbox;
      // Mindestens 30 mm Umgebung, damit man die Stelle in der Zeichnung wiederfindet
      setViewBox(boxToViewBox(focus.bbox, Math.max(30, (x1 - x0) * 0.6, (y1 - y0) * 0.6)));
    } else {
      setViewBox(sheetBox);
    }
  }, [focus, fitKey, sheetBox]);

  // Bildschirm → Blatt-mm bei preserveAspectRatio "xMidYMid meet": gemeinsamer Maßstab, Rest zentriert
  function toSheet(clientX: number, clientY: number): [number, number, number] {
    const r = svgRef.current!.getBoundingClientRect();
    const vb = vbRef.current;
    const scale = Math.min(r.width / vb[2], r.height / vb[3]);
    const ox = (r.width - vb[2] * scale) / 2;
    const oy = (r.height - vb[3] * scale) / 2;
    return [vb[0] + (clientX - r.left - ox) / scale, vb[1] + (clientY - r.top - oy) / scale, scale];
  }

  // Rad-Listener nativ, weil React wheel-Events passiv anhängt und preventDefault dort nicht greift
  useEffect(() => {
    const svg = svgRef.current!;
    const onWheel = (evt: WheelEvent) => {
      evt.preventDefault();
      const [mx, my] = toSheet(evt.clientX, evt.clientY);
      const f = Math.exp(evt.deltaY * 0.0015);
      const [x, y, vw, vh] = vbRef.current;
      setViewBox([mx - (mx - x) * f, my - (my - y) * f, vw * f, vh * f]);
    };
    svg.addEventListener("wheel", onWheel, { passive: false });
    return () => svg.removeEventListener("wheel", onWheel);
  }, []);

  const drag = useRef<{ x: number; y: number; vb: Box; scale: number } | null>(null);
  const [panning, setPanning] = useState(false);
  const onPointerDown = (evt: ReactPointerEvent<SVGSVGElement>) => {
    drag.current = { x: evt.clientX, y: evt.clientY, vb: vbRef.current, scale: toSheet(evt.clientX, evt.clientY)[2] };
    evt.currentTarget.setPointerCapture(evt.pointerId);
    setPanning(true);
  };
  const onPointerMove = (evt: ReactPointerEvent<SVGSVGElement>) => {
    const g = drag.current;
    if (!g) return;
    setViewBox([g.vb[0] - (evt.clientX - g.x) / g.scale, g.vb[1] - (evt.clientY - g.y) / g.scale, g.vb[2], g.vb[3]]);
  };
  const endDrag = () => { drag.current = null; setPanning(false); };

  const toggle = (kind: StrokeKind) => setOff((prev) => {
    const next = new Set(prev);
    if (!next.delete(kind)) next.add(kind);
    return next;
  });

  return (
    <>
      <div className="kinds" aria-label="Strichklassen">
        {KINDS.filter(([kind]) => byKind.has(kind)).map(([kind, label, color]) => (
          <button key={kind} type="button" className="chip" aria-pressed={!off.has(kind)} title={label} onClick={() => toggle(kind)}>
            <i style={{ background: color }} /><span>{label}</span><b>{byKind.get(kind)!.length}</b>
          </button>
        ))}
      </div>
      <div className="viewer" {...dropProps}>
        <svg
          ref={svgRef} xmlns="http://www.w3.org/2000/svg" viewBox={viewBox.join(" ")} className={panning ? "panning" : undefined}
          onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={endDrag} onPointerCancel={endDrag}
          onDoubleClick={() => setViewBox(sheetBox)}
        >
          <rect className="paper" x={0} y={0} width={w} height={h} />
          <image className="page" href={result.page_png} x={0} y={0} width={w} height={h} />
          <g className="overlay">
            {KINDS.filter(([kind]) => byKind.has(kind)).map(([kind, , color]) => (
              <g key={kind} className={`k k-${kind}`} style={{ display: off.has(kind) ? "none" : undefined }}>
                <path d={byKind.get(kind)!.join("")} stroke={color} />
              </g>
            ))}
            <g>
              {d.text_blocks.map((t) => (
                <rect key={t.id} className="text-box" x={t.bbox[0]} y={t.bbox[1]} width={t.bbox[2] - t.bbox[0]} height={t.bbox[3] - t.bbox[1]}>
                  <title>{t.text}</title>
                </rect>
              ))}
            </g>
            {d.views.map((v) => (
              <g key={v.id}>
                <rect className="view-box" x={v.bbox[0]} y={v.bbox[1]} width={v.bbox[2] - v.bbox[0]} height={v.bbox[3] - v.bbox[1]} />
                <text className="view-label" x={v.bbox[0] + 1} y={v.bbox[1] - 1.5}>{v.is_iso ? `${v.id} · 3D` : String(v.id)}</text>
              </g>
            ))}
          </g>
          {focus?.bbox && (
            <g>
              <rect className="focus" x={focus.bbox[0] - 1} y={focus.bbox[1] - 1} width={focus.bbox[2] - focus.bbox[0] + 2} height={focus.bbox[3] - focus.bbox[1] + 2} />
              {focusPath && <path className="focus-strokes" d={focusPath} />}
            </g>
          )}
        </svg>
      </div>
    </>
  );
}
