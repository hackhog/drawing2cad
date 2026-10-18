// Sidebar: overview, every stored drawing with its status, and uploads in progress.
// While the settings are open, the settings sections replace the drawings. The footer opens the settings.
import { useQueries, useQuery } from "@tanstack/react-query";
import { Link, useRouterState } from "@tanstack/react-router";
import { Bot, LayoutGrid, Settings, type LucideIcon } from "lucide-react";
import type { Capabilities } from "@/lib/contract";
import { useApi } from "@/lib/apiContext";
import { partName } from "@/lib/format";
import { analysisQuery, capabilitiesQuery, flagsQuery, sourcesQuery } from "@/lib/queries";
import { SETTINGS_SECTIONS, type SettingsSection } from "@/lib/settings";
import { analysisStatus, uploadStatus, type Tone } from "@/lib/status";
import { useUploads } from "@/lib/uploads";
import { cn } from "@/lib/utils";
import { StatusDot } from "./Status";

const ITEM = "flex w-full items-center gap-2.5 rounded-lg px-2 py-[7px] text-left hover:bg-accent";
const SECTION_ICONS: Record<SettingsSection, LucideIcon> = { agent: Bot };
const CURRENT = "data-[status=active]:bg-highlight-bg data-[status=active]:font-semibold data-[status=active]:text-card-foreground";

function agentLabel(caps: Capabilities | undefined): [Tone, string] {
  if (caps?.simulated) return ["flag", "Simulated service"];
  if (caps?.agent_model) return ["done", `${caps.agent_profile ?? "KI-Agent"} · ${caps.agent_model}`];
  return ["wait", "Local, no AI"];
}

export function Sidebar() {
  const api = useApi();
  const { data: caps } = useQuery(capabilitiesQuery(api));
  const settings = useRouterState({ select: (state) => state.location.pathname.startsWith("/settings") });
  const [tone, label] = agentLabel(caps);

  return (
    <aside className="flex min-h-0 flex-col px-3 pt-4 pb-3">
      <div className="flex items-center gap-2.5 px-2 pt-1.5 pb-3.5 text-sm font-bold text-card-foreground">
        <span aria-hidden="true" className="grid size-[26px] place-items-center rounded-[7px] bg-primary text-primary-foreground">
          <svg viewBox="0 0 16 16" className="size-3.5 fill-none stroke-current stroke-2" strokeLinecap="round"><path d="M4 11V8M8 11V5M12 11V7" /></svg>
        </span>
        Drawing2CAD
      </div>

      <Link to="/" activeOptions={{ exact: true }} className={cn(ITEM, CURRENT, "mb-1.5 font-medium")}>
        <LayoutGrid className="size-4 text-muted-foreground" />Overview
      </Link>

      {settings ? <SettingsSections /> : <Drawings flagDecisions={!!caps?.flag_decisions} />}

      <footer className="mt-auto border-t pt-1">
        {/* Same layout as the user block below: round icon, title, and one line of status. */}
        <Link to="/settings/$section" params={{ section: "agent" }} title={label} className={cn(ITEM, CURRENT, "my-1.5 gap-2.5")}>
          <span aria-hidden="true" className="grid size-8 flex-none place-items-center rounded-full bg-muted text-muted-foreground">
            <Settings className="size-4" />
          </span>
          <span className="min-w-0 flex-1">
            <strong className="block font-bold text-card-foreground">Settings</strong>
            <small className="flex items-center gap-1.5 text-[11.5px] font-normal text-muted-foreground">
              <StatusDot tone={tone} /><span className="min-w-0 truncate">{label}</span>
            </small>
          </span>
        </Link>
        <div className="flex items-center gap-2.5 border-t px-2 pt-3 pb-1 max-[1000px]:hidden">
          <span aria-hidden="true" className="grid size-8 flex-none place-items-center rounded-full bg-highlight-bg text-[11.5px] font-bold text-bad">KO</span>
          <div><strong className="block font-bold text-card-foreground">Design</strong><small className="text-[11.5px] text-muted-foreground">Demo workspace</small></div>
        </div>
      </footer>
    </aside>
  );
}

function SettingsSections() {
  return (
    <>
      <p className="mx-2 mt-2 mb-1.5 text-[11px] font-semibold tracking-[.06em] text-faint uppercase">Settings</p>
      <ul aria-label="Settings">
        {SETTINGS_SECTIONS.map((section) => {
          const Icon = SECTION_ICONS[section.id];
          return (
            <li key={section.id}>
              <Link to="/settings/$section" params={{ section: section.id }} className={cn(ITEM, CURRENT, "font-medium")}>
                <Icon className="size-4 text-muted-foreground" />{section.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </>
  );
}

function Drawings({ flagDecisions }: { flagDecisions: boolean }) {
  const api = useApi();
  const { data: sources = [] } = useQuery(sourcesQuery(api));
  const analyses = useQueries({ queries: sources.map((s) => analysisQuery(api, s.source_id)) });
  const flags = useQueries({ queries: sources.map((s) => ({ ...flagsQuery(api, s.source_id), enabled: flagDecisions })) });
  const { uploads } = useUploads();

  return (
    <>
        <p className="mx-2 mt-2 mb-1.5 text-[11px] font-semibold tracking-[.06em] text-faint uppercase">Drawings</p>
        <ul aria-label="Uploaded drawings" className="min-h-0 overflow-y-auto">
          {!sources.length && !uploads.length && <li className="px-2 py-1 text-faint">None yet</li>}
          {sources.map((source, i) => {
            const [tone, label] = analysisStatus(analyses[i]?.data, analyses[i]?.isError ?? false, flags[i]?.data?.flags);
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
    </>
  );
}
