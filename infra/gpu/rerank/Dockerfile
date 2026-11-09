# rerank-cpu (T3.1a S5): TEI-compatible POST /rerank for BAAI/bge-reranker-v2-m3 on the VM CPU. No auth, no secrets (D217).
# Build context = infra/gpu/rerank:  docker build -t pruefstand-rerank-cpu infra/gpu/rerank
# Plain Dockerfile syntax only (the VM's docker has no buildx). The model weights are downloaded at the pinned
# revision into the VM-local volume mounted at /models (HF_HOME), never baked into the image.
FROM python:3.15-slim-bookworm@sha256:96599df822d0e1c6bb700014a05c7f3c8cabc6e0f7ff3c4f9f69cee033b4b5d9 AS base

FROM ghcr.io/astral-sh/uv:0.13.7@sha256:96f40d3904aad8d0bd010539001d36c8e2188b981e1334471a90c4a1d93bb490 AS uv

FROM base AS builder
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_NO_CACHE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY requirements.txt ./
RUN uv venv /app/.venv --python /usr/local/bin/python \
    && uv pip install --python /app/.venv/bin/python \
        --require-hashes \
        --index-strategy unsafe-best-match \
        --index-url https://pypi.org/simple \
        --extra-index-url https://download.pytorch.org/whl/cpu \
        -r requirements.txt

FROM base AS runtime
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --home-dir /nonexistent app \
    && mkdir -p /models \
    && chown app:app /models
COPY --from=builder /app/.venv /app/.venv
COPY rerank_app.py /app/rerank_app.py
# GIT_SHA changes on every commit: declared after the expensive layers so it never invalidates them.
ARG GIT_SHA=unknown
LABEL org.opencontainers.image.source="https://github.com/dheena18/pruefstand" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.licenses="MIT"
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/models \
    RERANK_PORT=8201 \
    RERANK_MODEL=BAAI/bge-reranker-v2-m3 \
    RERANK_REVISION=953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e \
    RERANK_WEIGHTS_SHA256=d9e3e081faff1eefb84019509b2f5558fd74c1a05a2c7db22f74174fcedb5286
WORKDIR /app
USER 10001
EXPOSE 8201
HEALTHCHECK --interval=10s --timeout=3s --start-period=180s --retries=5 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8201/health', timeout=2).status==200 else 1)"]
ENTRYPOINT ["python", "/app/rerank_app.py"]
