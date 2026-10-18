// Job state of a run: the actual phase from the service, progress, and a structured error.
import { Check } from "lucide-react";
import { StatusBadge } from "@/components/Status";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { RunFiles } from "@/components/run/RunFiles";
import type { Run, RunPhase } from "@/lib/contract";
import { time } from "@/lib/format";
import { PHASE_LABEL, runStatus } from "@/lib/status";
import { cn } from "@/lib/utils";

const SEQUENCE: RunPhase[] = ["queued", "analyzing", "modeling", "drawing", "validating", "done"];

export function JobCard({ run }: { run: Run }) {
  const [tone, label] = runStatus(run);
  // A failed run marks the phase in which it stopped. Older records have no such phase.
  const current = SEQUENCE.indexOf(run.phase === "failed" ? (run.failed_phase ?? "validating") : run.phase);
  return (
    <Card className="gap-3 rounded-xl px-3.5 pt-3 pb-3.5 shadow-none">
      <CardHeader className="flex flex-row items-center justify-between px-0">
        <CardTitle className="text-sm font-bold">Job</CardTitle>
        <StatusBadge tone={tone}>{label}</StatusBadge>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 px-0">
        <Progress value={(run.job.progress ?? 0) * 100} aria-label="Progress" className="h-1.5" />
        <ol className="flex flex-col gap-1">
          {SEQUENCE.map((phase, i) => {
            const passed = i < current || run.phase === "done";
            const here = i === current && run.phase !== "done";
            return (
              <li key={phase} className={cn("flex items-center gap-2 text-xs text-faint", (passed || here) && "text-card-foreground", here && "font-semibold")}>
                <span className={cn("grid size-4 place-items-center rounded-full border text-[9px]",
                  passed && "border-good bg-good text-white", here && (run.phase === "failed" ? "border-flag bg-flag" : "border-run bg-run dot-run"))}>
                  {passed && <Check className="size-2.5" />}
                </span>
                {PHASE_LABEL[phase]}
              </li>
            );
          })}
        </ol>
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
          <dt>Job</dt><dd className="truncate font-mono text-[11px]">{run.job.job_id}</dd>
          <dt>Started</dt><dd>{time(run.job.started_at)}</dd>
          <dt>Finished</dt><dd>{run.job.finished_at ? time(run.job.finished_at) : "–"}</dd>
          {run.iterations && (
            <>
              <dt>Turns</dt><dd>{run.iterations.model_turns}</dd>
              <dt>Tools</dt><dd>{run.iterations.tool_requests} of {run.iterations.step_budget} calls</dd>
            </>
          )}
          {run.agent && (
            <>
              {run.agent.profile && <><dt>Profile</dt><dd className="truncate">{run.agent.profile}</dd></>}
              <dt>Model</dt><dd className="truncate font-mono text-[11px]" title={run.agent.model}>{run.agent.model}</dd>
              {run.agent.reasoning_effort !== undefined && (
                <><dt>Reasoning</dt><dd className="font-mono text-[11px]">{run.agent.reasoning_effort ?? "not set"}</dd></>
              )}
              {run.agent.skill_version !== undefined && (
                <><dt>Skill</dt><dd className="font-mono text-[11px]">drawing2cad {run.agent.skill_version ?? "unversioned"}</dd></>
              )}
              <dt>MCP</dt><dd className="font-mono text-[11px]">drawing2cad-mcp {run.agent.mcp_version}</dd>
            </>
          )}
        </dl>
        {run.error && (
          <Alert variant="destructive" className="[overflow-wrap:anywhere]">
            <AlertTitle className="line-clamp-none">{run.error.message}</AlertTitle>
            <AlertDescription>
              {run.error.recovery && <p>{run.error.recovery}</p>}
              <code className="text-[11px]">{run.error.code}{run.error.field ? ` · ${run.error.field}` : ""}</code>
            </AlertDescription>
          </Alert>
        )}
        <RunFiles run={run} />
      </CardContent>
    </Card>
  );
}
