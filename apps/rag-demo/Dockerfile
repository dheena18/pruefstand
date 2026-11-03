# rag-demo image (T1.13 S5), built from the T0.3 template infra/docker/python-uv.Dockerfile.
# Build context = repository root:  docker build -f apps/rag-demo/Dockerfile --build-arg GIT_SHA="$(git rev-parse HEAD)" .
# Plain Dockerfile syntax only (the VM's docker has no buildx). The configs are copied next to the venv:
# RAG_CONFIG=/app/configs/rag.yaml (or /app/configs/bugs/<name>.yaml); tier 2: /app/configs/rag.gpu.yaml (or bugs/gpu/<name>.yaml).
FROM python:3.12-slim-bookworm@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337 AS base

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
COPY infra/gpu/models.yaml infra/gpu/models.yaml
RUN uv sync --frozen --no-dev --no-editable --package rag-demo
# T3.4 (DEV11-21): the embedding model's tokenizer.json, pinned by sha256 in the catalogue, baked at build time
# (the candidate has no internet at runtime); it only serves the truncated_chunks count.
RUN /app/.venv/bin/python -m rag_demo.index.fetch_tokenizer --catalogue infra/gpu/models.yaml --out /app/tokenizers/bge-m3.json
# T3.6 (AI13-05): the generator's own tokenizer.json (the id comes from rag.gpu.yaml, so a re-pin in the catalogue needs no
# change here), sha256 checked: a wrong pin fails the build. It counts the prompt budget; the bge-m3 one is never used for it.
RUN /app/.venv/bin/python -m rag_demo.index.fetch_tokenizer --catalogue infra/gpu/models.yaml --config apps/rag-demo/configs/rag.gpu.yaml --out /app/tokenizers/generator.json

FROM base AS runtime
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --home-dir /nonexistent app
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/apps/rag-demo/configs /app/configs
COPY --from=builder /app/tokenizers /app/tokenizers
# The model catalogue the gpu profile is validated against (T3.2, D221); ignored by the live profile.
COPY --from=builder /app/infra/gpu/models.yaml /app/catalogue/models.yaml
# GIT_SHA changes on every commit: declared after the expensive layers so it never invalidates them.
ARG GIT_SHA=unknown
LABEL org.opencontainers.image.source="https://github.com/dheena18/pruefstand" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.licenses="MIT"
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    GIT_SHA=${GIT_SHA} \
    RAG_CONFIG=/app/configs/rag.yaml \
    RAG_MODEL_CATALOGUE=/app/catalogue/models.yaml \
    RAG_EMBED_TOKENIZER=/app/tokenizers/bge-m3.json \
    RAG_GENERATOR_TOKENIZER=/app/tokenizers/generator.json
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/v1/health', timeout=2).status==200 else 1)"]
ENTRYPOINT ["uvicorn", "rag_demo.api:create_default_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
