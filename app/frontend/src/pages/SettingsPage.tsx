// Settings page: one section at a time; the sidebar lists the sections.
import { useParams } from "@tanstack/react-router";
import { PageHeader } from "@/components/PageHeader";
import { AgentModelSettings } from "@/components/settings/AgentModelSettings";
import { SETTINGS_SECTIONS } from "@/lib/settings";

export function SettingsPage() {
  const { section } = useParams({ from: "/settings/$section" });
  const current = SETTINGS_SECTIONS.find((s) => s.id === section) ?? SETTINGS_SECTIONS[0];
  return (
    <>
      <PageHeader title={current.label} subtitle={current.description} />
      {current.id === "agent" && <AgentModelSettings />}
    </>
  );
}
