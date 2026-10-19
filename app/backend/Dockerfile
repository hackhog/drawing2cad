# Web backend (ADR 0012, ADR 0018): one shared domain service for the web API and its MCP endpoint.
# Agent runs build models only through that endpoint and its restricted build123d worker.
# Use the repository root as the build context for the MCP path dependency.
#   docker compose build   or   docker build -f app/backend/Dockerfile .
FROM python:3.12-slim

# Poetry has its own environment, separate from the application environment.
# Use the same Poetry version as the CI workflows.
ARG POETRY_VERSION=2.4.1
RUN python -m venv /opt/poetry \
    && /opt/poetry/bin/pip install --no-cache-dir "poetry==${POETRY_VERSION}" \
    && ln -s /opt/poetry/bin/poetry /usr/local/bin/poetry

RUN apt-get update \
    && apt-get install -y --no-install-recommends poppler-utils libseccomp2 libgl1 libglu1-mesa libxrender1 libxext6 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

ENV POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_CACHE_DIR=/tmp/poetry-cache \
    PYTHONUNBUFFERED=1

WORKDIR /src
COPY drawing2cad-mcp/ drawing2cad-mcp/
COPY app/backend/ app/backend/
# The agent receives the complete maintained skill (SKILL.md and all references) as its work instruction.
COPY skills/drawing2cad/SKILL.md skills/drawing2cad/SKILL.md
COPY skills/drawing2cad/references/ skills/drawing2cad/references/

WORKDIR /src/app/backend
# Install the locked runtime dependencies without the dev group. Poetry installs the MCP path
# dependency from a built wheel (develop = false). Install the backend package from a wheel too.
RUN poetry install --only main --no-root --compile \
    && poetry build --format wheel --output /tmp/dist \
    && .venv/bin/python -m pip install --no-cache-dir --no-deps /tmp/dist/*.whl \
    && rm -rf /tmp/dist /tmp/poetry-cache \
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
