# Targets of the rag-demo retriever (T3.5). Included by the root Makefile (-include mk/*.mk).
.PHONY: cassettes-rerank

# Re-records tests/cassettes/rerank_622.yaml from the REAL rerank-cpu (bge-reranker-v2-m3 on the VM CPU, no auth).
# Needs a running rerank-cpu: make up PROFILES="gpu dev" SERVICES=rerank-cpu  (dev port 18201 via PORT_OFFSET, docker.mk).
cassettes-rerank:
	RAG_RECORD=1 RECORD_RERANK_URL=http://127.0.0.1:$(RERANK_HOST_PORT) \
	    uv run pytest apps/rag-demo/tests/live/test_record.py -k rerank --record-mode=rewrite -m live
