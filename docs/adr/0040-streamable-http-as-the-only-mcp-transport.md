# 40. Use Streamable HTTP as the only MCP transport

Date: 2026-10-24

## Status

Accepted. Replaces the MCP transport decisions in [ADR 0009](0009-drawing-extract-as-mcp-tool.md),
[ADR 0013](0013-vector-analysis-in-mcp.md), [ADR 0014](0014-headless-build123d-metric-prototype.md),
[ADR 0016](0016-shared-domain-service-and-drawing-delivery.md),
[ADR 0027](0027-container-images-on-ghcr-for-version-tags.md), and
[ADR 0035](0035-shared-runtime-base-for-the-mcp-and-backend-images.md).
Their other decisions and historical test evidence remain unchanged.

## Context

The standalone MCP server supported stdio and Streamable HTTP. The web backend and its agent runner already used HTTP.
Two transports required separate start paths, client plans, Compose services, tests, and instructions.
The stdio default also selected a different path from the deployed web runner.

The HTTP endpoint can accept network requests. It must require a bearer token before startup.
The Compose deployment must publish its host port on loopback only. The CAD worker retains its verified sandbox and limits.

## Decision

- Streamable HTTP is the only MCP transport and the default server setting. The server rejects a stdio CLI option or configuration value with a clear error.
- The server requires the configured bearer token for every listener, including loopback. It rejects a missing or invalid token before serving requests.
- The standalone Compose service is `mcp-http`. It publishes the container listener on host `127.0.0.1:8765` and retains the existing resource and worker restrictions. The stdio Compose service is removed.
- CLI evaluation plans name an HTTP URL and a token environment variable. They do not contain a token value or a process command. The clients send the token through the HTTP Authorization header.
- The local-path development profile and the domain profile remain separate. This decision does not change their tool contracts or source rules.
- A full client-to-server HTTP test verifies the native tools. Authentication tests verify rejection of missing and incorrect tokens.

The Docker build target and published image keep the name `mcp`. The name identifies an image, not a transport.

## Consequences

An HTTP client connects to a running service. The client does not start a server subprocess.
Operators supply the token to the server and client through their environment or secret mechanism.
The token must not appear in a plan, trace, log, or error message.
The host port stays on loopback. A remote deployment needs a defined network boundary and permitted Host header.
The bearer token does not establish a separate principal for each client.

This transport decision does not change part construction, STEP validation, drawing delivery, or their acceptance gates.
