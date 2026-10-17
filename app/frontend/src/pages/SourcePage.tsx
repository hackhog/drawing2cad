// Drawing page: the guided sequence Drawing → Recognized → Review → 3D model (ADR 0007),
// the review list, and the CAD runs of this source.
import { useMutation, useQuery, useQueryClient, useSuspenseQuery } from "@tanstack/react-query";
import { getRouteApi, Link, useNavigate } from "@tanstack/react-router";
import { ChevronRight, Maximize, Play } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { FlagList } from "@/components/FlagList";
import { ModelPanel } from "@/components/ModelPanel";
import { PageHeader } from "@/components/PageHeader";
import { SheetViewer } from "@/components/SheetViewer";
import { StatusBadge } from "@/components/Status";
import { UploadButton } from "@/components/UploadButton";
import { VIEWER_FRAME } from "@/components/viewerFrame";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useApi } from "@/lib/apiContext";
import type { ReviewFlag } from "@/lib/drawing";
import { dropTarget } from "@/lib/drop";
import { recoveryFor } from "@/lib/errors";
import { explainedShare, partName, pct, shortHash, time } from "@/lib/format";
import { analysisQuery, capabilitiesQuery, keys, runsQuery, sourceQuery } from "@/lib/queries";
import { runStatus } from "@/lib/status";
import { setStepPreview, useStepPreview } from "@/lib/stepPreviews";
import { isPdf, useUploads } from "@/lib/uploads";
import { cn } from "@/lib/utils";

export type Step = 1 | 2 | 3 | 4;
const STEPS: [Step, string][] = [[1, "Zeichnung"], [2, "Erkannt"], [3, "Prüfen"], [4, "3D-Modell"]];

const route = getRouteApi("/sources/$sourceId");

export function SourcePage() {
  const { sourceId } = route.useParams();
  // A new key per source resets the selected flag and the zoom when the user opens another drawing.
  return <SourceView key={sourceId} sourceId={sourceId} />;
}

/** `null` = default (step 3 starts at the first located flag), "sheet" = the full sheet. */
type Pick = ReviewFlag | "sheet" | null;

function SourceView({ sourceId }: { sourceId: string }) {
  const api = useApi();
  const { step = 1 } = route.useSearch();
  const navigate = useNavigate({ from: "/sources/$sourceId" });
  const { addFiles } = useUploads();
  const { data: source } = useSuspenseQuery(sourceQuery(api, sourceId));
  const { data: result } = useSuspenseQuery(analysisQuery(api, sourceId));
  const [picked, setPicked] = useState<Pick>(null);
  const [fitKey, setFitKey] = useState(0);
  const drop = dropTarget((files) => addFiles(files.filter(isPdf)), () => {});

  const focus = step !== 3 || picked === "sheet" ? null : picked ?? result.review.find((f) => f.bbox) ?? null;
  const fitSheet = () => { setPicked("sheet"); setFitKey((k) => k + 1); };
  const setStep = (next: Step) => {
    setPicked(null);
    setFitKey((k) => k + 1);
    void navigate({ search: { step: next } });
  };

  const d = result.drawing;
  const story = {
    1: `Eine Zeichnung ohne 3D-Modell: ${d.sheet_size_mm[0]} × ${d.sheet_size_mm[1]} mm, keine Textebene, nur Striche.`,
    2: `${d.summary.strokes.toLocaleString("de-DE")} Striche klassifiziert, ${d.summary.views} Ansichten gefunden, ${d.summary.text_blocks} Maße und Texte gelesen. Ohne KI, nachvollziehbar.`,
    3: result.review.length ? `${result.review.length} Stelle(n) ohne sichere Bedeutung: markiert statt geraten.` : "Keine unklaren Stellen: alles erklärt.",
    4: "Aus der geprüften Zeichnung baut der Dienst ein parametrisches Modell und exportiert STEP.",
  }[step];

  return (
    <>
      <PageHeader
        title={partName(source.filename)} live
        subtitle={`Hochgeladen ${time(source.created_at)} · ${pct(explainedShare(result).share)} erklärt · SHA-256 ${shortHash(source.sha256)}`}
        actions={<>
          {step < 4 && (
            <Button variant="outline" size="sm" className="rounded-full" onClick={fitSheet}>
              <Maximize />Ganzes Blatt
            </Button>
          )}
          <UploadButton label="Weitere PDFs" />
        </>}
      />

      <section aria-label="Zeichnung" className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_320px] gap-3 max-[1000px]:grid-cols-1">
        <Card className="min-h-0 gap-0 rounded-xl px-3.5 pt-3 pb-3.5 shadow-none">
          <nav aria-label="Ablauf" className="mb-2.5 inline-flex flex-wrap gap-0.5 self-start rounded-[10px] bg-muted p-[3px]">
            {STEPS.map(([n, label]) => (
              <button key={n} type="button" aria-current={n === step ? "step" : undefined} onClick={() => setStep(n)}
                className="group inline-flex items-center gap-2 rounded-lg px-3.5 py-1.5 font-medium text-muted-foreground hover:text-card-foreground aria-[current=step]:bg-card aria-[current=step]:font-semibold aria-[current=step]:text-card-foreground aria-[current=step]:shadow-[0_1px_2px_rgb(17_20_24/.08),0_0_0_1px_var(--border)]">
                <b className="grid size-[18px] place-items-center rounded-full bg-border text-[10.5px] font-bold group-aria-[current=step]:bg-primary group-aria-[current=step]:text-primary-foreground">{n}</b>
                {label}
              </button>
            ))}
          </nav>
          {step === 4
            ? <StepModel sourceId={sourceId} />
            : <SheetViewer result={result} focus={focus} fitKey={fitKey} step={step} dropProps={drop} />}
          <footer className="mt-3 flex items-center justify-between gap-4">
            <p className="text-[13.5px]">{story}</p>
            {step < 4 && <Button size="sm" className="rounded-full" onClick={() => setStep((step + 1) as Step)}>Weiter</Button>}
          </footer>
        </Card>

        <div className="flex min-h-0 flex-col gap-3">
          <FlagList
            flags={result.review} active={focus} highlight={step === 3}
            onSelect={(f) => { if (step !== 3) void navigate({ search: { step: 3 } }); setPicked(f); }}
          />
          <RunsCard sourceId={sourceId} />
        </div>
      </section>
    </>
  );
}

/** Step 4: a STEP preview that the user supplies (legacy service), or a pointer to the CAD run. */
function StepModel({ sourceId }: { sourceId: string }) {
  const api = useApi();
  const { data: caps } = useQuery(capabilitiesQuery(api));
  // Each drawing keeps its preview while the user navigates; the store frees replaced GLB URLs.
  const model = useStepPreview(sourceId);
  const convert = useMutation({
    mutationFn: (file: File) => api.stepPreview(file),
    onMutate: (file) => setStepPreview(sourceId, { state: "run", name: file.name }),
    onSuccess: (glb, file) => setStepPreview(sourceId, { state: "done", name: file.name, url: URL.createObjectURL(glb) }),
    onError: (err, file) => setStepPreview(sourceId, { state: "error", name: file.name, error: `${err.message} ${recoveryFor(err)}` }),
  });

  if (caps?.step_preview_upload) return <ModelPanel model={model} onStep={(f) => convert.mutate(f)} />;
  return (
    <div className={cn(VIEWER_FRAME, "grid place-items-center p-6 text-center text-muted-foreground")}>
      <p className="max-w-sm">Das 3D-Modell entsteht in einem CAD-Lauf. Lauf rechts starten oder öffnen; die Vorschau zeigt dort die geprüfte Revision.</p>
    </div>
  );
}

function RunsCard({ sourceId }: { sourceId: string }) {
  const api = useApi();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: caps } = useQuery(capabilitiesQuery(api));
  const { data: runs = [] } = useQuery({ ...runsQuery(api, sourceId), enabled: caps?.runs === true });
  const start = useMutation({
    mutationFn: () => api.createRun(sourceId),
    onSuccess: async (run) => {
      await queryClient.invalidateQueries({ queryKey: keys.runs(sourceId) });
      void navigate({ to: "/runs/$runId", params: { runId: run.run_id } });
    },
    onError: (err) => toast.error("Lauf nicht gestartet", { description: `${err.message} ${recoveryFor(err)}` }),
  });

  return (
    <Card className="gap-2.5 rounded-xl px-3.5 pt-3 pb-3.5 shadow-none">
      <CardHeader className="flex flex-row items-center justify-between px-0">
        <CardTitle className="text-sm font-bold">CAD-Läufe</CardTitle>
        <Button size="sm" className="h-7 rounded-full" disabled={!caps?.runs || start.isPending} onClick={() => start.mutate()}>
          <Play className="size-3" />Lauf starten
        </Button>
      </CardHeader>
      <CardContent className="px-0">
        {!caps?.runs ? (
          <p className="text-xs text-muted-foreground">
            Der verbundene Dienst liest nur Zeichnungen. Modell und technische Zeichnung erzeugt er noch nicht.
          </p>
        ) : !runs.length ? (
          <p className="text-xs text-muted-foreground">Noch kein Lauf für diese Zeichnung.</p>
        ) : (
          <ul>
            {runs.map((run) => {
              const [tone, label] = runStatus(run);
              return (
                <li key={run.run_id}>
                  <Link to="/runs/$runId" params={{ runId: run.run_id }}
                    className={cn("flex items-center gap-2 rounded-md px-1.5 py-2 hover:bg-accent")}>
                    <span className="flex-1 font-medium text-card-foreground">{run.run_id}</span>
                    <span className="text-[11px] text-muted-foreground">Rev. {run.part?.revision ?? "–"}</span>
                    <StatusBadge tone={tone}>{label}</StatusBadge>
                    <ChevronRight className="size-3.5 text-muted-foreground" />
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
