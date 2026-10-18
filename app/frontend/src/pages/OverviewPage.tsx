// Overview page: tiles for all drawings, tiles for what the CAD runs delivered and save, and one table row per source or upload (ADR 0008).
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { Gauge, Hash, Trash2, X } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { BenefitDialog } from "@/components/BenefitDialog";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/Status";
import { UploadButton } from "@/components/UploadButton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useApi } from "@/lib/apiContext";
import { useAssumptions } from "@/lib/assumptions";
import { benefit, effort, measurementsCsv, runSeconds, saving } from "@/lib/benefit";
import type { Measurement, Run, Source } from "@/lib/contract";
import type { ExtractResult, ReviewFlag } from "@/lib/drawing";
import { dropTarget } from "@/lib/drop";
import { errorCode, recoveryFor } from "@/lib/errors";
import { ESTIMATOR_LABEL } from "@/lib/estimators";
import { bytes, duration, euros, explainedShare, fmt, hours, partName, pct } from "@/lib/format";
import { analysisQuery, capabilitiesQuery, flagsQuery, keys, measurementsQuery, runsQuery, sourcesQuery } from "@/lib/queries";
import { analysisStatus, openFlags, uploadStatus } from "@/lib/status";
import { isPdf, useUploads, type Upload } from "@/lib/uploads";
import { cn } from "@/lib/utils";

type Tone = "" | "good" | "bad";
const SUB: Record<Tone, string> = { "": "text-muted-foreground", good: "font-semibold text-good", bad: "font-semibold text-bad" };

function Tile({ title, value, sub, tone = "", warn = false, extra }: {
  title: string; value: React.ReactNode; sub: string; tone?: Tone; warn?: boolean; extra?: React.ReactNode;
}) {
  return (
    <Card className={cn("gap-0 rounded-xl px-3.5 py-3 shadow-none transition-colors", warn && "border-warn-line bg-warn-bg")}>
      <header className="flex min-h-[22px] items-center justify-between">
        <h3 className="text-[11px] font-semibold tracking-[.06em] text-[#4b5360] uppercase">{title}</h3>{extra}
      </header>
      <div className="mt-1.5 mb-0.5 flex min-h-[34px] items-center gap-3">{value}</div>
      <p className={cn("text-xs", SUB[tone])}>{sub}</p>
    </Card>
  );
}

const Big = ({ children, small = false }: { children: React.ReactNode; small?: boolean }) =>
  <strong className={cn("leading-[1.1] font-bold tracking-tight text-card-foreground", small ? "text-lg" : "text-[26px]")}>{children}</strong>;

export function OverviewPage() {
  const api = useApi();
  const { uploads, addFiles } = useUploads();
  const { data: sources = [] } = useQuery(sourcesQuery(api));
  const { data: caps } = useQuery(capabilitiesQuery(api));
  const analyses = useQueries({ queries: sources.map((s) => analysisQuery(api, s.source_id)) });
  const pages = useQueries({ queries: sources.map((s) => ({ ...flagsQuery(api, s.source_id), enabled: !!caps?.flag_decisions })) });
  const runs = useQueries({ queries: sources.map((s) => runsQuery(api, s.source_id)) });
  const { data: measurements = [] } = useQuery(measurementsQuery(api));
  const [assumptions, setAssumptions] = useAssumptions();
  const [gauge, setGauge] = useState(false);
  const [over, setOver] = useState(false);
  const drop = dropTarget((files) => addFiles(files.filter(isPdf)), setOver);

  const done = analyses.flatMap((q) => (q.data ? [q.data] : []));
  const busy = uploads.filter((u) => u.state !== "error").length;
  const failed = uploads.filter((u) => u.state === "error").length;
  const shares = done.map(explainedShare);
  const total = shares.reduce((a, s) => a + s.total, 0);
  const explained = shares.reduce((a, s) => a + s.explained, 0);
  const share = total ? explained / total : 0;
  const texts = done.flatMap((r) => r.drawing.text_blocks);
  const unsure = texts.filter((t) => t.text.includes("?")).length;
  const flags = analyses.reduce((a, q, i) => a + (q.data ? openFlags(q.data, pages[i]?.data?.flags) : 0), 0);
  const empty = !sources.length && !uploads.length;
  const b = benefit(runs.map((q) => q.data ?? []));
  const built = b.models > 0;
  const human = effort(measurements);
  const saved = saving(b, human, assumptions);
  const machineBySource = new Map(sources.map((s, i) => [s.source_id, latestSeconds(runs[i]?.data)]));
  const csv = measurementsCsv(measurements, new Map(sources.map((s) => [s.source_id, { name: partName(s.filename), machineSeconds: machineBySource.get(s.source_id) ?? null }])));

  const [jobsSub, jobsTone]: [string, Tone] = busy ? [`${busy} in progress`, ""]
    : failed ? [`${failed} unreadable`, "bad"]
    : sources.length ? ["all read", "good"] : ["read and stored", ""];

  return (
    <>
      <PageHeader
        title="Overview" live={done.length > 0}
        subtitle={empty ? "No drawing uploaded yet" : `${fmt(done.length)} of ${fmt(sources.length + busy)} drawings read`}
        actions={<UploadButton label={empty ? "Upload PDFs" : "More PDFs"} />}
      />

      <section aria-label="Key figures" className="grid grid-cols-4 gap-3 max-[1000px]:grid-cols-2">
        <Tile title="Drawings" value={<Big>{empty ? "–" : fmt(done.length)}</Big>} sub={jobsSub} tone={jobsTone} />
        <Tile
          title="Explained"
          extra={
            <div role="radiogroup" aria-label="Display" className="flex gap-0.5 rounded-[7px] bg-muted p-0.5">
              {([[false, "Number", Hash], [true, "Gauge", Gauge]] as const).map(([mode, label, Icon]) => (
                <button key={label} type="button" role="radio" aria-checked={gauge === mode} title={label} onClick={() => setGauge(mode)}
                  className="grid h-[18px] w-5 place-items-center rounded-[5px] text-muted-foreground aria-checked:bg-card aria-checked:text-card-foreground aria-checked:shadow-xs">
                  <Icon className="size-3" />
                </button>
              ))}
            </div>
          }
          value={<>
            {gauge && (
              <svg viewBox="0 0 100 56" aria-hidden="true" className="h-10 w-[72px] fill-none" strokeWidth={9} strokeLinecap="round">
                <path d="M8 50a42 42 0 0 1 84 0" className="stroke-[#eef0f3]" />
                <path d="M8 50a42 42 0 0 1 84 0" pathLength={100} className="stroke-highlight transition-[stroke-dasharray] duration-500"
                  style={{ strokeDasharray: `${share * 100} 100` }} />
              </svg>
            )}
            <Big small={gauge}>{total ? pct(share) : "–"}</Big>
          </>}
          sub={total ? `${fmt(explained)} of ${fmt(total)} strokes assigned` : "Share of strokes with a certain meaning"}
        />
        <Tile
          title="Texts read" value={<Big>{done.length ? fmt(texts.length) : "–"}</Big>}
          sub={!done.length ? "Dimensions, sections, notes" : unsure ? `${unsure} not read with certainty` : "all read with certainty"}
          tone={!done.length ? "" : unsure ? "bad" : "good"}
        />
        <Tile
          title="To review" warn={flags > 0} value={<Big>{done.length ? fmt(flags) : "–"}</Big>}
          sub={!done.length ? "Flagged, not guessed" : flags === 1 ? "spot flagged, not guessed" : flags ? "spots flagged, not guessed" : "nothing open"}
          tone={!done.length ? "" : flags ? "bad" : "good"}
        />
      </section>

      <section aria-labelledby="benefit-title" className="grid gap-1.5">
        <h2 id="benefit-title" className="flex items-center gap-2 text-[11px] font-semibold tracking-[.06em] text-faint uppercase">
          Benefit{b.simulated && <Badge variant="secondary" className="bg-warn-bg text-bad normal-case tracking-normal">Simulated</Badge>}
          <span className="ml-auto">
            <BenefitDialog built={b} human={human} result={saved} assumptions={assumptions} onAssumptions={setAssumptions} csv={csv} />
          </span>
        </h2>
        <div className="grid grid-cols-3 gap-3 max-[1000px]:grid-cols-2">
          <Tile
            title="3D models" value={<Big>{built || b.active ? fmt(b.models) : "–"}</Big>}
            sub={b.active ? `${b.active} being built` : built ? `from ${fmt(done.length)} drawings read` : "STEP built from the drawing"}
          />
          <Tile
            title="Released" value={<Big>{built ? fmt(b.released) : "–"}</Big>}
            sub={!built ? "reviewed models only" : b.released ? "reviewed and deliverable" : "drafts awaiting review"}
            tone={built && b.released ? "good" : ""}
          />
          <Tile
            title="Dimensions from drawing" value={<Big>{b.parameters ? pct(b.fromDrawing / b.parameters) : "–"}</Big>}
            sub={!b.parameters ? "sourced, not retyped"
              : `${fmt(b.fromDrawing)} of ${fmt(b.parameters)} sourced${b.assumed ? `, ${fmt(b.assumed)} assumed` : ""}`}
          />
          <Tile
            title="Time per model" value={<Big>{b.medianSeconds === null ? "–" : duration(b.medianSeconds)}</Big>}
            sub={b.medianSeconds === null ? "drawing to STEP" : "median, drawing to STEP"}
          />
          <Tile
            title="Review time" value={<Big>{human.reviewSeconds === null ? "–" : duration(human.reviewSeconds)}</Big>}
            sub={human.reviewSeconds === null ? "stopwatch in step 3 “Review”"
              : `median of ${fmt(human.reviews)} review${human.reviews === 1 ? "" : "s"}`}
          />
          <Tile
            title="Saved" value={<Big>{saved ? hours(saved.hours) : "–"}</Big>}
            sub={!saved ? "by hand vs. run and review"
              : `≈ ${euros(saved.euros)}, ${saved.manualAssumed ? `assumed ${hours(saved.manualHours)} by hand` : `${hours(saved.manualHours)} by hand, estimated`}`}
            tone={saved && saved.hours > 0 ? "good" : ""}
          />
        </div>
      </section>

      <Card {...drop} className={cn("min-h-0 flex-1 gap-2.5 rounded-xl px-3.5 pt-3 pb-3.5 shadow-none", over && "ring-4 ring-primary/10")}>
        <CardHeader className="flex flex-row items-center justify-between px-0">
          <CardTitle className="text-sm font-bold">Drawings</CardTitle>
          <span className="rounded-full bg-info-bg px-2.5 py-0.5 text-[11px] font-semibold text-info">Table</span>
        </CardHeader>
        <CardContent className="flex min-h-0 flex-1 flex-col px-0">
          {empty ? (
            <p className="grid flex-1 place-items-center rounded-lg border-[1.5px] border-dashed border-input bg-surface px-6 py-10 text-center text-sm font-medium text-muted-foreground">
              Drag legacy drawings here as PDF, several at once if you like
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow className="[&>th]:text-[11px] [&>th]:font-semibold [&>th]:tracking-[.06em] [&>th]:text-faint [&>th]:uppercase">
                  <TableHead>Drawing</TableHead><TableHead>Status</TableHead><TableHead className="text-right">Explained</TableHead>
                  <TableHead className="text-right">Views</TableHead><TableHead className="text-right">Texts</TableHead>
                  <TableHead className="text-right">To review</TableHead><TableHead className="text-right">Machine</TableHead>
                  <TableHead className="text-right">Review</TableHead><TableHead className="text-right">By hand</TableHead>
                  <TableHead className="text-right">Size</TableHead><TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {sources.map((source, i) => (
                  <SourceRow key={source.source_id} source={source} analysis={analyses[i]?.data} flags={pages[i]?.data?.flags}
                    error={analyses[i]?.error ?? null}
                    machineSeconds={machineBySource.get(source.source_id) ?? null}
                    measurements={measurements.filter((m) => m.source_id === source.source_id)} />
                ))}
                {uploads.map((upload) => <UploadRow key={upload.id} upload={upload} />)}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </>
  );
}

const NUM = "text-right tabular-nums";

/** Machine time of the latest run of a drawing, if it succeeded. */
const latestSeconds = (runs: Run[] | undefined) => {
  const latest = runs?.at(-1);
  return latest ? runSeconds(latest) : null;
};

interface SourceRowProps {
  source: Source;
  analysis: ExtractResult | undefined;
  flags?: ReviewFlag[];
  error: Error | null;
  machineSeconds?: number | null;
  measurements?: Measurement[];
}

export function SourceRow({ source, analysis, flags, error, machineSeconds = null, measurements = [] }: SourceRowProps) {
  const navigate = useNavigate();
  const [tone, label] = analysisStatus(analysis, error !== null, flags);
  const open = () => void navigate({ to: "/sources/$sourceId", params: { sourceId: source.source_id } });
  const d = analysis?.drawing;
  const human = effort(measurements);
  return (
    <TableRow tabIndex={0} onClick={open} onKeyDown={(e) => e.key === "Enter" && open()} className="cursor-pointer">
      <TableCell className="font-semibold text-card-foreground" title={`SHA-256 ${source.sha256}`}>{partName(source.filename)}</TableCell>
      <TableCell>
        <StatusBadge tone={tone} title={error?.message}>{label}</StatusBadge>
        {error && (
          <p className="mt-1 max-w-md text-xs text-flag" role="alert">
            Analysis failed ({errorCode(error)}): {error.message} {recoveryFor(error)}
          </p>
        )}
      </TableCell>
      <TableCell className={NUM}>{analysis ? pct(explainedShare(analysis).share) : "–"}</TableCell>
      <TableCell className={NUM}>{d ? fmt(d.views.length) : "–"}</TableCell>
      <TableCell className={NUM}>{d ? fmt(d.text_blocks.length) : "–"}</TableCell>
      <TableCell className={NUM}>{analysis ? fmt(openFlags(analysis, flags)) : "–"}</TableCell>
      <TableCell className={NUM}>{machineSeconds === null ? "–" : duration(machineSeconds)}</TableCell>
      <TableCell className={NUM} title={human.reviews > 1 ? `median of ${human.reviews} reviews` : undefined}>
        {human.reviewSeconds === null ? "–" : duration(human.reviewSeconds)}
      </TableCell>
      <TableCell className={NUM} title={human.estimators.map((e) => ESTIMATOR_LABEL[e]).join(", ") || undefined}>
        {human.manualHours === null ? "–" : hours(human.manualHours)}
      </TableCell>
      <TableCell className={NUM}>{bytes(source.byte_count)}</TableCell>
      <TableCell className="w-8"><DeleteButton source={source} /></TableCell>
    </TableRow>
  );
}

/** Deletes a drawing after a second click, so that one stray click removes nothing. */
function DeleteButton({ source }: { source: Source }) {
  const api = useApi();
  const queryClient = useQueryClient();
  const [armed, setArmed] = useState(false);
  const name = partName(source.filename);
  const remove = useMutation({
    mutationFn: () => api.deleteSource(source.source_id),
    onSuccess: async () => {
      // Refresh the list first: its rows observe the analysis, which would otherwise be read again and fail.
      await queryClient.invalidateQueries({ queryKey: keys.sources, exact: true });
      for (const key of [keys.source(source.source_id), keys.analysis(source.source_id), keys.runs(source.source_id)]) {
        queryClient.removeQueries({ queryKey: key });
      }
      toast.success(`${name} deleted`);
    },
    onError: (err) => toast.error(`${name} not deleted`, { description: `${err.message} ${recoveryFor(err)}` }),
    onSettled: () => setArmed(false),
  });
  // The row opens the drawing on click and Enter; the button handles its own events.
  const stop = (e: React.SyntheticEvent) => e.stopPropagation();
  return (
    <span onClick={stop} onKeyDown={stop}>
      {armed ? (
        <Button variant="destructive" size="xs" autoFocus disabled={remove.isPending} onBlur={() => !remove.isPending && setArmed(false)}
          onClick={() => remove.mutate()}>
          Delete
        </Button>
      ) : (
        <Button variant="ghost" size="icon" className="size-7 text-muted-foreground" aria-label={`Delete ${name}`} title="Delete drawing"
          onClick={() => setArmed(true)}>
          <Trash2 className="size-3.5" />
        </Button>
      )}
    </span>
  );
}

function UploadRow({ upload }: { upload: Upload }) {
  const { dismiss } = useUploads();
  const [tone, label] = uploadStatus(upload);
  return (
    <TableRow className="hover:bg-transparent">
      <TableCell className="font-semibold text-card-foreground">{partName(upload.name)}</TableCell>
      <TableCell><StatusBadge tone={tone} title={upload.error ?? undefined}>{label}</StatusBadge></TableCell>
      <TableCell colSpan={8}>
        {upload.state === "error"
          ? <span className="text-flag">{upload.error}</span>
          : <Progress value={upload.progress * 100} aria-label={`Upload ${upload.name}`} className="h-1.5" />}
      </TableCell>
      <TableCell className="w-8">
        {upload.state === "error" && (
          <Button variant="ghost" size="icon" className="size-7" aria-label="Dismiss message" onClick={() => dismiss(upload.id)}>
            <X className="size-3.5" />
          </Button>
        )}
      </TableCell>
    </TableRow>
  );
}
