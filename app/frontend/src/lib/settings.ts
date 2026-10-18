// Sections of the settings page. The sidebar lists them in place of the drawings while the settings are open.
export const SETTINGS_SECTIONS = [
  { id: "agent", label: "AI model", description: "Model profiles for new CAD runs" },
] as const;

export type SettingsSection = (typeof SETTINGS_SECTIONS)[number]["id"];

export const isSettingsSection = (id: string): id is SettingsSection => SETTINGS_SECTIONS.some((s) => s.id === id);
