// Show release outputs and the separate last results selected by the service.
import { useMutation, useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { toast } from "sonner";
import { LastResultsPanel } from "./LastResultsPanel";
import { BlobView, Empty, Preview } from "./ArtifactPreview";
import { StatusBadge } from "@/components/Status";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { useApi } from "@/lib/apiContext";
import { saveBlob } from "@/lib/download";
import type { Artifact, ReleaseDrawing, Run } from "@/lib/contract";
import { recoveryFor } from "@/lib/errors";
import { bytes, shortHash } from "@/lib/format";
import { capabilitiesQuery } from "@/lib/queries";
import { ARTIFACT_LABEL } from "@/lib/artifactLabels";
import { delivery, isDraft, isReleased, latestShown } from "@/lib/release";

// The service reports the drawing status recorded by the STEP release.
const DRAWING_STATUS: Record<ReleaseDrawing["status"], string> = {
  accepted: "Drawing reviewed and verified.",
  unverified: "Drawing reviewed, but its final PDF verification did not pass the acceptance gate.",
  unreviewed: "Drawing created, but not reviewed.",
  rejected: "Drawing rejected in review.",
  failed: "Drawing faulty. The diagnostic files are not released.",
  missing: "No drawing created.",
};

export function ArtifactsPanel({ run }: { run: Run }) {
  const api = useApi();
  const { data: caps } = useQuery(capabilitiesQuery(api));
  const state = delivery(run);
  const revision = run.part?.revision;
  const download = useMutation({
    mutationFn: async (a: Artifact) => saveBlob(await api.readArtifact(a.artifact_id), a.filename),
    onError: (err) => toast.error("Download failed", { description: `${err.message} ${recoveryFor(err)}` }),
  });
  const released = (a: Artifact) => isReleased(state, run, a);
  const diagnostic = (a: Artifact) => isDraft(state, run, a);
  // A draft drawing is shown for review: the drawing review needs a person who can see the drawing.
  const preview = latestShown(run, "step");
  const drawing = latestShown(run, "drawing_pdf");
  const lastIds = new Set(run.last_results?.artifact_ids ?? []);
  const otherFiles = run.artifacts.filter((a) => !lastIds.has(a.artifact_id));

  return (
    <div className="flex flex-col gap-4">
      {state.released ? (
        <Alert className="border-good/30 bg-good-bg text-good">
          <AlertTitle>Released: model of revision {revision}</AlertTitle>
          {run.review?.drawing && (
            <AlertDescription>
              <p>{DRAWING_STATUS[run.review.drawing.status]}{run.review.drawing.current ? "" : " This state is outdated: the drawing or a released file was changed after the release."}</p>
              {run.review.drawing.delivery === "complete_service" && (
                <p>{run.review.drawing.pair_current ? "Complete-service delivery: the STEP model and the drawing PDF are verified as one pair."
                  : "Complete-service delivery is outdated: the released STEP and drawing no longer form the verified pair."}</p>
              )}
              {run.review.drawing.reason && <p>{run.review.drawing.reason}</p>}
            </AlertDescription>
          )}
        </Alert>
      ) : (
        <Alert className="border-warn-line bg-warn-bg">
          <AlertTitle>Not released</AlertTitle>
          <AlertDescription>{state.reasons.map((r) => <p key={r}>{r}</p>)}</AlertDescription>
        </Alert>
      )}

      {run.last_results && <LastResultsPanel run={run} />}
      {run.last_results && otherFiles.length > 0 && <h2 className="font-semibold">Other run files</h2>}
      <ul className="flex flex-col gap-1.5">
        {!run.artifacts.length && !run.last_results && <li className="text-muted-foreground">No results yet.</li>}
        {otherFiles.map((a) => {
          const ok = released(a);
          const diag = diagnostic(a);
          const stale = a.model_revision !== revision;
          const candidate = a.role === "step_candidate" || a.release_status === "not_released";
          return (
            <li key={a.artifact_id} className="flex items-center gap-3 rounded-md border px-3 py-2 data-[stale]:opacity-60" data-stale={stale || undefined}>
              <div className="min-w-0 flex-1">
                <strong className="block text-card-foreground">{ARTIFACT_LABEL[a.role]}</strong>
                <span className="block truncate text-[11px] text-muted-foreground" title={`SHA-256 ${a.sha256}`}>
                  {a.filename} · {bytes(a.byte_count)} · SHA-256 {shortHash(a.sha256)}
                </span>
              </div>
              <span className="text-[11px] text-muted-foreground">Rev. {a.model_revision}</span>
              <StatusBadge tone={ok ? "done" : diag ? "flag" : stale ? "flag" : "error"}>
                {ok ? "released" : candidate ? "not released" : diag ? "diagnostic" : stale ? "outdated" : "locked"}
              </StatusBadge>
              <Button variant="outline" size="sm" disabled={!(ok || diag) || !caps?.downloads || download.isPending}
                aria-label={`Download ${a.filename}`} onClick={() => download.mutate(a)}>
                <Download />
              </Button>
            </li>
          );
        })}
      </ul>

      {!run.last_results && <section className="grid grid-cols-2 gap-3 max-[1200px]:grid-cols-1">
        <Preview title={`Drawing${drawing ? ` · Rev. ${drawing.model_revision} · ${released(drawing) ? "released" : "draft, not released"}` : ""}`}>
          {drawing && !run.simulated ? <BlobView artifact={drawing} kind="pdf" />
            : <Empty text={run.simulated ? "No drawing preview for simulated results." : "No drawing created yet."} />}
        </Preview>
        <Preview title={`Model${preview ? ` · Rev. ${preview.model_revision} · ${released(preview) ? "released" : "diagnostic, not released"}` : ""}`}>
          {preview ? <BlobView artifact={preview} kind="glb" notReleased={!released(preview)} />
            : <Empty text={caps?.model_preview ? "No 3D preview yet." : "The connected service does not provide a 3D preview yet."} />}
        </Preview>
      </section>}
    </div>
  );
}
