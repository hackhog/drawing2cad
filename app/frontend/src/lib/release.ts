// Presentation of the release state that the service reports. The service owns the release gate;
// the UI only refuses to present an artifact as released when the run state does not support it.
import type { Artifact, Run } from "./contract";

const DELIVERABLE_ROLES = new Set(["drawing_pdf", "drawing_dxf", "step"]);

export interface Delivery {
  released: boolean;
  /** All drawing and model artifacts refer to the current part revision. */
  revisionsAgree: boolean;
  reasons: string[];
}

export function delivery(run: Run): Delivery {
  const revision = run.part?.revision ?? null;
  const outputs = run.artifacts.filter((a) => DELIVERABLE_ROLES.has(a.role));
  const revisionsAgree = revision !== null && outputs.length > 0 && outputs.every((a) => a.model_revision === revision);
  const reasons: string[] = [];
  const state = run.review?.release_state ?? "draft";
  if (state === "stale") reasons.push("Ergebnisse gehören zu einer älteren Revision und werden neu erzeugt.");
  // "blocked" also covers a valid build without release; name a failed check only when one failed.
  const failed = run.review?.validation.some((v) => v.status === "fail") ?? false;
  if (state === "blocked") reasons.push(failed ? "Eine Prüfung ist fehlgeschlagen. Die Ergebnisse sind gesperrt."
    : "Modell gebaut, aber nicht freigegeben: Geprüfte Zeichnung und STEP-Freigabe fehlen.");
  if (state === "draft") reasons.push("Noch keine geprüften Ergebnisse.");
  // These checks guard against an inconsistent service state; the reported state already explains the other cases.
  if (state === "released" && outputs.length && !revisionsAgree) reasons.push("Zeichnung und Modell gehören nicht zur aktuellen Revision.");
  if (state === "released" && failed) reasons.push("Mindestens eine Prüfung ist fehlgeschlagen.");
  return { released: state === "released" && revisionsAgree && reasons.length === 0, revisionsAgree, reasons };
}

/** An artifact is released only if the run is released, the artifact has the current revision, and the release names it. */
export const isReleased = (state: Delivery, run: Run, artifact: Artifact): boolean =>
  state.released && artifact.model_revision === run.part?.revision && (artifact.released ?? true);

export const isActive = (run: Run) => run.job.status === "queued" || run.job.status === "running";

/** A draft belongs to the current revision of a finished run that the service did not release. */
export const isDraft = (state: Delivery, run: Run, artifact: Artifact): boolean =>
  !isReleased(state, run, artifact) && !isActive(run) && artifact.model_revision === run.part?.revision;

/** The latest released or draft artifact of a role. The service lists artifacts in creation order. */
export const latestShown = (run: Run, role: Artifact["role"]): Artifact | undefined => {
  const state = delivery(run);
  return run.artifacts.findLast((a) => a.role === role && (isReleased(state, run, a) || isDraft(state, run, a)));
};
