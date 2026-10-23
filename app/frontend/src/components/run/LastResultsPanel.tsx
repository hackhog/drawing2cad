// The service selects these outputs. Their build revision can precede the current part revision.
import { useMutation, useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { toast } from "sonner";
import { StatusBadge } from "@/components/Status";
import { Button } from "@/components/ui/button";
import { ARTIFACT_LABEL } from "@/lib/artifactLabels";
import { useApi } from "@/lib/apiContext";
import type { Artifact, Run } from "@/lib/contract";
import { saveBlob } from "@/lib/download";
import { recoveryFor } from "@/lib/errors";
import { bytes } from "@/lib/format";
import { capabilitiesQuery } from "@/lib/queries";
import { lastResultArtifacts, lastResultModel } from "@/lib/release";
import { PHASE_LABEL } from "@/lib/status";
import { BlobView, Empty, Preview } from "./ArtifactPreview";

export function LastResultsPanel({ run }: { run: Run }) {
  const api = useApi();
  const { data: caps } = useQuery(capabilitiesQuery(api));
  const download = useMutation({
    mutationFn: async (artifact: Artifact) => saveBlob(await api.readArtifact(artifact.artifact_id), artifact.filename),
    onError: (err) => toast.error("Download failed", { description: err.message + " " + recoveryFor(err) }),
  });
  const last = run.last_results;
  if (!last) return null;
  const artifacts = lastResultArtifacts(run);
  const candidate = lastResultModel(run);
  const drawing = artifacts.find((artifact) => artifact.role === "drawing_pdf");
  const verification = artifacts.find((artifact) => artifact.role === "verification_preview");
  return (
    <section aria-label="Last results (not released)" className="flex flex-col gap-3 rounded-lg border border-warn-line bg-warn-bg/30 p-3">
      <h2 className="font-semibold text-card-foreground">Last results (not released)</h2>
      <p className="text-sm">{last.reason}</p>
      <p className="text-xs text-muted-foreground">Failed phase: {last.failed_phase ? PHASE_LABEL[last.failed_phase] : "not recorded"}</p>
      {last.blocking.length > 0 && <ul aria-label="Blocking findings" className="flex flex-col gap-1">
        {last.blocking.map((finding, index) => <li key={finding.rule_id + "-" + index} className="rounded-md border px-2.5 py-1.5 text-xs">
          <strong>{finding.rule_id}</strong> · {finding.status.replaceAll("_", " ")}
          <p>{finding.feature ? finding.feature + ": " : ""}{finding.message}</p>
        </li>)}
      </ul>}
      {!last.model && <p className="text-sm font-medium">No STEP model is available: {last.no_model_reason ?? "The run ended before the first valid build."}</p>}
      {last.model && <section aria-label="Last model validation" className="text-xs">
        <h3 className="font-semibold">Last validated build · Rev. {last.model.model_revision} · not released</h3>
        <ul>{last.model.validation.map((result, index) => <li key={result.check + "-" + index}>
          {result.check} · {result.status.replaceAll("_", " ")} · {result.detail}
        </li>)}</ul>
      </section>}
      <ul aria-label="Last result files" className="flex flex-col gap-1.5">
        {artifacts.map((artifact) => <li key={artifact.artifact_id} className="flex flex-wrap items-center gap-3 rounded-md border px-3 py-2">
          <div className="min-w-0 flex-1">
            <strong className="block break-all text-card-foreground">{artifact.filename}</strong>
            <p className="text-xs text-muted-foreground">{ARTIFACT_LABEL[artifact.role]} · {bytes(artifact.byte_count)} · Rev. {artifact.model_revision}</p>
            <p className="text-xs text-muted-foreground">{artifact.reason ?? last.reason}</p>
          </div>
          <StatusBadge tone="flag">not released</StatusBadge>
          <Button variant="outline" size="sm" disabled={!caps?.downloads || download.isPending}
            aria-label={"Download " + artifact.filename} onClick={() => download.mutate(artifact)}><Download /></Button>
        </li>)}
      </ul>
      <div className="grid grid-cols-2 gap-3 max-[1200px]:grid-cols-1">
        <Preview title={"Last drawing" + (drawing ? " · Rev. " + drawing.model_revision : "") + " · not released"}>
          {drawing && !run.simulated ? <BlobView artifact={drawing} kind="pdf" />
            : <Empty text={run.simulated ? "No drawing preview for simulated results." : "No rendered drawing is available."} />}
        </Preview>
        <Preview title={"Candidate model" + (candidate ? " · Rev. " + candidate.model_revision : "") + " · not released"}>
          {candidate ? <BlobView artifact={candidate} kind="glb" notReleased />
            : <Empty text={last.model ? "The candidate model file is unavailable." : "No STEP model is available."} />}
        </Preview>
        {verification && <Preview title="Last verification preview · not released"><BlobView artifact={verification} kind="png" /></Preview>}
      </div>
    </section>
  );
}
