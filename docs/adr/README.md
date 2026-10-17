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

The numbers come from the first local work. Numbers 0001, 0002 and 0005 are local tool or open team decisions and are not in this repository.
