# 6. Demo app as one container, local with Docker Compose, Azure optional

Date: 2026-10-16

## Status

Accepted (local part done on 2026-10-16, `app/`). The part "one container" is superseded by
[ADR 0012](0012-demo-app-as-frontend-and-backend-container.md) (frontend and backend container).

## Context

For the pitch (Solution & Demo = 17.5 % of the total score), we need a user interface: upload a drawing PDF,
see the result of the extractor (overlay, read dimensions, review flags), and later the 3D model.

Constraints:

- The challenge requires that the MCP server runs fully locally, for example as a Docker container, without cloud dependencies.
- An AI that builds the repository gives 50 % of the score. Build errors cost points. The repository must build on a new
  computer without manual work, keys, or accounts.
- Optionally, the same demo runs in Azure (sandbox subscription, GitHub login) as a fallback for the pitch.
- Development computer: OrbStack (Docker Engine and Compose v5; Kubernetes is available, but not configured).

Compared options:

- **A:** one app container (FastAPI serves UI and API), local with `docker compose up`, the same image in Azure Container Apps with Easy Auth.
- **B:** Static Web App as frontend, API as Container App (linked backend).

## Decision

Option A. The demo app is one Python container (FastAPI). It serves UI and API and uses the extractor as a library.
Locally, `docker compose up` starts everything. We do not use Kubernetes.

The MCP server can be added as a second Compose service. Azure (Container Apps, Easy Auth with GitHub, allowlist) comes only
after the local version works. Azure is never necessary for build or tests.

## Consequences

**Positive:**
- One command to build and start, without an account or a key. This agrees with the jury build criterion and the local-first requirement.
- The same image runs locally and in Azure. There is no second code path.
- Compose services map directly to Azure Container Apps.

**Negative / trade-offs:**
- The UI has no frontend build chain (static HTML/JS). For a larger product, a framework would be easier.
- No autoscaling or self-healing as in Kubernetes. A demo with few users does not need this.

**Neutral:**
- Uploaded PDFs are only processed, not saved.

## Considered alternatives

| Option | Assessment |
|---|---|
| Kubernetes (OrbStack k8s, manifests/Helm) | Only overhead for two containers: manifests, ingress, a cluster on the jury computer. The challenge names Docker. Container Apps does not need k8s manifests |
| B: Static Web App + container backend | Two deployments, SWA Standard for the linked backend, SWA CLI locally. No advantage for a prototype |
| Frontend with a Node build (React/Vite) | A second toolchain and lockfile, more possible build errors. Can be added later if necessary |
