import { StatusBadge } from "@/components/Status";
import { useApi } from "@/lib/apiContext";
import { useArtifactUrl } from "@/lib/artifacts";
import { delivery } from "@/lib/release";
import type { ProjectionCheck, ProjectionStatus, ProjectionView, Run } from "@/lib/contract";
import type { Tone } from "@/lib/status";

const STATE: Record<ProjectionStatus, [Tone, string]> = {
  matches: ["done", "matches"], deviates: ["error", "deviates"], not_tested: ["flag", "not tested"],
};

/** A source-projection result is separate from the release state and the generated drawing verification. */
export function ProjectionBadge({ status = "not_tested" }: { status?: ProjectionStatus }) {
  const [tone, label] = STATE[status];
  return <StatusBadge tone={tone}>{label}</StatusBadge>;
}

export function ProjectionSection({ run }: { run: Run }) {
  const check = run.projection;
  const status = check?.status ?? "not_tested";
  return (
    <section aria-label="Does the model match the drawing?" className="flex flex-col gap-3 rounded-lg border p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-semibold text-card-foreground">Does the model match the drawing?</h3>
        <ProjectionBadge status={status} />
      </div>
      {(run.simulated || check?.simulated) && <p className="text-xs font-semibold text-bad">Simulated projection data — not verification evidence.</p>}
      {check?.revision != null && <p className="text-xs text-muted-foreground">Part revision {check.revision}{check.page ? ` · Source page ${check.page}` : ""}</p>}
      {status === "not_tested" && (
        <div className="rounded-md border border-warn-line bg-warn-bg p-2 text-xs">
          <p>{check?.reason ?? "No projection check is available for the current revision."}</p>
          {delivery(run).released && <p className="mt-1 font-semibold">The release does not prove agreement with the source drawing.</p>}
        </div>
      )}
      {check && check.views.length > 0 && (
        <>
          <p className="text-xs text-muted-foreground">Grey = source drawing · Blue = built model · Red = largest deviations. Vertical marks show the reported limits.</p>
          {check.overlay_artifact_id && check.sheet_size_mm
            ? <ProjectionImages check={check} />
            : <ViewCards check={check} url={null} error="No overlay image is available for this check." />}
        </>
      )}
      <p className="text-xs text-muted-foreground">This compares projected views with the source drawing. It does not test every hidden feature or replace the other model checks.</p>
    </section>
  );
}

function ProjectionImages({ check }: { check: ProjectionCheck }) {
  const api = useApi();
  const { url, error } = useArtifactUrl(api, check.overlay_artifact_id!);
  return <ViewCards check={check} url={url} error={error} />;
}

function ViewCards({ check, url, error }: { check: ProjectionCheck; url: string | null; error: string | null }) {
  return <div className="grid gap-3 xl:grid-cols-2">{check.views.map((view, index) => {
    const [x0, y0, x1, y1] = view.region_sheet_mm;
    const [sheetWidth, sheetHeight] = check.sheet_size_mm ?? [0, 0];
    const left = Math.max(0, x0), top = Math.max(0, y0);
    const right = Math.min(sheetWidth, x1), bottom = Math.min(sheetHeight, y1);
    const visible = right > left && bottom > top;
    const name = `${view.view_id} (${index + 1})`;
    return (
      <article key={`${index}-${view.view_id}`} className="flex min-w-0 flex-col gap-3 rounded-md border bg-surface p-3" aria-label={`Projection view ${name}`}>
        <div className="flex items-center justify-between gap-2"><h4 className="font-semibold">{view.view_id}</h4>
          <ProjectionBadge status={view.status === "pass" ? "matches" : view.status === "fail" ? "deviates" : "not_tested"} /></div>
        {url && check.sheet_size_mm && visible ? (
          <svg viewBox={`${left} ${top} ${right - left} ${bottom - top}`} role="img" aria-label={`Source and model overlay for ${name}`}
            className="max-h-72 w-full rounded border bg-white" style={{ aspectRatio: `${right - left} / ${bottom - top}` }}>
            <title>Grey source drawing, blue model, red largest deviations</title>
            <image href={url} x="0" y="0" width={check.sheet_size_mm[0]} height={check.sheet_size_mm[1]} preserveAspectRatio="none" />
          </svg>
        ) : <p className="rounded border border-dashed p-3 text-xs text-muted-foreground" role="status">{error ?? (check.sheet_size_mm && !visible ? "The view region is outside the source sheet." : "Loading projection overlay…")}</p>}
        {view.reason && <p className="text-xs text-muted-foreground">{view.reason}</p>}
        <MetricBar label="p95 deviation" value={view.metrics.p95_mm} limit={view.limits.p95_mm} status={view.checks.p95} />
        <MetricBar label="Maximum deviation" value={view.metrics.max_mm} limit={view.limits.max_mm} status={view.checks.max} capped={view.max_capped} />
        <MetricBar label="Drawing coverage" value={view.metrics.coverage} limit={view.limits.coverage_min} status={view.checks.coverage} coverage />
      </article>
    );
  })}</div>;
}

function MetricBar({ label, value, limit, status, coverage = false, capped = false }: {
  label: string; value: number | null; limit: number | null; status: ProjectionView["status"]; coverage?: boolean; capped?: boolean;
}) {
  const format = (n: number) => coverage ? `${(n * 100).toFixed(1)}%` : `${n.toFixed(3)} mm`;
  const maximum = coverage ? 1 : Math.max(value ?? 0, (limit ?? 0) * 1.5, 0.001);
  const width = Math.max(0, Math.min(100, (value ?? 0) / maximum * 100));
  const mark = Math.max(0, Math.min(100, (limit ?? 0) / maximum * 100));
  const state = status === "pass" ? "passed" : status === "fail" ? "failed" : "not tested";
  return (
    <div className="flex flex-col gap-1 text-xs" role="group" aria-label={`${label}: ${value == null ? "unavailable" : format(value)}; ${state}`}>
      <div className="flex flex-wrap justify-between gap-1"><span>{label}</span><strong>{value == null ? "unavailable" : `${capped ? "≥ " : ""}${format(value)}`}</strong></div>
      <div className="relative h-2 overflow-hidden rounded bg-muted" aria-hidden="true">
        <div className={`h-full ${status === "fail" ? "bg-destructive" : status === "pass" ? "bg-good" : "bg-highlight"}`} style={{ width: `${width}%` }} />
        {limit != null && <span className="absolute inset-y-0 w-0.5 bg-card-foreground" style={{ left: `calc(${mark}% - 1px)` }} />}
      </div>
      <div className="flex justify-between gap-2 text-muted-foreground"><span>{limit == null ? "Limit unavailable" : `${coverage ? "Minimum" : "Limit"} ${format(limit)}`}</span><span>{state}</span></div>
    </div>
  );
}
