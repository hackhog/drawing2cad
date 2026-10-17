// Server rendering verifies the error text without a browser or a live service.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { SourceRow } from "../../pages/OverviewPage";
import { ApiFailure } from "../errors";
import type { Source } from "../contract";

vi.mock("@tanstack/react-router", () => ({ useNavigate: () => vi.fn() }));
vi.mock("../apiContext", () => ({ useApi: () => ({ deleteSource: vi.fn() }) }));

function renderRow(error: Error | null) {
  return renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient()}>
      <table><tbody><SourceRow source={source} analysis={undefined} error={error} /></tbody></table>
    </QueryClientProvider>,
  );
}

const source: Source = {
  source_id: "src_synthetic", filename: "synthetic.pdf", media_type: "application/pdf",
  byte_count: 100, sha256: "0".repeat(64), upload_state: "complete", created_at: "2026-01-01T00:00:00Z",
};

describe("overview analysis errors", () => {
  it("shows the message, stable code, and service recovery action", () => {
    const error = new ApiFailure({ code: "PDF_PREPARATION_FAILED", message: "PDF could not be prepared.", recovery: "Use PDF image tools." }, 422);
    const html = renderRow(error);
    expect(html).toContain('role="alert"');
    expect(html).toContain("Analyse fehlgeschlagen (PDF_PREPARATION_FAILED)");
    expect(html).toContain("PDF could not be prepared.");
    expect(html).toContain("Use PDF image tools.");
  });

  it("does not show an error while the analysis is loading", () => {
    const html = renderRow(null);
    expect(html).not.toContain('role="alert"');
    expect(html).not.toContain("Analyse fehlgeschlagen");
  });
});
