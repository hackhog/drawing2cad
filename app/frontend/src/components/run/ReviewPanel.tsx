// Review data: release state, assumptions, uncertainty markers, and validation results.
// `not_tested` is shown as such and never as a pass.
import { StatusBadge } from "@/components/Status";
import type { DrawingAcceptance, ReleaseState, Run, ValidationResult } from "@/lib/contract";
import { fmt } from "@/lib/format";
import { delivery } from "@/lib/release";
import type { Tone } from "@/lib/status";

const RELEASE: Record<ReleaseState, [Tone, string]> = {
  draft: ["wait", "draft"], stale: ["flag", "outdated"], blocked: ["flag", "not released"], released: ["done", "released"],
};
const CHECK: Record<ValidationResult["status"], [Tone, string]> = {
  pass: ["done", "passed"], fail: ["error", "failed"], not_tested: ["wait", "not tested"],
};

const ACCEPTANCE: Record<DrawingAcceptance["status"], [Tone, string]> = {
  accepted: ["done", "accepted"], unverified: ["flag", "not verified"], unreviewed: ["wait", "not reviewed"],
  rejected: ["error", "rejected"], failed: ["error", "faulty"], missing: ["wait", "missing"],
};
const FINDING: Record<string, [Tone, string]> = {
  fail: ["error", "failed"], needs_review: ["flag", "needs review"], not_tested: ["wait", "not tested"], not_applicable: ["wait", "no reason"],
};

const region = (r: [number, number, number, number] | null) => r ? `x ${Math.round(r[0])} · y ${Math.round(r[1])}` : "no location";
const H3 = "mb-1.5 text-xs font-semibold tracking-[.06em] text-faint uppercase";

export function ReviewPanel({ run }: { run: Run }) {
  const review = run.review;
  if (!review) return <p className="text-muted-foreground">No review data yet.</p>;
  const [tone, label] = RELEASE[review.release_state];
  const { reasons } = delivery(run);
  return (
    <div className="flex flex-col gap-5">
      <section className="flex flex-col gap-1.5">
        <div className="flex items-center gap-2"><span className="font-semibold text-card-foreground">Release</span><StatusBadge tone={tone}>{label}</StatusBadge></div>
        {reasons.map((r) => <p key={r} className="text-xs text-muted-foreground">{r}</p>)}
      </section>

      {review.drawing_acceptance && <AcceptanceSection acceptance={review.drawing_acceptance} />}

      {run.agent_report && (
        <section>
          <h3 className={H3}>Agent report</h3>
          <p className="rounded-md border bg-surface px-3 py-2 text-xs whitespace-pre-wrap text-card-foreground [overflow-wrap:anywhere]">{run.agent_report}</p>
        </section>
      )}

      <section>
        <h3 className={H3}>Assumptions ({review.assumptions.length})</h3>
        {!review.assumptions.length && <p className="text-xs text-muted-foreground">No open assumptions.</p>}
        <ul className="flex flex-col gap-1.5">
          {review.assumptions.map((a) => (
            <li key={a.id} className="rounded-md border border-warn-line bg-warn-bg px-2.5 py-1.5">
              <div className="flex items-baseline justify-between gap-2">
                <strong className="text-card-foreground">{a.id} · {a.feature}{a.parameter ? ` · ${a.parameter} = ${fmt(a.value)} ${a.unit}` : ""}</strong>
                <span className="text-[11px] whitespace-nowrap text-muted-foreground">{region(a.source_region)}</span>
              </div>
              <p className="text-xs text-muted-foreground">{a.reason}</p>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h3 className={H3}>Uncertainties ({review.uncertainties.length})</h3>
        {!review.uncertainties.length && <p className="text-xs text-muted-foreground">No flagged uncertainties.</p>}
        <ul className="flex flex-col gap-1">
          {review.uncertainties.map((u) => (
            <li key={u.id} className="flex items-baseline gap-2 text-xs">
              <i className="size-[7px] flex-none rounded-full bg-highlight" />
              <span className="flex-1"><b>{u.feature}:</b> {u.message}</span>
              <span className="text-muted-foreground">{region(u.source_region)}</span>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h3 className={H3}>Checks</h3>
        {!review.validation.length && <p className="text-xs text-muted-foreground">Checks run after the model is built.</p>}
        <ul className="flex flex-col gap-1">
          {review.validation.map((v) => {
            const [t, l] = CHECK[v.status];
            return (
              <li key={v.check} className="flex items-center gap-2.5 rounded-md border px-2.5 py-1.5">
                <code className="w-32 text-[11px]">{v.check}</code>
                <span className="flex-1 text-xs text-muted-foreground">{v.detail}</span>
                <StatusBadge tone={t}>{l}</StatusBadge>
              </li>
            );
          })}
        </ul>
      </section>
    </div>
  );
}

/** The acceptance of the drawing. A blocking finding is shown with its own status; not_tested is never shown as a pass. */
function AcceptanceSection({ acceptance }: { acceptance: DrawingAcceptance }) {
  const [tone, label] = ACCEPTANCE[acceptance.status];
  const verification = acceptance.verification;
  return (
    <section className="flex flex-col gap-1.5" aria-label="Drawing verification">
      <div className="flex items-center gap-2"><span className="font-semibold text-card-foreground">Drawing</span><StatusBadge tone={tone}>{label}</StatusBadge></div>
      {acceptance.reason && <p className="text-xs text-muted-foreground">{acceptance.reason}</p>}
      {!verification && <p className="text-xs text-muted-foreground">The final PDF has no verification.</p>}
      {verification && (
        <>
          <p className="text-xs text-muted-foreground">
            Verification {verification.status ?? "missing"} · {verification.validity === "current" ? "current" : "outdated"} ·
            {" "}{verification.gate_passed ? "acceptance gate passed" : `${verification.blocking_count} blocking findings`}
            {verification.reviewed_count ? ` · ${verification.reviewed_count} decided in review` : ""}
          </p>
          <ul className="flex flex-col gap-1">
            {verification.blocking.map((item) => {
              const [t, l] = FINDING[item.status] ?? ["wait", item.status];
              return (
                <li key={`${item.rule_id}-${item.feature ?? ""}`} className="flex items-center gap-2.5 rounded-md border px-2.5 py-1.5">
                  <code className="w-24 text-[11px]">{item.rule_id}</code>
                  <span className="flex-1 text-xs text-muted-foreground">{item.feature ? `${item.feature}: ` : ""}{item.message}</span>
                  <StatusBadge tone={t}>{l}</StatusBadge>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </section>
  );
}
