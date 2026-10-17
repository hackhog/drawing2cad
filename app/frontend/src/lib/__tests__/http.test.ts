// Error mapping of the HTTP helpers that the web adapter uses.
import { afterEach, describe, expect, it, vi } from "vitest";
import { failure, request, uploadFile } from "../http";

/** Minimal XMLHttpRequest stub: `send` answers with the configured response on the next tick. */
function stubXhr(answer: { status: number; text?: string; network?: boolean }) {
  class FakeXhr {
    status = 0; statusText = ""; responseText = ""; responseType = "";
    upload: { onprogress: ((e: { lengthComputable: boolean; loaded: number; total: number }) => void) | null } = { onprogress: null };
    onload: (() => void) | null = null; onerror: (() => void) | null = null; onabort: (() => void) | null = null;
    open() {}
    send() {
      setTimeout(() => {
        if (answer.network) { this.onerror?.(); return; }
        this.upload.onprogress?.({ lengthComputable: true, loaded: 5, total: 10 });
        this.status = answer.status;
        this.responseText = answer.text ?? "";
        this.onload?.();
      });
    }
  }
  vi.stubGlobal("XMLHttpRequest", FakeXhr);
}

afterEach(() => vi.unstubAllGlobals());

const pdf = new File(["%PDF-1.7"], "a.pdf");

describe("failure", () => {
  it.each([[404, "NOT_FOUND"], [409, "REVISION_CONFLICT"], [413, "UPLOAD_TOO_LARGE"], [415, "UNSUPPORTED_MEDIA_TYPE"], [422, "PROCESSING_FAILED"]])(
    "maps status %i to %s", (status, code) => {
      expect(failure(status, JSON.stringify({ detail: "Text" }), "")).toMatchObject({ code, message: "Text", status });
    });

  it("keeps a structured service error", () => {
    const body = JSON.stringify({ detail: { code: "REVISION_CONFLICT", message: "neuer Stand", field: "expected_revision", recovery: "neu laden" } });
    expect(failure(409, body, "")).toMatchObject({ code: "REVISION_CONFLICT", field: "expected_revision", recovery: "neu laden" });
  });

  it("uses the status text for a body that is not JSON", () => {
    expect(failure(502, "<html>", "Bad Gateway")).toMatchObject({ code: "PROCESSING_FAILED", message: "Bad Gateway" });
  });
});

describe("uploadFile", () => {
  it("reports progress and returns the JSON body", async () => {
    stubXhr({ status: 200, text: '{"ok":true}' });
    const progress: number[] = [];
    await expect(uploadFile("/api/x", pdf, (f) => progress.push(f))).resolves.toEqual({ ok: true });
    expect(progress).toEqual([0.5, 1]);
  });

  it("rejects an error status with its code", async () => {
    stubXhr({ status: 415, text: '{"detail":"Keine PDF-Datei"}' });
    await expect(uploadFile("/api/x", pdf, () => {})).rejects.toMatchObject({ code: "UNSUPPORTED_MEDIA_TYPE", message: "Keine PDF-Datei" });
  });

  it("rejects a 2xx answer that is not JSON instead of staying pending", async () => {
    stubXhr({ status: 200, text: "<!doctype html>" });
    await expect(uploadFile("/api/x", pdf, () => {})).rejects.toMatchObject({ code: "PROCESSING_FAILED" });
  });

  it("reports an unreachable server as NETWORK_ERROR", async () => {
    stubXhr({ status: 0, network: true });
    await expect(uploadFile("/api/x", pdf, () => {})).rejects.toMatchObject({ code: "NETWORK_ERROR" });
  });
});

describe("request", () => {
  const respond = (status: number, body: string) =>
    vi.stubGlobal("fetch", vi.fn(async () => new Response(status === 204 ? null : body, { status })));

  it("returns JSON and nothing for 204", async () => {
    respond(200, '{"a":1}');
    await expect(request("/api/x")).resolves.toEqual({ a: 1 });
    respond(204, "");
    await expect(request("/api/x", { method: "DELETE" })).resolves.toBeUndefined();
  });

  it("maps a missing model endpoint to CAPABILITY_UNAVAILABLE", async () => {
    respond(503, JSON.stringify({ detail: { code: "CAPABILITY_UNAVAILABLE", message: "Kein Modell-Endpunkt", field: null, recovery: ".env" } }));
    await expect(request("/api/sources/s/runs", { method: "POST" })).rejects.toMatchObject({ code: "CAPABILITY_UNAVAILABLE", recovery: ".env" });
  });
});
