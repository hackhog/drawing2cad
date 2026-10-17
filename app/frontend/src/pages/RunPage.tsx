// Run page: job state, parameters and operations, review data, deliverables, and notes of one CAD run.
import { useQuery, useSuspenseQuery } from "@tanstack/react-query";
import { getRouteApi, Link } from "@tanstack/react-router";
import { ArrowLeft } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { ArtifactsPanel } from "@/components/run/ArtifactsPanel";
import { JobCard } from "@/components/run/JobCard";
import { NotesPanel } from "@/components/run/NotesPanel";
import { ParametersPanel } from "@/components/run/ParametersPanel";
import { ReviewPanel } from "@/components/run/ReviewPanel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useApi } from "@/lib/apiContext";
import { partName, time } from "@/lib/format";
import { runQuery, sourceQuery } from "@/lib/queries";

export const RUN_TABS = ["parameter", "review", "results", "notes"] as const;
export type RunTab = (typeof RUN_TABS)[number];
const LABEL: Record<RunTab, string> = { parameter: "Parameter", review: "Prüfung", results: "Ergebnisse", notes: "Notizen" };

const route = getRouteApi("/runs/$runId");

export function RunPage() {
  const api = useApi();
  const { runId } = route.useParams();
  const { tab = "parameter" } = route.useSearch();
  const navigate = route.useNavigate();
  const { data: run } = useSuspenseQuery(runQuery(api, runId));
  const { data: source } = useQuery(sourceQuery(api, run.source_id));

  return (
    <>
      <PageHeader
        title={<span className="flex items-center gap-2">Lauf {run.run_id}{run.simulated && <Badge variant="secondary" className="bg-warn-bg text-bad">Simuliert</Badge>}</span>}
        subtitle={`${source ? partName(source.filename) : run.source_id} · Revision ${run.part?.revision ?? "–"} · gestartet ${time(run.job.started_at)}`
          + (run.agent ? ` · ${run.agent.model} · MCP ${run.agent.mcp_version}` : "")}
        actions={
          <Button variant="outline" size="sm" className="rounded-full" asChild>
            <Link to="/sources/$sourceId" params={{ sourceId: run.source_id }}><ArrowLeft />Zur Zeichnung</Link>
          </Button>
        }
      />
      <section className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_300px] gap-3 max-[1000px]:grid-cols-1">
        <Card className="min-h-0 gap-0 overflow-y-auto rounded-xl px-3.5 pt-3 pb-3.5 shadow-none">
          <Tabs value={tab} onValueChange={(next) => void navigate({ search: { tab: next as RunTab } })}>
            <TabsList className="mb-3">
              {RUN_TABS.map((t) => <TabsTrigger key={t} value={t}>{LABEL[t]}</TabsTrigger>)}
            </TabsList>
            <TabsContent value="parameter"><ParametersPanel run={run} /></TabsContent>
            <TabsContent value="review"><ReviewPanel run={run} /></TabsContent>
            <TabsContent value="results"><ArtifactsPanel run={run} /></TabsContent>
            <TabsContent value="notes"><NotesPanel run={run} /></TabsContent>
          </Tabs>
        </Card>
        <div className="flex min-h-0 flex-col gap-3"><JobCard run={run} /></div>
      </section>
    </>
  );
}
