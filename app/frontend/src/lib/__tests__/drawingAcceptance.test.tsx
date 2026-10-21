// Server rendering verifies the acceptance text without a browser or a live service.
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ReviewPanel } from "../../components/run/ReviewPanel";
import type { DrawingAcceptance, Run } from "../contract";

function render(acceptance: DrawingAcceptance) {
  const run = {
    run_id: "run_synthetic", source_id: "src_synthetic", phase: "done", job: { status: "succeeded" }, error: null, artifacts: [],
    part: { revision: 1, parameters: [], operations: [], capabilities: { parameter_edit: false } }, agent_report: null,
    review: { release_state: "released", assumptions: [], uncertainties: [], validation: [], drawing: null, drawing_acceptance: acceptance },
  } as unknown as Run;
  return renderToStaticMarkup(<ReviewPanel run={run} />);
}

describe("drawing acceptance", () => {
  it("shows the blocking findings with their own status, never as a pass", () => {
    const html = render({
      status: "unverified", reason: "2 mandatory verification findings block the acceptance.",
      verification: { validity: "current", status: "fail", gate_passed: false, blocking_count: 2, reviewed_count: 0, blocking: [
        { rule_id: "MODEL-01", status: "fail", feature: "top", message: "Edges are missing." },
        { rule_id: "STYLE-02", status: "not_tested", feature: null, message: "Not run." },
      ] },
    });
    expect(html).toContain("not verified");
    expect(html).toContain("2 blocking findings");
    expect(html).toContain("MODEL-01");
    expect(html).toContain("not tested");
    expect(html).not.toContain("acceptance gate passed");
  });

  it("shows an outdated verification and the decisions of the review", () => {
    const html = render({
      status: "accepted", reason: null,
      verification: { validity: "current", status: "needs_review", gate_passed: true, blocking_count: 0, reviewed_count: 1, blocking: [] },
    });
    expect(html).toContain("accepted");
    expect(html).toContain("acceptance gate passed");
    expect(html).toContain("1 decided in review");
    const stale = render({ status: "unverified", reason: "The verification is stale.", verification: {
      validity: "stale", status: "pass", gate_passed: false, blocking_count: 0, reviewed_count: 0, blocking: [] } });
    expect(stale).toContain("outdated");
  });
});
