# Reusable hardened template for Pruefstand Python images (T0.3, CLAUDE.md section 8, docs/engineering/docker.md).
# Plain Dockerfile syntax only, so it also builds without BuildKit (the VM's docker has no buildx).
# Build context = repository root. Per image set PKG (uv workspace member name), ENTRYPOINT_BIN and,
# if the service listens, HEALTHCHECK_CMD. Smoke image: --build-arg PKG=pruefstand (the defaults).
#   docker build -f infra/docker/python-uv.Dockerfile --build-arg GIT_SHA="$(git rev-parse HEAD)" -t pruefstand-smoke .
FROM python:3.12-slim-bookworm@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337 AS base

FROM ghcr.io/astral-sh/uv:0.13.6@sha256:af22a52f5eafef3d78e551599d405c02df61919d18028f0cea8eda93bc9986d0 AS uv

FROM base AS builder
ARG PKG=pruefstand
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_NO_CACHE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/local/bin/python \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages packages
COPY apps apps
RUN uv sync --frozen --no-dev --no-editable --package "${PKG}"

FROM base AS runtime
# Name of the console script in /app/.venv/bin (may be a command line such as "uvicorn app:app"); extra
# arguments given to `docker run` are appended.
ARG ENTRYPOINT_BIN=pruefstand
# Shell command that exits 0 when the service is healthy. NONE (default) = placeholder for images with no
# service to probe (CLI/Action images): the HEALTHCHECK then always passes; the image does not claim a check.
ARG HEALTHCHECK_CMD=NONE
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --home-dir /nonexistent app
COPY --from=builder /app/.venv /app/.venv
# GIT_SHA changes on every commit: declared after the expensive layers so it never invalidates them.
ARG GIT_SHA=unknown
LABEL org.opencontainers.image.source="https://github.com/dheena18/pruefstand" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.licenses="MIT"
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    GIT_SHA=${GIT_SHA} \
    ENTRYPOINT_BIN=${ENTRYPOINT_BIN} \
    HEALTHCHECK_CMD=${HEALTHCHECK_CMD}
USER 10001
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
    CMD [ "$HEALTHCHECK_CMD" = "NONE" ] || sh -c "$HEALTHCHECK_CMD"
ENTRYPOINT ["/bin/sh", "-c", "exec $ENTRYPOINT_BIN \"$@\"", "--"]
