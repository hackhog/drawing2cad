# Headless MCP runtime. Use the repository root as the build context.
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

FROM python:3.12.15-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 AS runtime
COPY --from=ghcr.io/astral-sh/uv:0.11.1 /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils libseccomp2 libstdc++6 libgl1 libglu1-mesa libxrender1 libxext6 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
COPY --from=stepcode-build /build/bin/reader_sdai_ap242 /usr/local/bin/drawing2cad-stepcode
COPY --from=stepcode-build /stepcode/COPYING /stepcode/AUTHORS /stepcode/INTENT.md /usr/local/share/licenses/stepcode/
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv UV_PYTHON_DOWNLOADS=never \
    PATH=/opt/venv/bin:$PATH
WORKDIR /opt/drawing2cad-mcp
COPY drawing2cad-mcp/pyproject.toml drawing2cad-mcp/uv.lock ./
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
