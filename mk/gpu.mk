# GPU serving targets (T3.1a; docs/engineering/gpu-cluster.md section 8, infra/gpu/README.md). Included by the root Makefile.
# Every target that touches the cluster or the models runs UNDER the single VM GPU lock: `pruefstand-lock <cmd>` (T0.7)
# takes /var/lib/pruefstand/gpu.lock once and exports PRUEFSTAND_LOCK_HELD=1; the scripts never take it themselves.
# A lock-taking target runs its script and then health.sh (the preflight) inside the same lock.
# Optional environment: OLLAMA_GPU0_URL, OLLAMA_GPU1_URL, CLUSTER_SSH_HOST, PRUEFSTAND_DATA_ROOT (see the README).
# Qdrant keeps its data under $PRUEFSTAND_HOME/qdrant in the gpu profile (R9-32); otherwise the named volume.
ifneq ($(filter gpu,$(PROFILES)),)
PRUEFSTAND_HOME ?= $(HOME)/pruefstand
export QDRANT_STORAGE := $(PRUEFSTAND_HOME)/qdrant
endif

.PHONY: gpu-up gpu-night-up gpu-down gpu-health gpu-repair gpu-deploy-bin gpu-pull gpu-rm test-gpu-locked

GPU_LOCK := pruefstand-lock
need_id = $(if $(ID),,$(error ID=<models.yaml id, e.g. ollama/bge-m3> is required))

# Day and night load the same set (ADR-0019); the names stay for logs and the night window.
gpu-up:
	$(GPU_LOCK) bash -c 'infra/gpu/switch-mode.sh day && infra/gpu/health.sh --mode day'

gpu-night-up:
	$(GPU_LOCK) bash -c 'infra/gpu/switch-mode.sh night && infra/gpu/health.sh --mode night'

# Unloads every resident catalogue model; the server keeps running (ADR-0018).
gpu-down:
	$(GPU_LOCK) infra/gpu/unload-all.sh

gpu-health:
	$(GPU_LOCK) infra/gpu/health.sh

gpu-repair:
	$(GPU_LOCK) infra/gpu/health.sh --repair

# Swap rule (ADR-0019): MAINTENANCE must exist for gpu-rm; gpu-pull stops with exit 17 when the disk is too full.
gpu-pull:
	$(need_id)
	$(GPU_LOCK) infra/gpu/fetch-model.sh $(ID)

gpu-rm:
	$(need_id)
	$(GPU_LOCK) infra/gpu/fetch-model.sh --rm $(ID)

# OWNER step (sudo): the cluster key belongs to user pruefstand, which cannot read the owner's checkout, so the
# scripts are copied to a world-readable temp dir first. No lock needed. DEPLOY_ARGS=--check only compares.
gpu-deploy-bin:
	d=$$(mktemp -d) && cp -r infra/gpu infra/cluster "$$d"/ && chmod -R a+rX "$$d" \
	  && { sudo -u pruefstand "$$d/gpu/deploy-cluster-bin.sh" $(DEPLOY_ARGS); rc=$$?; rm -rf "$$d"; exit $$rc; }

# The `gpu` smoke tests under the same lock (R11 D212, DEV11-20).
test-gpu-locked:
	$(GPU_LOCK) make test-gpu
