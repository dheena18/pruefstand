# Prüfstand GitHub Action image (T1.12 S1), from the T0.3 template infra/docker/python-uv.Dockerfile.
# BUILD CONTEXT = the repository root, not action/:
#   docker build -f action/Dockerfile --build-arg GIT_SHA="$(git rev-parse HEAD)" -t pruefstand-action .
# GitHub builds `image: Dockerfile` of a `uses: ./action` step with action/ as the context, which cannot see
# packages/. Until T9.1b publishes the image and action.yml points at it, workflows build it from the root
# and run it with `docker run` (action-selftest.yml). Plain Dockerfile syntax only (no BuildKit needed).
FROM python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df AS base

FROM ghcr.io/astral-sh/uv:0.13.6@sha256:af22a52f5eafef3d78e551599d405c02df61919d18028f0cea8eda93bc9986d0 AS uv

FROM base AS builder
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
RUN uv sync --frozen --no-dev --no-editable --package pruefstand

FROM base AS runtime
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --home-dir /nonexistent app
COPY --from=builder /app/.venv /app/.venv
COPY action/entrypoint.py /app/action/entrypoint.py
# GIT_SHA changes on every commit: declared after the expensive layers so it never invalidates them.
ARG GIT_SHA=unknown
LABEL org.opencontainers.image.source="https://github.com/dheena18/pruefstand" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.licenses="MIT"
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    GIT_SHA=${GIT_SHA}
# One-shot container, not a service: there is nothing to probe.
HEALTHCHECK NONE
# The workspace mount must be writable for this uid; run with --user "$(id -u):$(id -g)" when it is not.
USER 10001
ENTRYPOINT ["python", "/app/action/entrypoint.py"]
