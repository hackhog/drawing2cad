// Stable error codes and the recovery text that the UI shows for them.
import type { ServiceError } from "./contract";

export class ApiFailure extends Error {
  readonly code: string;
  readonly status: number | null;
  readonly field: string | null;
  readonly recovery: string | null;

  constructor(error: Partial<ServiceError> & { code: string; message: string }, status: number | null = null) {
    super(error.message);
    this.code = error.code;
    this.status = status;
    this.field = error.field ?? null;
    this.recovery = error.recovery ?? null;
  }
}

// UI text stays German (app/AGENTS.md).
const RECOVERY: Record<string, string> = {
  UPLOAD_TOO_LARGE: "Datei verkleinern oder nur die Zeichnungsseite als PDF hochladen.",
  UNSUPPORTED_MEDIA_TYPE: "Nur PDF-Zeichnungen hochladen.",
  PROCESSING_FAILED: "Datei prüfen (PDF: eine Seite, nicht gedreht) und erneut hochladen.",
  NETWORK_ERROR: "Verbindung zum Server prüfen und erneut versuchen.",
  UPLOAD_ABORTED: "Upload erneut starten.",
  NOT_FOUND: "Die Kennung ist unbekannt oder abgelaufen. Zurück zur Übersicht.",
  REVISION_CONFLICT: "Ein neuerer Stand liegt vor. Ansicht neu laden und die Änderung erneut eintragen.",
  CAPABILITY_UNAVAILABLE: "Diese Funktion bietet der verbundene Dienst noch nicht an.",
  INVALID_PARAMETER: "Wert prüfen: Zahl im zulässigen Bereich eingeben.",
};

/** Recovery text for an error: from the service if it supplies one, else from the code. */
export function recoveryFor(error: unknown): string {
  if (error instanceof ApiFailure) return error.recovery ?? RECOVERY[error.code] ?? "Erneut versuchen.";
  return "Erneut versuchen.";
}

export function errorCode(error: unknown): string {
  return error instanceof ApiFailure ? error.code : "UNKNOWN";
}

export const unavailable = (what: string) =>
  new ApiFailure({ code: "CAPABILITY_UNAVAILABLE", message: `${what} ist im verbundenen Dienst nicht verfügbar.` });

export const notFound = (what: string, id: string) =>
  new ApiFailure({ code: "NOT_FOUND", message: `${what} „${id}“ nicht gefunden.` }, 404);
