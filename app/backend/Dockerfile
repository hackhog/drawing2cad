# Web backend (ADR 0012, ADR 0018): one shared domain service for the web API and its MCP endpoint.
# Agent runs build models only through that endpoint and its restricted build123d worker.
# Use the repository root as the build context for the MCP path dependency.
#   docker compose build   or   docker build -f app/backend/Dockerfile .
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.1 /uv /usr/local/bin/uv

RUN apt-get update \
    && apt-get install -y --no-install-recommends poppler-utils libseccomp2 libgl1 libglu1-mesa libxrender1 libxext6 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1

WORKDIR /src
COPY drawing2cad-mcp/ drawing2cad-mcp/
COPY app/backend/ app/backend/
# The agent receives the maintained skill as its work instruction.
COPY skills/drawing2cad/SKILL.md skills/drawing2cad/SKILL.md

WORKDIR /src/app/backend
RUN uv sync --locked --no-dev --no-editable \
    && useradd --system --uid 10001 --no-create-home demo \
    && mkdir /data && chown demo:demo /data

USER demo
ENV PATH="/src/app/backend/.venv/bin:$PATH" \
    HOST=0.0.0.0 \
    PORT=8000 \
    DRAWING2CAD_DATA_DIR=/data \
    DRAWING2CAD_SKILL_PATH=/src/skills/drawing2cad/SKILL.md \
    OPENBLAS_NUM_THREADS=1 \
    OMP_NUM_THREADS=1
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')"

CMD ["drawing-demo"]
