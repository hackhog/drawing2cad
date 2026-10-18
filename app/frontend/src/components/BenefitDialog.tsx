// Key figures for the pitch: one sentence, a time comparison, the assumptions, and all measurements as CSV.
// Each figure states its origin, so that measured values and assumptions stay apart.
import { ClipboardCopy, Presentation } from "lucide-react";
import { useId, useRef } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { Assumptions, Benefit, Effort, Saving } from "@/lib/benefit";
import { ESTIMATOR_LABEL } from "@/lib/estimators";
import { duration, euros, fmt, hours, pct } from "@/lib/format";
import { cn } from "@/lib/utils";

// "estimated" is the answer of a reviewer in step 3; "assumption" is a value that the user sets here.
type Origin = "measured" | "calculated" | "estimated" | "assumption";
const ORIGIN: Record<Origin, string> = {
  measured: "bg-good-bg text-good", calculated: "bg-info-bg text-info", estimated: "bg-run-bg text-run",
  assumption: "border border-warn-line bg-warn-bg text-bad",
};

const OriginBadge = ({ origin }: { origin: Origin }) =>
  <span className={cn("rounded-full px-1.5 py-px text-[10px] font-bold tracking-[.05em] uppercase", ORIGIN[origin])}>{origin}</span>;

interface Props {
  built: Benefit;
  human: Effort;
  result: Saving | null;
  assumptions: Assumptions;
  onAssumptions: (next: Assumptions) => void;
  csv: string;
}

export function BenefitDialog({ built, human, result, assumptions, onAssumptions, csv }: Props) {
  const csvRef = useRef<HTMLTextAreaElement>(null);
  const rateId = useId();
  const manualId = useId();
  const copy = () => navigator.clipboard.writeText(csv).then(
    () => toast.success("CSV copied"),
    () => { csvRef.current?.select(); toast.info("CSV selected", { description: "Copy with Cmd+C or Ctrl+C." }); },
  );
  const number = (value: string, fallback: number) => (Number.isFinite(Number(value)) && Number(value) > 0 ? Number(value) : fallback);
  const manualOrigin: Origin = human.manualHours !== null ? "estimated" : "assumption";

  const figures: [string, string, Origin][] = [
    ["3D models", fmt(built.models), "measured"],
    ["Dimensions from drawing", built.parameters ? pct(built.fromDrawing / built.parameters) : "–", "calculated"],
    ["Machine time per part (median)", built.medianSeconds === null ? "–" : duration(built.medianSeconds), "measured"],
    ["Review time per part (median)", human.reviewSeconds === null ? "–" : `${duration(human.reviewSeconds)} from ${fmt(human.reviews)} review${human.reviews === 1 ? "" : "s"}`, "measured"],
    ["Manual rebuild per part", human.manualHours !== null
      ? `${hours(human.manualHours)} from ${fmt(human.estimates)} estimate${human.estimates === 1 ? "" : "s"} (${human.estimators.map((e) => ESTIMATOR_LABEL[e]).join(", ")})`
      : hours(assumptions.manualHours), manualOrigin],
    ["Design hourly rate", euros(assumptions.hourlyRate), "assumption"],
  ];

  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button variant="outline" size="xs" className="rounded-full normal-case tracking-normal"><Presentation />Key figures</Button>
      </DialogTrigger>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Key figures for the pitch</DialogTitle>
          <DialogDescription>
            All values come from the runs and reviews in this app. Assumptions are marked.
            {built.simulated && <strong className="text-bad"> The runs are simulated: no figures for the pitch.</strong>}
          </DialogDescription>
        </DialogHeader>

        {result ? (
          <p className="text-lg leading-snug font-semibold text-balance text-card-foreground">
            {fmt(built.models)} legacy drawing{built.models === 1 ? "" : "s"}: {duration(built.medianSeconds!)} machine plus {duration(human.reviewSeconds!)} review
            instead of {hours(result.manualHours)} manual rebuild. That is <span className="text-run">{fmt(Math.round(result.factor))} times faster</span>
            {built.parameters > 0 && <>, and {pct(built.fromDrawing / built.parameters)} of the dimensions come straight from the drawing</>}.
          </p>
        ) : (
          <p className="rounded-md bg-surface px-3 py-2 text-sm text-muted-foreground">
            The comparison still needs {built.medianSeconds === null ? "a successful CAD run" : "a measured review (step 3 “Review”)"}.
          </p>
        )}

        {result && (
          <section aria-label="Time per part" className="grid gap-1.5 text-xs">
            <Bar label="By hand" value={hours(result.manualHours)} parts={[[1, "bg-faint"]]} />
            <Bar label="With drawing2cad" value={duration(result.toolSeconds)}
              parts={[[built.medianSeconds! / (result.manualHours * 3600), "bg-run"], [human.reviewSeconds! / (result.manualHours * 3600), "bg-highlight"]]} />
            <p className="flex gap-3 text-muted-foreground">
              <span className="flex items-center gap-1"><i className="size-2.5 rounded-sm bg-run" />Machine</span>
              <span className="flex items-center gap-1"><i className="size-2.5 rounded-sm bg-highlight" />Human review</span>
              <span className="ml-auto font-semibold text-good">
                Saved: {hours(result.hours)} ≈ {euros(result.euros)}
              </span>
            </p>
          </section>
        )}

        <table className="w-full text-xs">
          <tbody>
            {figures.map(([label, value, origin]) => (
              <tr key={label} className="border-b last:border-b-0">
                <td className="py-1.5 text-muted-foreground">{label}</td>
                <td className="py-1.5 text-right font-semibold text-card-foreground tabular-nums">{value}</td>
                <td className="w-24 py-1.5 text-right"><OriginBadge origin={origin} /></td>
              </tr>
            ))}
          </tbody>
        </table>

        <fieldset className="flex flex-wrap items-end gap-3 rounded-md border border-warn-line bg-warn-bg px-3 py-2">
          <legend className="sr-only">Assumptions</legend>
          <div className="grid gap-1">
            <Label htmlFor={rateId} className="text-xs">Hourly rate (€)</Label>
            <Input id={rateId} type="number" min={1} step={5} className="h-8 w-24 bg-card" defaultValue={assumptions.hourlyRate}
              onChange={(e) => onAssumptions({ ...assumptions, hourlyRate: number(e.target.value, assumptions.hourlyRate) })} />
          </div>
          <div className="grid gap-1">
            <Label htmlFor={manualId} className="text-xs">Manual rebuild (h)</Label>
            <Input id={manualId} type="number" min={0.25} step={0.25} className="h-8 w-24 bg-card" defaultValue={assumptions.manualHours}
              disabled={human.manualHours !== null}
              onChange={(e) => onAssumptions({ ...assumptions, manualHours: number(e.target.value, assumptions.manualHours) })} />
          </div>
          <p className="min-w-48 flex-1 text-xs text-muted-foreground">
            {human.manualHours !== null
              ? "The manual rebuild time comes from the estimates given during review; this field applies only without an estimate."
              : "Without an estimate from review, this value applies. Ideally, let BCT designers estimate in step 3."}
          </p>
        </fieldset>

        <section aria-label="Measurements as CSV" className="grid gap-1.5">
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-semibold tracking-[.06em] text-faint uppercase">Measurements ({fmt(human.reviews)})</h3>
            <Button size="xs" variant="outline" onClick={() => void copy()} disabled={!human.reviews}><ClipboardCopy />Copy CSV</Button>
          </div>
          <textarea ref={csvRef} readOnly value={csv} aria-label="CSV" rows={Math.min(8, human.reviews + 1)}
            className="w-full resize-none rounded-md border bg-surface px-2.5 py-2 font-mono text-[11px] text-card-foreground" />
        </section>
      </DialogContent>
    </Dialog>
  );
}

function Bar({ label, value, parts }: { label: string; value: string; parts: [number, string][] }) {
  return (
    <div className="grid grid-cols-[110px_1fr_90px] items-center gap-2.5">
      <span className="text-muted-foreground">{label}</span>
      <span className="flex h-3.5 overflow-hidden rounded bg-surface">
        {/* A very short machine or review time still shows as a sliver. */}
        {parts.map(([share, color]) => <i key={color} className={cn("h-full min-w-[3px]", color)} style={{ width: `${Math.min(1, share) * 100}%` }} />)}
      </span>
      <span className="text-right font-semibold text-card-foreground tabular-nums">{value}</span>
    </div>
  );
}
