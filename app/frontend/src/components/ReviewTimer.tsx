// Stopwatch of step 3: measures how long a person reviews the drawing, then asks once for the manual effort.
// The overview compares both values with the machine time of the CAD run.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, RotateCcw, Timer } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useApi } from "@/lib/apiContext";
import type { Estimator, Measurement } from "@/lib/contract";
import { recoveryFor } from "@/lib/errors";
import { ESTIMATOR_LABEL, MANUAL_ESTIMATES } from "@/lib/estimators";
import { clock, duration, hours } from "@/lib/format";
import { keys, measurementsQuery } from "@/lib/queries";
import { cn } from "@/lib/utils";

const CHIP = "rounded-full border border-input bg-card px-2.5 py-1 text-xs font-semibold text-card-foreground hover:bg-accent aria-pressed:border-primary aria-pressed:bg-primary aria-pressed:text-primary-foreground disabled:opacity-50";

export function ReviewTimer({ sourceId }: { sourceId: string }) {
  const api = useApi();
  const queryClient = useQueryClient();
  const { data: measurements = [] } = useQuery(measurementsQuery(api));
  const [startedAt, setStartedAt] = useState(Date.now);
  const [stoppedAt, setStoppedAt] = useState<number | null>(null);
  const [now, setNow] = useState(Date.now);
  const [estimator, setEstimator] = useState<Estimator | null>(null);
  const [saved, setSaved] = useState<Measurement | null>(null);

  useEffect(() => {
    if (stoppedAt !== null) return;
    const tick = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(tick);
  }, [stoppedAt]);

  const seconds = ((stoppedAt ?? now) - startedAt) / 1000;
  const save = useMutation({
    // The service rejects 0 s; a review shorter than one second counts as one second.
    mutationFn: (manualHours: number | null) =>
      api.addMeasurement(sourceId, { review_seconds: Math.max(1, Math.round(seconds)), manual_hours: manualHours, estimator }),
    onSuccess: async (measurement) => {
      setSaved(measurement);
      await queryClient.invalidateQueries({ queryKey: keys.measurements });
    },
    onError: (err) => toast.error("Review time not saved", { description: `${err.message} ${recoveryFor(err)}` }),
  });
  const restart = () => {
    setStartedAt(Date.now());
    setNow(Date.now());
    setStoppedAt(null);
    setSaved(null);
  };
  const earlier = measurements.filter((m) => m.source_id === sourceId).length;

  return (
    <Card className="gap-2 rounded-xl border-run/30 px-3.5 pt-3 pb-3.5 shadow-none">
      <CardHeader className="flex flex-row items-center justify-between px-0">
        <CardTitle className="flex items-center gap-1.5 text-sm font-bold"><Timer className="size-4 text-run" />Review time</CardTitle>
        <span className="text-[11px] text-muted-foreground">{earlier ? `${earlier} earlier measurement${earlier === 1 ? "" : "s"}` : "measured"}</span>
      </CardHeader>
      <CardContent className="flex flex-col gap-2.5 px-0">
        <div className="flex items-center gap-3">
          <span role="timer" aria-label="Review time" className={cn("font-mono text-[22px] font-semibold tabular-nums", stoppedAt === null ? "text-run" : "text-card-foreground")}>
            {clock(seconds)}
          </span>
          {stoppedAt === null ? (
            <Button size="sm" className="ml-auto rounded-full" onClick={() => setStoppedAt(Date.now())}><Check />Review done</Button>
          ) : (
            <Button variant="ghost" size="sm" className="ml-auto rounded-full" onClick={restart}><RotateCcw />Measure again</Button>
          )}
        </div>

        {stoppedAt === null && <p className="text-xs text-muted-foreground">Running since “Review” was opened. Look at the flagged spots, then finish.</p>}

        {stoppedAt !== null && !saved && (
          <div className="flex flex-col gap-2 border-t pt-2.5">
            <p className="text-xs font-semibold text-card-foreground">Who reviewed?</p>
            <div role="group" aria-label="Who reviewed" className="flex flex-wrap gap-1.5">
              {(Object.entries(ESTIMATOR_LABEL) as [Estimator, string][]).map(([value, label]) => (
                <button key={value} type="button" aria-pressed={estimator === value} className={CHIP} onClick={() => setEstimator(value)}>{label}</button>
              ))}
            </div>
            <p className="text-xs font-semibold text-card-foreground">How long would rebuilding this part by hand have taken?</p>
            <div role="group" aria-label="Manual effort" className="flex flex-wrap gap-1.5">
              {MANUAL_ESTIMATES.map(([value, label]) => (
                <button key={value} type="button" className={CHIP} disabled={save.isPending} onClick={() => save.mutate(value)}>{label}</button>
              ))}
            </div>
            <button type="button" className="self-start text-xs text-muted-foreground underline" disabled={save.isPending} onClick={() => save.mutate(null)}>
              Save review time only
            </button>
          </div>
        )}

        {saved && (
          <p className="rounded-md bg-good-bg px-2.5 py-1.5 text-xs font-semibold text-good" role="status">
            Saved: {duration(saved.review_seconds)} review
            {saved.manual_hours !== null && `, by hand ${hours(saved.manual_hours)}`}
            {saved.estimator && ` (${ESTIMATOR_LABEL[saved.estimator]})`}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
