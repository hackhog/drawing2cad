# Demo backend (ADR 0012): the API uses the shared MCP PDF service.
# Use the repository root as the build context for the MCP path dependency.
#   docker compose build   or   docker build -f app/backend/Dockerfile .
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.1 /uv /usr/local/bin/uv

RUN apt-get update \
    && apt-get install -y --no-install-recommends poppler-utils \
    && rm -rf /var/lib/apt/lists/*

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1

WORKDIR /src
COPY drawing2cad-mcp/ drawing2cad-mcp/
COPY app/backend/ app/backend/

WORKDIR /src/app/backend
RUN uv sync --locked --no-dev --no-editable \
    && useradd --system --uid 10001 --no-create-home demo

USER demo
ENV PATH="/src/app/backend/.venv/bin:$PATH" \
    HOST=0.0.0.0 \
    PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')"

CMD ["drawing-demo"]
