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

// "geschätzt" is the answer of a reviewer in step 3; "Annahme" is a value that the user sets here.
type Origin = "gemessen" | "berechnet" | "geschätzt" | "Annahme";
const ORIGIN: Record<Origin, string> = {
  gemessen: "bg-good-bg text-good", berechnet: "bg-info-bg text-info", geschätzt: "bg-run-bg text-run",
  Annahme: "border border-warn-line bg-warn-bg text-bad",
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
    () => toast.success("CSV kopiert"),
    () => { csvRef.current?.select(); toast.info("CSV markiert", { description: "Mit Cmd+C bzw. Strg+C kopieren." }); },
  );
  const number = (value: string, fallback: number) => (Number.isFinite(Number(value)) && Number(value) > 0 ? Number(value) : fallback);
  const manualOrigin: Origin = human.manualHours !== null ? "geschätzt" : "Annahme";

  const figures: [string, string, Origin][] = [
    ["3D-Modelle", fmt(built.models), "gemessen"],
    ["Maße aus Zeichnung", built.parameters ? pct(built.fromDrawing / built.parameters) : "–", "berechnet"],
    ["Maschinenzeit je Teil (Median)", built.medianSeconds === null ? "–" : duration(built.medianSeconds), "gemessen"],
    ["Prüfzeit je Teil (Median)", human.reviewSeconds === null ? "–" : `${duration(human.reviewSeconds)} aus ${fmt(human.reviews)} Prüfung${human.reviews === 1 ? "" : "en"}`, "gemessen"],
    ["Nachbau von Hand je Teil", human.manualHours !== null
      ? `${hours(human.manualHours)} aus ${fmt(human.estimates)} Schätzung${human.estimates === 1 ? "" : "en"} (${human.estimators.map((e) => ESTIMATOR_LABEL[e]).join(", ")})`
      : hours(assumptions.manualHours), manualOrigin],
    ["Stundensatz Konstruktion", euros(assumptions.hourlyRate), "Annahme"],
  ];

  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button variant="outline" size="xs" className="rounded-full normal-case tracking-normal"><Presentation />Kennzahlen</Button>
      </DialogTrigger>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Kennzahlen für den Pitch</DialogTitle>
          <DialogDescription>
            Alle Werte stammen aus den Läufen und Prüfungen in dieser App. Annahmen sind markiert.
            {built.simulated && <strong className="text-bad"> Die Läufe sind simuliert: keine Zahlen für den Pitch.</strong>}
          </DialogDescription>
        </DialogHeader>

        {result ? (
          <p className="text-lg leading-snug font-semibold text-balance text-card-foreground">
            {fmt(built.models)} Altzeichnung{built.models === 1 ? "" : "en"}: {duration(built.medianSeconds!)} Maschine plus {duration(human.reviewSeconds!)} Prüfung
            statt {hours(result.manualHours)} Nachbau von Hand. Das ist <span className="text-run">{fmt(Math.round(result.factor))}-mal schneller</span>
            {built.parameters > 0 && <>, und {pct(built.fromDrawing / built.parameters)} der Maße kommen direkt aus der Zeichnung</>}.
          </p>
        ) : (
          <p className="rounded-md bg-surface px-3 py-2 text-sm text-muted-foreground">
            Für den Vergleich fehlt noch {built.medianSeconds === null ? "ein erfolgreicher CAD-Lauf" : "eine gemessene Prüfung (Schritt 3 „Prüfen“)"}.
          </p>
        )}

        {result && (
          <section aria-label="Zeit je Teil" className="grid gap-1.5 text-xs">
            <Bar label="Von Hand" value={hours(result.manualHours)} parts={[[1, "bg-faint"]]} />
            <Bar label="Mit drawing2cad" value={duration(result.toolSeconds)}
              parts={[[built.medianSeconds! / (result.manualHours * 3600), "bg-run"], [human.reviewSeconds! / (result.manualHours * 3600), "bg-highlight"]]} />
            <p className="flex gap-3 text-muted-foreground">
              <span className="flex items-center gap-1"><i className="size-2.5 rounded-sm bg-run" />Maschine</span>
              <span className="flex items-center gap-1"><i className="size-2.5 rounded-sm bg-highlight" />Prüfung durch Mensch</span>
              <span className="ml-auto font-semibold text-good">
                Gespart: {hours(result.hours)} ≈ {euros(result.euros)}
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
          <legend className="sr-only">Annahmen</legend>
          <div className="grid gap-1">
            <Label htmlFor={rateId} className="text-xs">Stundensatz (€)</Label>
            <Input id={rateId} type="number" min={1} step={5} className="h-8 w-24 bg-card" defaultValue={assumptions.hourlyRate}
              onChange={(e) => onAssumptions({ ...assumptions, hourlyRate: number(e.target.value, assumptions.hourlyRate) })} />
          </div>
          <div className="grid gap-1">
            <Label htmlFor={manualId} className="text-xs">Nachbau von Hand (h)</Label>
            <Input id={manualId} type="number" min={0.25} step={0.25} className="h-8 w-24 bg-card" defaultValue={assumptions.manualHours}
              disabled={human.manualHours !== null}
              onChange={(e) => onAssumptions({ ...assumptions, manualHours: number(e.target.value, assumptions.manualHours) })} />
          </div>
          <p className="min-w-48 flex-1 text-xs text-muted-foreground">
            {human.manualHours !== null
              ? "Der Nachbau von Hand kommt aus den Schätzungen bei der Prüfung; das Feld gilt nur ohne Schätzung."
              : "Ohne Schätzung aus der Prüfung gilt dieser Wert. Am besten BCT-Konstrukteure in Schritt 3 schätzen lassen."}
          </p>
        </fieldset>

        <section aria-label="Messungen als CSV" className="grid gap-1.5">
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-semibold tracking-[.06em] text-faint uppercase">Messungen ({fmt(human.reviews)})</h3>
            <Button size="xs" variant="outline" onClick={() => void copy()} disabled={!human.reviews}><ClipboardCopy />CSV kopieren</Button>
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
