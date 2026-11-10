# llm-proxy (T6.2a S4b): the candidate's only route to the one Ollama server (D206, D242, ADR-0018).
# Build context = infra/gate-executor/llm-proxy:  docker build -t pruefstand-llm-proxy infra/gate-executor/llm-proxy
# Stdlib only (no third-party packages); plain Dockerfile syntax (the VM's docker has no buildx). Built on the VM from the
# private executor checkout at the synced tag, never from a PR (T6.2a S10).
FROM python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df AS base

FROM base AS builder
WORKDIR /app
COPY llm_proxy.py llm_proxy_policy.py llm_proxy_json.py llm_proxy_server.py ./
RUN python -m py_compile llm_proxy.py llm_proxy_policy.py llm_proxy_json.py llm_proxy_server.py

FROM base AS runtime
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --home-dir /nonexistent app
COPY --from=builder /app/llm_proxy.py /app/llm_proxy_policy.py /app/llm_proxy_json.py \
    /app/llm_proxy_server.py /app/
ARG GIT_SHA=unknown
LABEL org.opencontainers.image.source="https://github.com/dheena18/pruefstand" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.licenses="MIT"
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LLM_PROXY_UPSTREAM=http://172.17.0.1:11434
WORKDIR /app
USER 10001
EXPOSE 11500
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:11500/health', timeout=2).status==200 else 1)"]
ENTRYPOINT ["python", "/app/llm_proxy.py"]
