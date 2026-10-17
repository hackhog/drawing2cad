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
import type { ExtractResult } from "@/lib/drawing";
import { dropTarget } from "@/lib/drop";
import { errorCode, recoveryFor } from "@/lib/errors";
import { ESTIMATOR_LABEL } from "@/lib/estimators";
import { bytes, duration, euros, explainedShare, fmt, hours, partName, pct } from "@/lib/format";
import { analysisQuery, keys, measurementsQuery, runsQuery, sourcesQuery } from "@/lib/queries";
import { analysisStatus, uploadStatus } from "@/lib/status";
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
  const analyses = useQueries({ queries: sources.map((s) => analysisQuery(api, s.source_id)) });
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
  const flags = done.reduce((a, r) => a + r.review.length, 0);
  const empty = !sources.length && !uploads.length;
  const b = benefit(runs.map((q) => q.data ?? []));
  const built = b.models > 0;
  const human = effort(measurements);
  const saved = saving(b, human, assumptions);
  const machineBySource = new Map(sources.map((s, i) => [s.source_id, latestSeconds(runs[i]?.data)]));
  const csv = measurementsCsv(measurements, new Map(sources.map((s) => [s.source_id, { name: partName(s.filename), machineSeconds: machineBySource.get(s.source_id) ?? null }])));

  const [jobsSub, jobsTone]: [string, Tone] = busy ? [`${busy} in Arbeit`, ""]
    : failed ? [`${failed} nicht lesbar`, "bad"]
    : sources.length ? ["alle gelesen", "good"] : ["gelesen und gespeichert", ""];

  return (
    <>
      <PageHeader
        title="Übersicht" live={done.length > 0}
        subtitle={empty ? "Noch keine Zeichnung hochgeladen" : `${fmt(done.length)} von ${fmt(sources.length + busy)} Zeichnungen gelesen`}
        actions={<UploadButton label={empty ? "PDFs hochladen" : "Weitere PDFs"} />}
      />

      <section aria-label="Kennzahlen" className="grid grid-cols-4 gap-3 max-[1000px]:grid-cols-2">
        <Tile title="Zeichnungen" value={<Big>{empty ? "–" : fmt(done.length)}</Big>} sub={jobsSub} tone={jobsTone} />
        <Tile
          title="Erklärt"
          extra={
            <div role="radiogroup" aria-label="Darstellung" className="flex gap-0.5 rounded-[7px] bg-muted p-0.5">
              {([[false, "Zahl", Hash], [true, "Tacho", Gauge]] as const).map(([mode, label, Icon]) => (
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
          sub={total ? `${fmt(explained)} von ${fmt(total)} Strichen zugeordnet` : "Anteil der Striche mit sicherer Bedeutung"}
        />
        <Tile
          title="Texte gelesen" value={<Big>{done.length ? fmt(texts.length) : "–"}</Big>}
          sub={!done.length ? "Maße, Schnitte, Hinweise" : unsure ? `${unsure} nicht sicher gelesen` : "alle sicher gelesen"}
          tone={!done.length ? "" : unsure ? "bad" : "good"}
        />
        <Tile
          title="Zu prüfen" warn={flags > 0} value={<Big>{done.length ? fmt(flags) : "–"}</Big>}
          sub={!done.length ? "Markiert statt geraten" : flags === 1 ? "Stelle markiert statt geraten" : flags ? "Stellen markiert statt geraten" : "nichts offen"}
          tone={!done.length ? "" : flags ? "bad" : "good"}
        />
      </section>

      <section aria-labelledby="benefit-title" className="grid gap-1.5">
        <h2 id="benefit-title" className="flex items-center gap-2 text-[11px] font-semibold tracking-[.06em] text-faint uppercase">
          Nutzen{b.simulated && <Badge variant="secondary" className="bg-warn-bg text-bad normal-case tracking-normal">Simuliert</Badge>}
          <span className="ml-auto">
            <BenefitDialog built={b} human={human} result={saved} assumptions={assumptions} onAssumptions={setAssumptions} csv={csv} />
          </span>
        </h2>
        <div className="grid grid-cols-3 gap-3 max-[1000px]:grid-cols-2">
          <Tile
            title="3D-Modelle" value={<Big>{built || b.active ? fmt(b.models) : "–"}</Big>}
            sub={b.active ? `${b.active} im Bau` : built ? `aus ${fmt(done.length)} gelesenen Zeichnungen` : "STEP aus der Zeichnung gebaut"}
          />
          <Tile
            title="Freigegeben" value={<Big>{built ? fmt(b.released) : "–"}</Big>}
            sub={!built ? "nur geprüfte Modelle" : b.released ? "geprüft und lieferbar" : "Entwürfe warten auf Prüfung"}
            tone={built && b.released ? "good" : ""}
          />
          <Tile
            title="Maße aus Zeichnung" value={<Big>{b.parameters ? pct(b.fromDrawing / b.parameters) : "–"}</Big>}
            sub={!b.parameters ? "belegt statt abgetippt"
              : `${fmt(b.fromDrawing)} von ${fmt(b.parameters)} belegt${b.assumed ? `, ${fmt(b.assumed)} angenommen` : ""}`}
          />
          <Tile
            title="Zeit je Modell" value={<Big>{b.medianSeconds === null ? "–" : duration(b.medianSeconds)}</Big>}
            sub={b.medianSeconds === null ? "Zeichnung bis STEP" : "Median, Zeichnung bis STEP"}
          />
          <Tile
            title="Prüfzeit" value={<Big>{human.reviewSeconds === null ? "–" : duration(human.reviewSeconds)}</Big>}
            sub={human.reviewSeconds === null ? "Stoppuhr in Schritt 3 „Prüfen“"
              : `Median aus ${fmt(human.reviews)} Prüfung${human.reviews === 1 ? "" : "en"}`}
          />
          <Tile
            title="Gespart" value={<Big>{saved ? hours(saved.hours) : "–"}</Big>}
            sub={!saved ? "von Hand gegen Lauf und Prüfung"
              : `≈ ${euros(saved.euros)}, ${saved.manualAssumed ? `Annahme ${hours(saved.manualHours)} von Hand` : `von Hand ${hours(saved.manualHours)} geschätzt`}`}
            tone={saved && saved.hours > 0 ? "good" : ""}
          />
        </div>
      </section>

      <Card {...drop} className={cn("min-h-0 flex-1 gap-2.5 rounded-xl px-3.5 pt-3 pb-3.5 shadow-none", over && "ring-4 ring-primary/10")}>
        <CardHeader className="flex flex-row items-center justify-between px-0">
          <CardTitle className="text-sm font-bold">Zeichnungen</CardTitle>
          <span className="rounded-full bg-info-bg px-2.5 py-0.5 text-[11px] font-semibold text-info">Tabelle</span>
        </CardHeader>
        <CardContent className="flex min-h-0 flex-1 flex-col px-0">
          {empty ? (
            <p className="grid flex-1 place-items-center rounded-lg border-[1.5px] border-dashed border-input bg-surface px-6 py-10 text-center text-sm font-medium text-muted-foreground">
              Alte Zeichnungen als PDF hierher ziehen, gern mehrere auf einmal
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow className="[&>th]:text-[11px] [&>th]:font-semibold [&>th]:tracking-[.06em] [&>th]:text-faint [&>th]:uppercase">
                  <TableHead>Zeichnung</TableHead><TableHead>Status</TableHead><TableHead className="text-right">Erklärt</TableHead>
                  <TableHead className="text-right">Ansichten</TableHead><TableHead className="text-right">Texte</TableHead>
                  <TableHead className="text-right">Zu prüfen</TableHead><TableHead className="text-right">Maschine</TableHead>
                  <TableHead className="text-right">Prüfung</TableHead><TableHead className="text-right">Von Hand</TableHead>
                  <TableHead className="text-right">Größe</TableHead><TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {sources.map((source, i) => (
                  <SourceRow key={source.source_id} source={source} analysis={analyses[i]?.data} error={analyses[i]?.error ?? null}
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
  error: Error | null;
  machineSeconds?: number | null;
  measurements?: Measurement[];
}

export function SourceRow({ source, analysis, error, machineSeconds = null, measurements = [] }: SourceRowProps) {
  const navigate = useNavigate();
  const [tone, label] = analysisStatus(analysis, error !== null);
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
            Analyse fehlgeschlagen ({errorCode(error)}): {error.message} {recoveryFor(error)}
          </p>
        )}
      </TableCell>
      <TableCell className={NUM}>{analysis ? pct(explainedShare(analysis).share) : "–"}</TableCell>
      <TableCell className={NUM}>{d ? fmt(d.views.length) : "–"}</TableCell>
      <TableCell className={NUM}>{d ? fmt(d.text_blocks.length) : "–"}</TableCell>
      <TableCell className={NUM}>{analysis ? fmt(analysis.review.length) : "–"}</TableCell>
      <TableCell className={NUM}>{machineSeconds === null ? "–" : duration(machineSeconds)}</TableCell>
      <TableCell className={NUM} title={human.reviews > 1 ? `Median aus ${human.reviews} Prüfungen` : undefined}>
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
      toast.success(`${name} gelöscht`);
    },
    onError: (err) => toast.error(`${name} nicht gelöscht`, { description: `${err.message} ${recoveryFor(err)}` }),
    onSettled: () => setArmed(false),
  });
  // The row opens the drawing on click and Enter; the button handles its own events.
  const stop = (e: React.SyntheticEvent) => e.stopPropagation();
  return (
    <span onClick={stop} onKeyDown={stop}>
      {armed ? (
        <Button variant="destructive" size="xs" autoFocus disabled={remove.isPending} onBlur={() => !remove.isPending && setArmed(false)}
          onClick={() => remove.mutate()}>
          Löschen
        </Button>
      ) : (
        <Button variant="ghost" size="icon" className="size-7 text-muted-foreground" aria-label={`${name} löschen`} title="Zeichnung löschen"
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
          <Button variant="ghost" size="icon" className="size-7" aria-label="Meldung schließen" onClick={() => dismiss(upload.id)}>
            <X className="size-3.5" />
          </Button>
        )}
      </TableCell>
    </TableRow>
  );
}
