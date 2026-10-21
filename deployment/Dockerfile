# Images of drawing2cad (ADR 0035). Use the repository root as the build context.
#   docker build -f deployment/Dockerfile --target mcp      -t drawing2cad-mcp:local .
#   docker build -f deployment/Dockerfile --target mcp-test -t drawing2cad-mcp:test .
#   docker build -f deployment/Dockerfile --target backend  -t drawing2cad-backend:local .
# The stage "runtime" is the one definition of the system tools of the domain core and its restricted worker.
# The MCP image and the backend image both start from it. They differ only in their application layer, user, entry point, and data volume.
# The MCP image does not contain the backend. The backend and the web UI are optional components.

FROM python:3.12.15-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 AS stepcode-build
RUN apt-get update && apt-get install -y --no-install-recommends g++ cmake make \
    && rm -rf /var/lib/apt/lists/*
ADD --checksum=sha256:8fec5d2d3899dfd9de70adc8c0b7e779a75032368087819a8572aabc59ec0ff1 https://codeload.github.com/stepcode/stepcode/tar.gz/24783b448511b8f6bce2829286a3f00015430236 /tmp/stepcode.tar.gz
RUN mkdir /stepcode && tar -xzf /tmp/stepcode.tar.gz --strip-components=1 -C /stepcode \
    && rm /tmp/stepcode.tar.gz
RUN cmake -S /stepcode -B /build -DSC_BUILD_SCHEMAS=/stepcode/data/ap242 \
    -DSC_EXP2CXX_API_VERSION=2 -DBUILD_SHARED_LIBS=OFF -DBUILD_STATIC_LIBS=ON \
    -DCMAKE_BUILD_TYPE=Release \
    && cmake --build /build --target sdai_ap242-static --parallel 2
COPY drawing2cad-mcp/external/stepcode/reader.cc /reader.cc
RUN cmake -S /stepcode -B /build -DSC_SDAI_ADDITIONAL_EXES_SRCS=/reader.cc \
    && cmake --build /build --target reader_sdai_ap242 --parallel 2

# The shared system runtime: Python, Poetry, the system packages of the CAD worker, Poppler, Tesseract with eng and deu,
# and the independent STEPcode reader. Add a system tool of the domain core here, and only here.
FROM python:3.12.15-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 AS runtime
# Poetry has its own environment, separate from the application environments. Use the same Poetry version as the CI workflows.
ARG POETRY_VERSION=2.4.1
RUN python -m venv /opt/poetry \
    && /opt/poetry/bin/pip install --no-cache-dir "poetry==${POETRY_VERSION}" \
    && ln -s /opt/poetry/bin/poetry /usr/local/bin/poetry
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils libseccomp2 libstdc++6 libgl1 libglu1-mesa libxrender1 libxext6 fonts-dejavu-core \
    libtesseract5 tesseract-ocr-eng tesseract-ocr-deu \
    && rm -rf /var/lib/apt/lists/*
COPY --from=stepcode-build /build/bin/reader_sdai_ap242 /usr/local/bin/drawing2cad-stepcode
COPY --from=stepcode-build /stepcode/COPYING /stepcode/AUTHORS /stepcode/INTENT.md /usr/local/share/licenses/stepcode/
# A process in an image of this runtime refuses to start when a system tool is missing (drawing2cad_mcp.runtime_tools).
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
    POETRY_NO_INTERACTION=1 POETRY_CACHE_DIR=/tmp/poetry-cache \
    DRAWING2CAD_REQUIRE_RUNTIME_TOOLS=1

# The MCP server: the domain core with its own entry point and data volume. It does not need the backend.
FROM runtime AS mcp-base
RUN python -m venv /opt/venv
ENV VIRTUAL_ENV=/opt/venv PATH=/opt/venv/bin:$PATH
WORKDIR /opt/drawing2cad-mcp
# Poetry installs into the active environment (VIRTUAL_ENV=/opt/venv).
COPY drawing2cad-mcp/pyproject.toml drawing2cad-mcp/poetry.lock ./
RUN poetry install --only main --extras cad --no-root && rm -rf /tmp/poetry-cache
COPY drawing2cad-mcp /opt/drawing2cad-mcp
# Install the package from a wheel, not as a link to the source directory. Stop the build when a system tool is missing.
RUN poetry build --format wheel --output /tmp/dist \
    && pip install --no-cache-dir --no-deps /tmp/dist/*.whl \
    && rm -rf /tmp/dist \
    && python -m drawing2cad_mcp.runtime_tools \
    && useradd --system --uid 10001 --no-create-home cad \
    && mkdir /data /inputs && chown cad:cad /data
COPY drawing2cad-mcp/docker.toml /etc/drawing2cad.toml
USER cad
WORKDIR /data
ENTRYPOINT ["drawing2cad-mcp", "--config", "/etc/drawing2cad.toml"]

FROM mcp-base AS mcp-test
USER root
RUN cd /opt/drawing2cad-mcp && poetry install --only main --extras "cad test" --no-root \
    && rm -rf /tmp/poetry-cache
USER cad
ENTRYPOINT ["python", "-m", "pytest"]

FROM mcp-base AS mcp

# The web backend (ADR 0012, ADR 0018): the web API and its MCP endpoint on one shared domain service.
# Agent runs build models only through that endpoint and its restricted build123d worker.
FROM runtime AS backend
ENV POETRY_VIRTUALENVS_IN_PROJECT=true
WORKDIR /src
COPY drawing2cad-mcp/ drawing2cad-mcp/
COPY app/backend/ app/backend/
# The agent receives the complete maintained skill (SKILL.md and all references) as its work instruction.
COPY skills/drawing2cad/SKILL.md skills/drawing2cad/SKILL.md
COPY skills/drawing2cad/references/ skills/drawing2cad/references/
WORKDIR /src/app/backend
# Install the locked runtime dependencies without the dev group. Poetry installs the MCP path dependency from a built wheel
# (develop = false). Install the backend package from a wheel too. Stop the build when a system tool is missing.
RUN poetry install --only main --no-root --compile \
    && poetry build --format wheel --output /tmp/dist \
    && .venv/bin/python -m pip install --no-cache-dir --no-deps /tmp/dist/*.whl \
    && rm -rf /tmp/dist /tmp/poetry-cache \
    && .venv/bin/python -m drawing2cad_mcp.runtime_tools \
    && useradd --system --uid 10001 --no-create-home demo \
    && mkdir /data && chown demo:demo /data
USER demo
ENV PATH="/src/app/backend/.venv/bin:$PATH" \
    HOST=0.0.0.0 \
    PORT=8000 \
    DRAWING2CAD_DATA_DIR=/data \
    DRAWING2CAD_SKILL_PATH=/src/skills/drawing2cad/SKILL.md
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')"
CMD ["drawing-demo"]
