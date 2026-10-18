# Architecture decision records

Format: Michael Nygard. One file per decision. A replaced decision stays in the list and links to the decision that replaces it.

| ADR | Decision |
|---|---|
| [0003](0003-vector-extractor-as-fact-base.md) | Deterministic vector extractor as the fact base of drawing analysis |
| [0004](0004-text-by-glyph-templates.md) | Read text by glyph templates instead of OCR or a vision model |
| [0006](0006-demo-as-one-container-docker-compose.md) | Demo app as one container, local with Docker Compose, Azure optional. Part "one container" superseded by [0012](0012-demo-app-as-frontend-and-backend-container.md) |
| [0007](0007-demo-ui-guided-sequence-and-batch-upload.md) | Demo UI: guided sequence and batch upload |
| [0008](0008-demo-ui-light-dashboard.md) | Demo UI: light dashboard with overview page, guided sequence kept |
| [0009](0009-drawing-extract-as-mcp-tool.md) | Vector extractor as the MCP tool `drawing_extract` |
| [0010](0010-demo-ui-in-react-with-3d-viewer.md) | Demo UI in React with a 3D viewer, STEP to GLB on the server |
| [0011](0011-diagrams-in-readme-checked-by-ci.md) | Architecture diagram from a versioned source, as an image in the README, checked by CI |
| [0012](0012-demo-app-as-frontend-and-backend-container.md) | Demo app as a frontend container (nginx) and a backend container (FastAPI) |
| [0013](0013-vector-analysis-in-mcp.md) | Keep vector analysis in the MCP; remove the standalone extractor package and CLI |
| [0014](0014-headless-build123d-metric-prototype.md) | Headless build123d prototype, sandbox boundary, staged delivery, and challenge acceptance |
| [0015](0015-web-ui-on-tanstack-shadcn-with-service-adapter.md) | Web UI on TanStack Router, TanStack Query, and shadcn, with a replaceable service adapter |
| [0016](0016-shared-domain-service-and-drawing-delivery.md) | Shared domain services, persistent uploads and jobs, DXF/PDF drawing delivery, and current-review release gates |
| [0017](0017-ap242-application-construction-and-pmi.md) | Bounded AP242 construction adapter and nominal PMI |
| [0018](0018-agent-runner-in-the-web-backend.md) | Agent runner in the web backend on the shared domain service |
| [0019](0019-review-flag-decisions-in-the-domain-service.md) | Review flags and user decisions in the domain service, with a feedback export |
| [0020](0020-agent-model-profiles-selected-in-the-web-ui.md) | Agent model profiles from the server environment and the web UI, with server-side keys |
| [0021](0021-review-measurements-for-benefit-figures.md) | Review measurements in the web backend for the benefit figures |
| [0022](0022-ui-text-in-english.md) | UI text in English |
| [0023](0023-markdown-reader-for-run-notes.md) | Markdown reader for run notes |

The numbers come from the first local work. Numbers 0001, 0002 and 0005 are local tool or open team decisions and are not in this repository.
