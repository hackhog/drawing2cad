// Review data: release state, assumptions, uncertainty markers, and validation results.
// `not_tested` is shown as such and never as a pass.
import { StatusBadge } from "@/components/Status";
import type { ReleaseState, Run, ValidationResult } from "@/lib/contract";
import { delivery } from "@/lib/release";
import type { Tone } from "@/lib/status";

const RELEASE: Record<ReleaseState, [Tone, string]> = {
  draft: ["wait", "Entwurf"], stale: ["flag", "veraltet"], blocked: ["error", "gesperrt"], released: ["done", "freigegeben"],
};
const CHECK: Record<ValidationResult["status"], [Tone, string]> = {
  pass: ["done", "bestanden"], fail: ["error", "fehlgeschlagen"], not_tested: ["wait", "nicht geprüft"],
};

const region = (r: [number, number, number, number] | null) => r ? `x ${Math.round(r[0])} · y ${Math.round(r[1])}` : "ohne Ort";
const H3 = "mb-1.5 text-xs font-semibold tracking-[.06em] text-faint uppercase";

export function ReviewPanel({ run }: { run: Run }) {
  const review = run.review;
  if (!review) return <p className="text-muted-foreground">Noch keine Prüfdaten.</p>;
  const [tone, label] = RELEASE[review.release_state];
  const { reasons } = delivery(run);
  return (
    <div className="flex flex-col gap-5">
      <section className="flex flex-col gap-1.5">
        <div className="flex items-center gap-2"><span className="font-semibold text-card-foreground">Freigabe</span><StatusBadge tone={tone}>{label}</StatusBadge></div>
        {reasons.map((r) => <p key={r} className="text-xs text-muted-foreground">{r}</p>)}
      </section>

      <section>
        <h3 className={H3}>Annahmen ({review.assumptions.length})</h3>
        {!review.assumptions.length && <p className="text-xs text-muted-foreground">Keine offenen Annahmen.</p>}
        <ul className="flex flex-col gap-1.5">
          {review.assumptions.map((a) => (
            <li key={a.id} className="rounded-md border border-warn-line bg-warn-bg px-2.5 py-1.5">
              <div className="flex items-baseline justify-between gap-2">
                <strong className="text-card-foreground">{a.id} · {a.feature}{a.parameter ? ` · ${a.parameter} = ${a.value.toLocaleString("de-DE")} ${a.unit}` : ""}</strong>
                <span className="text-[11px] whitespace-nowrap text-muted-foreground">{region(a.source_region)}</span>
              </div>
              <p className="text-xs text-muted-foreground">{a.reason}</p>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h3 className={H3}>Unsicherheiten ({review.uncertainties.length})</h3>
        {!review.uncertainties.length && <p className="text-xs text-muted-foreground">Keine markierten Unsicherheiten.</p>}
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
        <h3 className={H3}>Prüfungen</h3>
        {!review.validation.length && <p className="text-xs text-muted-foreground">Prüfungen laufen nach dem Modellbau.</p>}
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
