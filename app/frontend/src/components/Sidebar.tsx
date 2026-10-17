// Sidebar: overview, every stored drawing with its status, and uploads in progress.
import { useQueries, useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { LayoutGrid } from "lucide-react";
import { useApi } from "@/lib/apiContext";
import { partName } from "@/lib/format";
import { analysisQuery, capabilitiesQuery, sourcesQuery } from "@/lib/queries";
import { analysisStatus, uploadStatus } from "@/lib/status";
import { useUploads } from "@/lib/uploads";
import { cn } from "@/lib/utils";
import { StatusDot } from "./Status";

const ITEM = "flex w-full items-center gap-2.5 rounded-lg px-2 py-[7px] text-left hover:bg-accent";
const CURRENT = "data-[status=active]:bg-highlight-bg data-[status=active]:font-semibold data-[status=active]:text-card-foreground";

export function Sidebar() {
  const api = useApi();
  const { data: sources = [] } = useQuery(sourcesQuery(api));
  const { data: caps } = useQuery(capabilitiesQuery(api));
  const analyses = useQueries({ queries: sources.map((s) => analysisQuery(api, s.source_id)) });
  const { uploads } = useUploads();

  return (
    <aside className="flex min-h-0 flex-col px-3 pt-4 pb-3">
      <div className="flex items-center gap-2.5 px-2 pt-1.5 pb-3.5 text-sm font-bold text-card-foreground">
        <span aria-hidden="true" className="grid size-[26px] place-items-center rounded-[7px] bg-primary text-primary-foreground">
          <svg viewBox="0 0 16 16" className="size-3.5 fill-none stroke-current stroke-2" strokeLinecap="round"><path d="M4 11V8M8 11V5M12 11V7" /></svg>
        </span>
        Drawing2CAD
      </div>

      <Link to="/" activeOptions={{ exact: true }} className={cn(ITEM, CURRENT, "mb-1.5 font-medium")}>
        <LayoutGrid className="size-4 text-muted-foreground" />Übersicht
      </Link>

      <p className="mx-2 mt-2 mb-1.5 text-[11px] font-semibold tracking-[.06em] text-faint uppercase">Zeichnungen</p>
      <ul aria-label="Hochgeladene Zeichnungen" className="min-h-0 overflow-y-auto">
        {!sources.length && !uploads.length && <li className="px-2 py-1 text-faint">Noch keine</li>}
        {sources.map((source, i) => {
          const [tone, label] = analysisStatus(analyses[i]?.data, analyses[i]?.isError ?? false);
          return (
            <li key={source.source_id}>
              <Link to="/sources/$sourceId" params={{ sourceId: source.source_id }} search={(prev) => ({ step: "step" in prev ? prev.step : undefined })}
                title={source.filename} className={cn(ITEM, CURRENT)}>
                <StatusDot tone={tone} />
                <span className="min-w-0 flex-1 truncate font-medium text-card-foreground">{partName(source.filename)}</span>
                <small className="text-[11px] text-muted-foreground">{label}</small>
              </Link>
            </li>
          );
        })}
        {uploads.map((upload) => {
          const [tone, label] = uploadStatus(upload);
          return (
            <li key={`u${upload.id}`} title={upload.error ?? upload.name} className={cn(ITEM, "cursor-default hover:bg-transparent")}>
              <StatusDot tone={tone} />
              <span className="min-w-0 flex-1 truncate font-medium text-card-foreground">{partName(upload.name)}</span>
              <small className={cn("text-[11px] text-muted-foreground", tone === "error" && "text-flag")}>{label}</small>
            </li>
          );
        })}
      </ul>

      <footer className="mt-auto pt-2.5 max-[1000px]:hidden">
        <div className="flex items-center gap-2 border-t px-2 py-2.5 text-xs text-muted-foreground">
          <StatusDot tone={caps?.simulated ? "flag" : "done"} />
          <span className="min-w-0 truncate" title={caps?.agent_model ?? undefined}>
            {caps?.simulated ? "Simulierter Dienst" : caps?.agent_model ? `KI-Agent · ${caps.agent_model}` : "Lokal, ohne KI"}
          </span>
        </div>
        <div className="flex items-center gap-2.5 border-t px-2 pt-3 pb-1">
          <span aria-hidden="true" className="grid size-8 flex-none place-items-center rounded-full bg-highlight-bg text-[11.5px] font-bold text-bad">KO</span>
          <div><strong className="block font-bold text-card-foreground">Konstruktion</strong><small className="text-[11.5px] text-muted-foreground">Demo-Arbeitsplatz</small></div>
        </div>
      </footer>
    </aside>
  );
}
