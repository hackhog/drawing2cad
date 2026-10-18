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
  UPLOAD_TOO_LARGE: "Make the file smaller or upload only the drawing page as PDF.",
  UNSUPPORTED_MEDIA_TYPE: "Upload PDF drawings only.",
  PROCESSING_FAILED: "Check the file (PDF: one page, not rotated) and upload it again.",
  NETWORK_ERROR: "Check the connection to the server and try again.",
  UPLOAD_ABORTED: "Start the upload again.",
  NOT_FOUND: "The ID is unknown or expired. Go back to the overview.",
  REVISION_CONFLICT: "A newer state exists. Reload the view and enter the change again.",
  RUN_ACTIVE: "Wait until the run has finished, then delete again.",
  CAPABILITY_UNAVAILABLE: "The connected service does not offer this function yet.",
  INVALID_PARAMETER: "Check the value: enter a number in the allowed range.",
};

/** Recovery text for an error: from the service if it supplies one, else from the code. */
export function recoveryFor(error: unknown): string {
  if (error instanceof ApiFailure) return error.recovery ?? RECOVERY[error.code] ?? "Try again.";
  return "Try again.";
}

export function errorCode(error: unknown): string {
  return error instanceof ApiFailure ? error.code : "UNKNOWN";
}

export const unavailable = (what: string) =>
  new ApiFailure({ code: "CAPABILITY_UNAVAILABLE", message: `${what} is not available in the connected service.` });

export const notFound = (what: string, id: string) =>
  new ApiFailure({ code: "NOT_FOUND", message: `${what} “${id}” not found.` }, 404);
