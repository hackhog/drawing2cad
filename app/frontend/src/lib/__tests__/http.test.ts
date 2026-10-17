// Error mapping of the legacy HTTP endpoints to stable codes.
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiFailure } from "../errors";
import { getJson } from "../http";

afterEach(() => vi.unstubAllGlobals());

const respond = (status: number, body: unknown) =>
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(body), { status })));

describe("getJson", () => {
  it.each([[404, "NOT_FOUND"], [409, "REVISION_CONFLICT"], [413, "UPLOAD_TOO_LARGE"], [415, "UNSUPPORTED_MEDIA_TYPE"], [422, "PROCESSING_FAILED"]])(
    "maps status %i to %s", async (status, code) => {
      respond(status, { detail: "Text" });
      await expect(getJson("api/x")).rejects.toMatchObject({ code, message: "Text", status });
    });

  it("keeps a structured service error", async () => {
    respond(409, { detail: { code: "REVISION_CONFLICT", message: "neuer Stand", field: "expected_revision", recovery: "neu laden" } });
    const err = await getJson("api/x").catch((e: ApiFailure) => e);
    expect(err).toMatchObject({ code: "REVISION_CONFLICT", field: "expected_revision", recovery: "neu laden" });
  });

  it("reports an unreachable server as NETWORK_ERROR", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("failed"); }));
    await expect(getJson("api/x")).rejects.toMatchObject({ code: "NETWORK_ERROR" });
  });
});
