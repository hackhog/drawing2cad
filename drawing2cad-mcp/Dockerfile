# M1: the complete headless MCP runtime. Use the repository root as build context.
FROM python:3.12.15-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 AS runtime
COPY --from=ghcr.io/astral-sh/uv:0.11.1 /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils libseccomp2 libgl1 libglu1-mesa libxrender1 libxext6 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv UV_PYTHON_DOWNLOADS=never \
    PATH=/opt/venv/bin:$PATH
WORKDIR /opt/drawing2cad-mcp
COPY drawing2cad-mcp/pyproject.toml drawing2cad-mcp/uv.lock drawing2cad-mcp/README.md ./
RUN uv sync --locked --extra cad --no-dev --no-install-project
COPY drawing2cad-mcp /opt/drawing2cad-mcp
RUN uv sync --locked --extra cad --no-dev --no-editable \
    && useradd --system --uid 10001 --no-create-home cad \
    && mkdir /data /inputs && chown cad:cad /data
COPY drawing2cad-mcp/docker.toml /etc/drawing2cad.toml
USER cad
WORKDIR /data
ENTRYPOINT ["drawing2cad-mcp", "--config", "/etc/drawing2cad.toml"]

FROM runtime AS test
USER root
RUN cd /opt/drawing2cad-mcp && uv sync --locked --extra cad --extra test --no-dev --no-editable
USER cad
ENTRYPOINT ["python", "-m", "pytest"]

FROM runtime AS production
