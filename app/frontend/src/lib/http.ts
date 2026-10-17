// HTTP helpers for relative /api paths. Upload uses XMLHttpRequest, because fetch does not report upload progress.
import { ApiFailure } from "./errors";

const CODE_BY_STATUS: Record<number, string> = {
  404: "NOT_FOUND",
  409: "REVISION_CONFLICT",
  413: "UPLOAD_TOO_LARGE",
  415: "UNSUPPORTED_MEDIA_TYPE",
  422: "PROCESSING_FAILED",
};

function failure(status: number, body: string, statusText: string): ApiFailure {
  let detail: unknown;
  try { detail = (JSON.parse(body) as { detail?: unknown }).detail; } catch { detail = undefined; }
  // A structured service error has a code; FastAPI errors have a text detail.
  if (detail && typeof detail === "object" && "code" in detail) {
    return new ApiFailure(detail as ApiFailure, status);
  }
  const message = typeof detail === "string" ? detail : statusText || `HTTP ${status}`;
  return new ApiFailure({ code: CODE_BY_STATUS[status] ?? "PROCESSING_FAILED", message }, status);
}

/** POST one file as multipart field `file`. `onProgress` receives the sent fraction from 0 to 1. */
export function uploadFile<T>(
  path: string, file: File, onProgress: (fraction: number) => void, responseType: "json" | "blob" = "json",
  signal?: AbortSignal,
): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", path);
    xhr.responseType = responseType === "blob" ? "blob" : "text";
    xhr.upload.onprogress = (evt) => { if (evt.lengthComputable) onProgress(evt.loaded / evt.total); };
    xhr.onload = async () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        onProgress(1);
        resolve(responseType === "blob" ? xhr.response : JSON.parse(xhr.responseText));
        return;
      }
      const body = responseType === "blob" ? await (xhr.response as Blob).text() : xhr.responseText;
      reject(failure(xhr.status, body, xhr.statusText));
    };
    xhr.onerror = () => reject(new ApiFailure({ code: "NETWORK_ERROR", message: "Server nicht erreichbar." }));
    xhr.onabort = () => reject(new ApiFailure({ code: "UPLOAD_ABORTED", message: "Upload abgebrochen." }));
    signal?.addEventListener("abort", () => xhr.abort(), { once: true });
    const body = new FormData();
    body.append("file", file);
    xhr.send(body);
  });
}

export async function getJson<T>(path: string): Promise<T> {
  let res: Response;
  try { res = await fetch(path); } catch {
    throw new ApiFailure({ code: "NETWORK_ERROR", message: "Server nicht erreichbar." });
  }
  if (!res.ok) throw failure(res.status, await res.text(), res.statusText);
  return res.json() as Promise<T>;
}

export async function sha256Hex(data: ArrayBuffer): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", data);
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}
