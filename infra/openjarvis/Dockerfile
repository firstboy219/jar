# OpenJarvis for the Fase 2 spike (ADR-043): a separate worker behind jarvis-core (started by infra/spike/spike.sh).
# Built from the commit the blueprint tested (40092da). Differs from upstream's deploy/docker/Dockerfile:
#   - Rust 1.89 (upstream's image pins 1.88, but uuid 1.27 in the workspace needs 1.89 — the build fails)
#   - no frontend stage (the worker role needs no GUI)
FROM python:3.12-slim-bookworm AS builder
ARG OPENJARVIS_COMMIT=40092da
RUN apt-get update && apt-get install -y --no-install-recommends build-essential ca-certificates curl git && \
    rm -rf /var/lib/apt/lists/*
ENV PATH="/root/.cargo/bin:${PATH}"
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal --default-toolchain 1.89
WORKDIR /app
RUN git clone https://github.com/open-jarvis/openjarvis.git . && git checkout ${OPENJARVIS_COMMIT}
RUN pip install --no-cache-dir uv && \
    uv export --frozen --no-dev --extra server --no-emit-project > requirements.txt && \
    uv pip install --system --no-deps -r requirements.txt && \
    uv pip install --system --no-deps "maturin>=1.12.6,<2"
RUN SETUPTOOLS_SCM_PRETEND_VERSION=1.0.4 uv pip install --system --no-deps . && \
    RUSTUP_TOOLCHAIN=1.89 maturin build --release --manifest-path rust/crates/openjarvis-python/Cargo.toml \
        --interpreter python3 --out /tmp/wheel && \
    uv pip install --system --no-deps /tmp/wheel/*.whl && \
    python3 -c "import openjarvis_rust; print('openjarvis_rust ok')" && \
    rm -rf /tmp/wheel rust .git

FROM python:3.12-slim-bookworm
COPY --from=builder /usr/local /usr/local
COPY --from=builder /app /app
COPY entrypoint.sh /entrypoint.sh
WORKDIR /app
RUN groupadd --system --gid 1000 jarvis && useradd --system --uid 1000 --gid jarvis --create-home --home-dir /home/oj jarvis
ENV HOME=/home/oj
USER jarvis
ENTRYPOINT ["/entrypoint.sh"]
