import type { ArtifactRole } from "./contract";

export const ARTIFACT_LABEL: Record<ArtifactRole, string> = {
  drawing_pdf: "Technical drawing (PDF)", drawing_diagnostic: "Drawing diagnostic (PDF)", drawing_dxf: "Technical drawing (DXF)", step: "3D model (STEP)",
  step_candidate: "Candidate 3D model (STEP)",
  part_description: "Part description (JSON)", manifest: "Run manifest", trace: "MCP trace",
  events: "Domain events", report: "Review report (JSON)",
  verification_report: "Drawing verification report (JSON)", verification_preview: "Drawing verification preview (PNG)",
  projection_report: "Source projection report (JSON)", projection_overlay: "Source projection overlay (PNG)",
};
