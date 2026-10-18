import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useApi } from "@/lib/apiContext";
import { saveBlob } from "@/lib/download";
import type { FlagChange, ReviewFlag, StrokeClass } from "@/lib/drawing";
import { recoveryFor } from "@/lib/errors";
import { decisionLabel, FLAG_KIND, STROKE_CLASSES } from "@/lib/kinds";
import { keys } from "@/lib/queries";
import { cn } from "@/lib/utils";

interface Props {
  flags: ReviewFlag[]; active: ReviewFlag | null; highlight: boolean; onSelect: (flag: ReviewFlag) => void;
  /** Set when the service stores decisions: the user can then decide the active flag and export the feedback. */
  sourceId?: string;
}

/** Review list in the style of a change list: a click zooms the sheet to the location. */
export function FlagList({ flags, active, highlight, onSelect, sourceId }: Props) {
  const api = useApi();
  const open = flags.filter((f) => !f.decision).length;
  const feedback = useMutation({
    mutationFn: async () => saveBlob(await api.exportFeedback(), `drawing2cad-feedback-${new Date().toISOString().slice(0, 10)}.json`),
    onError: (err) => toast.error(`${err.message} ${recoveryFor(err)}`),
  });
  return (
    <Card className={cn("min-h-0 gap-2.5 rounded-xl px-3.5 pt-3 pb-3.5 shadow-none transition-shadow", highlight && "border-warn-line ring-3 ring-warn-bg")}>
      <CardHeader className="flex flex-row items-center justify-between px-0">
        <CardTitle className="text-sm font-bold">
          Review
          {open > 0 && <span className="ml-1 rounded-full border border-warn-line bg-warn-bg px-1.5 py-px text-[11px] text-bad">{open}</span>}
          {flags.length > open && <span className="ml-1.5 text-[11px] font-normal text-muted-foreground">{flags.length - open} decided</span>}
        </CardTitle>
        {sourceId
          ? <Button variant="outline" size="sm" className="h-6 rounded-full px-2.5 text-[11px]" disabled={feedback.isPending}
              title="All decisions as feedback for the developers of the drawing analysis" onClick={() => feedback.mutate()}>
              <Download />Feedback
            </Button>
          : <span className="rounded-full bg-info-bg px-2.5 py-0.5 text-[11px] font-semibold text-info">Liste</span>}
      </CardHeader>
      <CardContent className="overflow-y-auto px-0">
        <ul>
          {!flags.length && <li className="px-1.5 py-2 text-muted-foreground">Nothing to review.</li>}
          {flags.map((f) => f.bbox ? (
            <li key={f.id} className="border-b last:border-b-0">
              <button type="button" onClick={() => onSelect(f)} aria-pressed={f.id === active?.id}
                className={cn("flex w-full items-start gap-2.5 rounded-md px-1.5 py-2 text-left hover:bg-accent aria-pressed:bg-[#fff1f0]", f.decision && "opacity-60")}>
                <i className={cn("mt-[5px] size-[7px] flex-none rounded-full", f.decision ? "bg-good" : f.kind === "unreadable_text" ? "bg-run" : "bg-highlight")} />
                <span className="flex min-w-0 flex-1 flex-col">
                  <strong className="truncate font-semibold text-card-foreground">{f.message}</strong>
                  <span className="text-xs text-muted-foreground">{f.decision ? decisionLabel(f.decision) : FLAG_KIND[f.kind] ?? f.kind}</span>
                </span>
                <time className="text-[11.5px] whitespace-nowrap text-muted-foreground">x {Math.round(f.bbox[0])} · y {Math.round(f.bbox[1])}</time>
              </button>
              {sourceId && f.id === active?.id && <DecisionForm key={f.id + (f.decision?.decided_at ?? "")} sourceId={sourceId} flag={f} />}
            </li>
          ) : <li key={f.id} className="px-1.5 py-2 text-muted-foreground">{f.message}</li>)}
        </ul>
      </CardContent>
    </Card>
  );
}

/** The decision of the user on one flag. New agent runs apply it; the feedback export collects it for the developers. */
function DecisionForm({ sourceId, flag }: { sourceId: string; flag: ReviewFlag }) {
  const api = useApi();
  const queryClient = useQueryClient();
  const [strokeClass, setStrokeClass] = useState<StrokeClass | "">(flag.decision?.stroke_class ?? "");
  const [text, setText] = useState(flag.decision?.text ?? flag.text ?? "");
  const [note, setNote] = useState(flag.decision?.note ?? "");
  const decide = useMutation({
    mutationFn: (change: FlagChange) => api.decideFlag(sourceId, flag.id, change),
    onSuccess: (page) => queryClient.setQueryData(keys.flags(sourceId), page),
    onError: (err) => toast.error(`${err.message} ${recoveryFor(err)}`),
  });
  const withNote = (change: FlagChange): FlagChange => (note.trim() ? { ...change, note: note.trim() } : change);
  const textValid = text.trim() !== "" && !text.includes("?");

  return (
    <form className="mx-1.5 mb-2 flex flex-col gap-1.5 rounded-md border bg-surface p-2 text-xs"
      onSubmit={(e) => {
        e.preventDefault();
        if (flag.kind === "unclear_strokes" && strokeClass) decide.mutate(withNote({ action: "classify", stroke_class: strokeClass }));
        if (flag.kind === "unreadable_text" && textValid) decide.mutate(withNote({ action: "correct", text: text.trim() }));
      }}>
      {flag.kind === "unclear_strokes" && (
        <label className="flex items-center gap-2">
          <span className="w-16 text-muted-foreground">Meaning</span>
          <select aria-label="Meaning of the strokes" value={strokeClass} onChange={(e) => setStrokeClass(e.target.value as StrokeClass | "")}
            className="h-7 flex-1 rounded-md border bg-card px-1.5">
            <option value="">choose …</option>
            {STROKE_CLASSES.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
          </select>
        </label>
      )}
      {flag.kind === "unreadable_text" && (
        <label className="flex items-center gap-2">
          <span className="w-16 text-muted-foreground">Correct</span>
          <Input aria-label="Correct text" value={text} onChange={(e) => setText(e.target.value)} className="h-7 flex-1 text-xs" />
        </label>
      )}
      <Input aria-label="Note for the developers" value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000}
        placeholder="Note for the developers (optional)" className="h-7 text-xs" />
      <div className="flex flex-wrap justify-end gap-1.5">
        {flag.decision && (
          <Button type="button" variant="ghost" size="sm" className="h-7" disabled={decide.isPending}
            onClick={() => decide.mutate({ action: "reopen" })}>Undo</Button>
        )}
        <Button type="button" variant="outline" size="sm" className="h-7" disabled={decide.isPending}
          onClick={() => decide.mutate(withNote({ action: "ignore" }))}>Ignore</Button>
        {flag.kind !== "no_views" && (
          <Button type="submit" size="sm" className="h-7"
            disabled={decide.isPending || (flag.kind === "unclear_strokes" ? !strokeClass : !textValid)}>Apply</Button>
        )}
      </div>
    </form>
  );
}
