# 27. Container images on ghcr.io for version tags

Date: 2026-10-19

## Status

The MCP transport and Compose service list below is replaced by [ADR 0040](0040-streamable-http-as-the-only-mcp-transport.md).
Accepted. Replaces the rule of [ADR 0010](0010-demo-ui-in-react-with-3d-viewer.md) and [ADR 0012](0012-demo-app-as-frontend-and-backend-container.md) that `docker compose up --build` is the only command to build and start.

## Context

Each user built the MCP, backend, and frontend images locally. The images were built at different times from different commits.
The backend image contains its own copy of the MCP package and the skill. A standalone MCP image from another commit can then have different tools and skill text.
No one could see which revision of an image runs.

## Decision

- Only a pushed version tag (`v<major>.<minor>` or `v<major>.<minor>.<patch>`) publishes container images. The workflow is `.github/workflows/release.yml`.
- The workflow publishes nothing if the tagged commit is not on `main`, or if the MCP test suite fails in its container.
- It builds `ghcr.io/hackhog/drawing2cad-mcp`, `drawing2cad-backend`, and `drawing2cad-frontend` from the tagged commit, for `linux/amd64` and `linux/arm64` on native runners.
- Each image has the tags `<version>` and `latest`, and the OCI labels for source, revision, version, and title.
- The `deployment/` directory has two Compose files with the same services: backend, frontend, `mcp` (stdio), and `mcp-http`. The MCP services use Compose profiles, so `up` starts only the web app.
- `deployment/compose.yaml` uses the published images. `DRAWING2CAD_VERSION` selects one version for all services. The default is `latest`.
- `deployment/compose.local.yaml` builds all containers from the current source. Its services extend `deployment/compose.yaml`, so the runtime settings stay the same. It uses local image tags, so a local build does not replace a published tag.
- Both files set the project name `drawing2cad`. The volumes of earlier installations stay in use.
- Pull request and `main` workflows still build images for tests. They do not push images.

## Consequences

- All images of one version come from the same commit. The `org.opencontainers.image.revision` label identifies it.
- `docker compose -f deployment/compose.yaml up` needs no local build and no credentials while the packages are public.
- Before the first tag after this change, `deployment/compose.yaml` cannot pull an image. Use `deployment/compose.local.yaml` until then.
- The Compose files are no longer in the repository root. Each command needs `-f deployment/<file>`.
- `latest` changes with each release. A deployment that must not change sets `DRAWING2CAD_VERSION`.
- A release takes longer, because the workflow runs the MCP test suite and builds six platform images.
- The package visibility on ghcr.io must be public for pulls without a login. A new package can start as private. An organization owner sets the visibility once.

## Alternatives considered

| Alternative | Reason for rejection |
|---|---|
| Build images on each push to `main` | Many images without a version. A user cannot select a tested state. |
| Keep local builds only | The images of one installation can come from different commits. |
| Build `linux/arm64` with QEMU emulation | The STEPcode and CAD dependency builds are slow in emulation. Native arm64 runners are available. |
