// Deliverables of a run. Artifacts of a released run with the current revision are released.
// A finished run without release keeps its current-revision model as a marked diagnostic artifact; stale artifacts stay locked.
import { useMutation, useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { toast } from "sonner";
import { ModelFrame } from "@/components/ModelPanel";
import { StatusBadge } from "@/components/Status";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { useApi } from "@/lib/apiContext";
import { useArtifactUrl } from "@/lib/artifacts";
import type { Artifact, ArtifactRole, Run } from "@/lib/contract";
import { recoveryFor } from "@/lib/errors";
import { bytes, shortHash } from "@/lib/format";
import { capabilitiesQuery } from "@/lib/queries";
import { delivery, isActive, isReleased } from "@/lib/release";

const ROLE: Record<ArtifactRole, string> = {
  drawing_pdf: "Technische Zeichnung (PDF)", drawing_dxf: "Technische Zeichnung (DXF)", step: "3D-Modell (STEP)",
  model_preview: "3D-Vorschau", manifest: "Lauf-Manifest",
};

function save(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement("a"), { href: url, download: filename });
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function ArtifactsPanel({ run }: { run: Run }) {
  const api = useApi();
  const { data: caps } = useQuery(capabilitiesQuery(api));
  const state = delivery(run);
  const revision = run.part?.revision;
  const download = useMutation({
    mutationFn: async (a: Artifact) => save(await api.readArtifact(a.artifact_id), a.filename),
    onError: (err) => toast.error("Download fehlgeschlagen", { description: `${err.message} ${recoveryFor(err)}` }),
  });
  const released = (a: Artifact) => isReleased(state, run, a);
  // A diagnostic artifact belongs to the current revision of a finished run that the service did not release.
  const diagnostic = (a: Artifact) => !released(a) && !isActive(run) && a.model_revision === revision;
  const preview = run.artifacts.find((a) => a.role === "model_preview" && (released(a) || diagnostic(a)));
  const drawing = run.artifacts.find((a) => a.role === "drawing_pdf" && released(a));

  return (
    <div className="flex flex-col gap-4">
      {state.released ? (
        <Alert className="border-good/30 bg-good-bg text-good">
          <AlertTitle>Freigegeben: Zeichnung und Modell gehören zu Revision {revision}</AlertTitle>
        </Alert>
      ) : (
        <Alert className="border-warn-line bg-warn-bg">
          <AlertTitle>Nicht freigegeben</AlertTitle>
          <AlertDescription>{state.reasons.map((r) => <p key={r}>{r}</p>)}</AlertDescription>
        </Alert>
      )}

      <ul className="flex flex-col gap-1.5">
        {!run.artifacts.length && <li className="text-muted-foreground">Noch keine Ergebnisse.</li>}
        {run.artifacts.map((a) => {
          const ok = released(a);
          const diag = diagnostic(a);
          const stale = a.model_revision !== revision;
          return (
            <li key={a.artifact_id} className="flex items-center gap-3 rounded-md border px-3 py-2 data-[stale]:opacity-60" data-stale={stale || undefined}>
              <div className="min-w-0 flex-1">
                <strong className="block text-card-foreground">{ROLE[a.role]}</strong>
                <span className="block truncate text-[11px] text-muted-foreground" title={`SHA-256 ${a.sha256}`}>
                  {a.filename} · {bytes(a.byte_count)} · SHA-256 {shortHash(a.sha256)}
                </span>
              </div>
              <span className="text-[11px] text-muted-foreground">Rev. {a.model_revision}</span>
              <StatusBadge tone={ok ? "done" : diag ? "flag" : stale ? "flag" : "error"}>
                {ok ? "freigegeben" : diag ? "Diagnose" : stale ? "veraltet" : "gesperrt"}
              </StatusBadge>
              <Button variant="outline" size="sm" disabled={!(ok || diag) || !caps?.downloads || download.isPending}
                aria-label={`${a.filename} herunterladen`} onClick={() => download.mutate(a)}>
                <Download />
              </Button>
            </li>
          );
        })}
      </ul>

      <section className="grid grid-cols-2 gap-3 max-[1200px]:grid-cols-1">
        <Preview title={`Zeichnung${drawing ? ` · Rev. ${drawing.model_revision}` : ""}`}>
          {drawing && !run.simulated ? <BlobView artifact={drawing} kind="pdf" />
            : <Empty text={run.simulated ? "Keine Zeichnungsvorschau für simulierte Ergebnisse." : "Keine freigegebene Zeichnung."} />}
        </Preview>
        <Preview title={`Modell${preview ? ` · Rev. ${preview.model_revision} · ${released(preview) ? "freigegeben" : "Diagnose, nicht freigegeben"}` : ""}`}>
          {preview ? <BlobView artifact={preview} kind="glb" />
            : <Empty text={caps?.model_preview ? "Noch keine 3D-Vorschau." : "Der verbundene Dienst liefert noch keine 3D-Vorschau."} />}
        </Preview>
      </section>
    </div>
  );
}

const Preview = ({ title, children }: { title: string; children: React.ReactNode }) => (
  <div className="flex min-h-[280px] flex-col gap-1.5">
    <h3 className="text-xs font-semibold tracking-[.06em] text-faint uppercase">{title}</h3>{children}
  </div>
);

const Empty = ({ text }: { text: string }) => (
  <div className="grid flex-1 place-items-center rounded-lg border bg-viewer p-6 text-center text-xs text-muted-foreground">{text}</div>
);

function BlobView({ artifact, kind }: { artifact: Artifact; kind: "pdf" | "glb" }) {
  const { url, error } = useArtifactUrl(useApi(), artifact.artifact_id);
  if (error) return <Empty text={error} />;
  if (!url) return <Empty text="Wird geladen …" />;
  if (kind === "glb") return <ModelFrame url={url} name={artifact.filename} />;
  return <object data={url} type="application/pdf" aria-label={artifact.filename} className="min-h-[280px] flex-1 rounded-lg border" />;
}
