// Sections of the settings page. The sidebar lists them in place of the drawings while the settings are open.
export const SETTINGS_SECTIONS = [
  { id: "agent", label: "KI-Modell", description: "Modellprofile für neue CAD-Läufe" },
] as const;

export type SettingsSection = (typeof SETTINGS_SECTIONS)[number]["id"];

export const isSettingsSection = (id: string): id is SettingsSection => SETTINGS_SECTIONS.some((s) => s.id === id);
