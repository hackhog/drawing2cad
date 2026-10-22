// Run timeline (ADR 0038): what the skill, the agent loop, the MCP server, and the CAD worker did, step by step,
// with the failed calls and the corrections of the loop. It updates while the run is active.
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { useApi } from "@/lib/apiContext";
import type { Run, RunStep } from "@/lib/contract";
import { recoveryFor } from "@/lib/errors";
import { duration, fmt } from "@/lib/format";
import { runStepQuery, runStepsQuery } from "@/lib/queries";
import { isActive } from "@/lib/release";
import { explanation, LAYERS, layerOf, outcome, problemGroups, stepLabel, totals, type Layer } from "@/lib/timeline";
import { cn } from "@/lib/utils";

const LAYER_BG: Record<Layer, string> = { skill: "bg-info", loop: "bg-faint", mcp: "bg-run", cad: "bg-good" };
const LAYER_BORDER: Record<Layer, string> = { skill: "border-info", loop: "border-faint", mcp: "border-run", cad: "border-good" };
const H3 = "mb-1.5 text-xs font-semibold tracking-[.06em] text-faint uppercase";
const PRE = "max-h-72 overflow-auto rounded-md border bg-surface px-3 py-2 font-mono text-[11px] leading-snug whitespace-pre text-card-foreground";

const seconds = (s: number | null) => (s == null ? "" : s < 10 ? `${s.toFixed(1)} s` : duration(s));
const failed = (step: RunStep) => step.kind === "tool" && step.status === "failed";

/** The step to show first: the newest step of an active run, else the first failed call, else the last step. */
function initialStep(steps: RunStep[], active: boolean): number | null {
  if (!steps.length) return null;
  if (active) return steps[steps.length - 1].sequence;
  return (steps.find(failed) ?? steps[steps.length - 1]).sequence;
}

export function TimelinePanel({ run }: { run: Run }) {
  const api = useApi();
  const active = isActive(run);
  const { data, error, isPending } = useQuery({ ...runStepsQuery(api, run.run_id, run.job.status), placeholderData: (previous) => previous });
  const [chosen, setChosen] = useState<number | null>(null);
  const list = useRef<HTMLElement>(null);

  const steps = data?.steps ?? [];
  const selected = chosen ?? initialStep(steps, active);
  const step = steps.find((s) => s.sequence === selected) ?? null;

  // Scroll only the step list, so that the page keeps its position when a step is selected.
  useEffect(() => {
    const nav = list.current;
    const row = selected == null ? null : nav?.querySelector<HTMLElement>(`[data-sequence="${selected}"]`);
    if (!nav || !row) return;
    if (row.offsetTop < nav.scrollTop || row.offsetTop + row.offsetHeight > nav.scrollTop + nav.clientHeight) {
      nav.scrollTop = row.offsetTop - nav.clientHeight / 2;
    }
  }, [selected, steps.length]);

  if (isPending) return <p className="text-muted-foreground">Loading the agent trace …</p>;
  if (error) return <p className="text-flag">{error.message} {recoveryFor(error)}</p>;
  if (!steps.length) {
    return <p className="text-muted-foreground">{active ? "The agent has not started yet." : run.simulated
      ? "A simulated run has no agent trace." : "This run has no agent trace."}</p>;
  }

  const sum = totals(steps);
  const groups = problemGroups(steps);
  const ending = outcome(data.summary, run.iterations?.step_budget);
  const timed = steps.filter((s) => (s.kind === "model" || s.kind === "tool") && (s.seconds ?? 0) > 0);
  const layerCount = (id: Layer) => steps.filter((s) => layerOf(s) === id && s.kind !== "model" && s.kind !== "correction").length;

  return (
    <div className="flex flex-col gap-5">
      <section className="flex flex-col gap-1">
        {ending && <p className="font-semibold text-card-foreground">{ending}</p>}
        {active && <p className="font-semibold text-run">The run is active. New steps appear here.</p>}
        <p className="text-xs text-muted-foreground">
          {sum.turns} model turns · {duration(sum.modelSeconds)} model time · {sum.calls} tool calls · {seconds(sum.toolSeconds)} MCP and CAD time
          {sum.failed > 0 && <> · <span className="font-semibold text-flag">{sum.failed} failed</span></>}
          {sum.corrections > 0 && <> · {sum.corrections} corrections</>}
        </p>
      </section>

      <section aria-label="How a run works">
        <h3 className={H3}>How a run works</h3>
        <ol className="grid grid-cols-4 gap-2.5 max-[1200px]:grid-cols-2">
          {LAYERS.map((layer) => (
            <li key={layer.id} className={cn("border-t-[3px] pt-1.5", LAYER_BORDER[layer.id], step && layerOf(step) !== layer.id && "opacity-60")}>
              <div className="flex items-baseline justify-between gap-2">
                <strong className="text-sm text-card-foreground">{layer.title}</strong>
                <span className="text-[11px] text-muted-foreground">
                  {layer.id === "loop" ? `${sum.turns} turns` : layer.id === "skill" ? `${layerCount("skill")} supplies` : `${layerCount(layer.id)} calls`}
                </span>
              </div>
              <p className="text-xs text-muted-foreground">{layer.text}</p>
            </li>
          ))}
        </ol>
      </section>

      <section aria-label="Time line">
        <h3 className={H3}>Where the time went · width = duration</h3>
        <div className="flex h-6 overflow-hidden rounded-md border bg-surface">
          {timed.map((s) => (
            <button key={s.sequence} type="button" title={`${stepLabel(s)} · ${seconds(s.kind === "model" || s.kind === "tool" ? s.seconds : null)}`}
              aria-label={stepLabel(s)} onClick={() => setChosen(s.sequence)}
              style={{ flexGrow: (s.kind === "model" || s.kind === "tool") ? s.seconds ?? 0 : 0 }}
              className={cn("h-full min-w-[3px] basis-0 border-r border-card", failed(s) ? "bg-flag" : LAYER_BG[layerOf(s)],
                s.kind === "model" && "opacity-50", s.sequence === selected && "outline-2 -outline-offset-2 outline-card-foreground opacity-100")} />
          ))}
        </div>
        <ul className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
          <li><i className="mr-1 inline-block size-2.5 bg-faint opacity-50" />model</li>
          <li><i className="mr-1 inline-block size-2.5 bg-run" />MCP</li>
          <li><i className="mr-1 inline-block size-2.5 bg-good" />CAD</li>
          <li><i className="mr-1 inline-block size-2.5 bg-flag" />failed call</li>
        </ul>
      </section>

      {groups.length > 0 && (
        <section aria-label="Problems">
          <h3 className={H3}>Problems ({sum.failed} failed calls)</h3>
          <ul className="flex flex-col gap-1">
            {groups.map((g) => (
              <li key={`${g.tool}-${g.code}`}>
                <button type="button" onClick={() => setChosen(g.sequences[0])}
                  className="flex w-full items-baseline gap-2 rounded-md border border-flag/30 bg-flag-bg px-2.5 py-1.5 text-left text-xs hover:border-flag">
                  <code className="font-semibold text-flag">{g.code}</code>
                  <span className="text-card-foreground">{g.tool}{g.count > 1 ? ` · ${g.count}×` : ""}{g.first.target ? ` · ${g.first.target}` : ""}</span>
                  <span className="min-w-0 flex-1 truncate text-muted-foreground" title={g.first.message}>{g.first.message}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="grid grid-cols-[minmax(0,300px)_minmax(0,1fr)] gap-3 max-[1200px]:grid-cols-1">
        <nav ref={list} aria-label="Steps" className="relative max-h-[70vh] overflow-y-auto rounded-md border max-[1200px]:max-h-[40vh]">
          {steps.map((s) => (
            <button key={s.sequence} data-sequence={s.sequence} type="button" onClick={() => setChosen(s.sequence)}
              aria-current={s.sequence === selected ? "step" : undefined}
              className={cn("grid w-full grid-cols-[34px_minmax(0,1fr)_auto] items-baseline gap-1.5 border-b px-2.5 py-1.5 text-left hover:bg-surface",
                s.sequence === selected && "bg-run-bg shadow-[inset_3px_0_0_var(--run)]")}>
              <span className="font-mono text-[10.5px] text-faint">{s.turn != null ? `T${s.turn}` : ""}</span>
              <span className={cn("flex items-baseline gap-1.5 font-mono text-[11.5px] [overflow-wrap:anywhere]",
                failed(s) && "text-flag", s.kind === "correction" && "text-bad italic", s.kind === "model" && "text-muted-foreground")}>
                <i aria-hidden="true" className={cn("inline-block size-2 flex-none", failed(s) ? "bg-flag" : LAYER_BG[layerOf(s)])} />
                {stepLabel(s)}{failed(s) && " ✕"}
              </span>
              <span className="font-mono text-[10.5px] whitespace-nowrap text-muted-foreground">
                {s.kind === "tool" && s.status === "no_response" ? (active ? "running" : "no response")
                  : s.kind === "model" || s.kind === "tool" ? seconds(s.seconds) : ""}
              </span>
            </button>
          ))}
        </nav>
        {step && <StepDetail run={run} step={step} />}
      </section>
    </div>
  );
}

function StepDetail({ run, step }: { run: Run; step: RunStep }) {
  const api = useApi();
  const complete = step.kind !== "tool" || step.status !== "no_response";
  const { data, error, isPending } = useQuery(runStepQuery(api, run.run_id, step.sequence, complete));
  const layer = LAYERS.find((l) => l.id === layerOf(step))!;

  return (
    <article aria-live="polite" className="flex min-w-0 flex-col gap-3 rounded-md border px-3.5 py-3">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="min-w-0">
          <p className="text-[11px] font-semibold tracking-[.06em] text-faint uppercase">{layer.title}{step.turn != null ? ` · turn ${step.turn}` : ""}</p>
          <h3 className="font-mono text-base font-semibold [overflow-wrap:anywhere] text-card-foreground">{stepLabel(step)}</h3>
        </div>
        {step.kind === "model" && (
          <span className="text-xs text-muted-foreground">
            {seconds(step.seconds)} · {fmt(step.prompt_tokens ?? 0)} tokens in · {fmt(step.output_tokens ?? 0)} out
          </span>
        )}
        {step.kind === "tool" && step.seconds != null && <span className="text-xs text-muted-foreground">{seconds(step.seconds)}</span>}
      </header>
      <p className={cn("border-l-[3px] pl-2.5 text-xs text-card-foreground", LAYER_BORDER[layer.id])}>{explanation(step)}</p>

      {isPending ? <p className="text-xs text-muted-foreground">Loading the step …</p>
        : error ? <p className="text-xs text-flag">{error.message} {recoveryFor(error)}</p>
        : (
          <>
            {data.problem && (
              <Alert variant="destructive" className="[overflow-wrap:anywhere]">
                <AlertTitle className="line-clamp-none">{data.problem.code}{data.problem.target ? ` · ${data.problem.target}` : ""}</AlertTitle>
                <AlertDescription className="text-xs">{data.problem.message}</AlertDescription>
              </Alert>
            )}
            {data.text && (
              <section>
                <h4 className={H3}>{step.kind === "model" ? "Model text" : step.kind === "correction" ? "Message to the model" : "Reason"}</h4>
                <p className="max-h-56 overflow-auto rounded-md border bg-surface px-3 py-2 text-xs whitespace-pre-wrap text-card-foreground [overflow-wrap:anywhere]">{data.text}</p>
              </section>
            )}
            {step.kind === "model" && !data.text && <p className="text-xs text-muted-foreground italic">The model sent no text in this turn, only tool calls.</p>}
            <div className="grid grid-cols-2 gap-3 max-[1400px]:grid-cols-1">
              {data.arguments && (
                <section className="min-w-0">
                  <h4 className={H3}>{step.kind === "model" ? "Requested tool calls" : step.kind === "skill" ? "References" : "Arguments from the model"}</h4>
                  <pre className={PRE}>{data.arguments}</pre>
                </section>
              )}
              {step.kind === "tool" && (
                <section className="min-w-0">
                  <h4 className={H3}>Answer of the MCP server</h4>
                  {data.result != null ? <pre className={PRE}>{data.result}</pre>
                    : <p className="text-xs text-muted-foreground">{isActive(run) ? "The call is running." : "The call got no answer."}</p>}
                </section>
              )}
            </div>
            {data.images.length > 0 && (
              <section>
                <h4 className={H3}>Images that the model received</h4>
                <div className="grid grid-cols-[repeat(auto-fit,minmax(200px,1fr))] gap-2">
                  {data.images.map((src, i) => <img key={i} src={src} alt={`Image ${i + 1} of ${stepLabel(step)}`} className="w-full rounded-md border bg-white" />)}
                </div>
              </section>
            )}
          </>
        )}
    </article>
  );
}
