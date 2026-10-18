// The sheet as SVG in sheet mm: a faded page image, with the classified strokes, texts, and views on top.
// Wheel zooms, dragging pans, double-click shows the whole sheet. A review flag as `focus` zooms to its spot.
import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import type { Box, ExtractResult, ReviewFlag, StrokeKind } from "@/lib/drawing";
import { boxToViewBox, strokePath } from "@/lib/geometry";
import { KINDS, OFF_BY_DEFAULT } from "@/lib/kinds";
import { cn } from "@/lib/utils";
import { VIEWER_FRAME } from "./viewerFrame";

interface Props {
  result: ExtractResult;
  focus: ReviewFlag | null;
  fitKey: number; // each change = back to the whole sheet
  step: 1 | 2 | 3; // 1 = original sheet, 2 = stroke classes, 3 = review
  dropProps: object; // PDFs dropped onto the sheet start an upload
}

export function SheetViewer({ result, focus, fitKey, step, dropProps }: Props) {
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
      // At least 30 mm of surroundings, so that the spot can be found in the drawing
      setViewBox(boxToViewBox(focus.bbox, Math.max(30, (x1 - x0) * 0.6, (y1 - y0) * 0.6)));
    } else {
      setViewBox(sheetBox);
    }
  }, [focus, fitKey, sheetBox]);

  // Screen → sheet mm with preserveAspectRatio "xMidYMid meet": common scale, remainder centered
  function toSheet(clientX: number, clientY: number): [number, number, number] {
    const r = svgRef.current!.getBoundingClientRect();
    const vb = vbRef.current;
    const scale = Math.min(r.width / vb[2], r.height / vb[3]);
    const ox = (r.width - vb[2] * scale) / 2;
    const oy = (r.height - vb[3] * scale) / 2;
    return [vb[0] + (clientX - r.left - ox) / scale, vb[1] + (clientY - r.top - oy) / scale, scale];
  }

  // Native wheel listener, because React attaches wheel events as passive and preventDefault has no effect there
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
      {step === 2 && (
        <div className="mb-2.5 flex flex-wrap gap-1.5" aria-label="Stroke classes">
          {KINDS.filter(([kind]) => byKind.has(kind)).map(([kind, label, color]) => (
            <button key={kind} type="button" aria-pressed={!off.has(kind)} title={label} onClick={() => toggle(kind)}
              className="inline-flex items-center gap-1.5 rounded-full border bg-card px-2.5 py-0.5 text-xs font-medium aria-[pressed=false]:opacity-45">
              <i className="size-2 rounded-full" style={{ background: color }} /><span>{label}</span>
              <b className="font-medium text-muted-foreground">{byKind.get(kind)!.length}</b>
            </button>
          ))}
        </div>
      )}
      <div data-step={step} className={cn("sheet", VIEWER_FRAME)} {...dropProps}>
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
