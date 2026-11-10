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

.PHONY: gpu-up gpu-night-up gpu-down gpu-health gpu-repair gpu-deploy-bin gpu-install-wrapper gpu-pull gpu-rm \
        test-gpu-locked

GPU_LOCK := pruefstand-lock
# The owner steps fetch this exact URL (not the `origin` remote, whose refspec could be remapped) and export FETCH_HEAD.
GPU_REPO_URL := https://github.com/dheena18/pruefstand
# Refuse a url.<base>.insteadOf rewrite: it could send the fetch of the exact URL below to another repository (D954).
GPU_NO_REWRITE = if git config --get-regexp '^url\..*\.insteadof$$' | grep -q .; then echo "refusing: a url.<base>.insteadOf rewrite is configured (git config --get-regexp 'url.*insteadof')" >&2; exit 1; fi
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

# OWNER steps (sudo). Both fetch `main` from the exact repository URL and export FETCH_HEAD with `git archive` and run THAT copy, never the working tree: an edited
# dev worktree must not be able to borrow sudo or the cluster key (M3). The cluster key belongs to user pruefstand, which
# cannot read the owner's checkout, hence the world-readable temp dir. No lock needed. DEPLOY_ARGS=--check only compares.
gpu-deploy-bin:
	$(GPU_NO_REWRITE); git fetch -q $(GPU_REPO_URL) main && d=$$(mktemp -d) && git archive FETCH_HEAD infra/gpu infra/cluster | tar -x -C "$$d" \
	  && git rev-parse FETCH_HEAD > "$$d/COMMIT" && chmod -R a+rX "$$d" \
	  && { sudo -u pruefstand "$$d/infra/gpu/deploy-cluster-bin.sh" $(DEPLOY_ARGS); rc=$$?; rm -rf "$$d"; exit $$rc; }

# Installs the pruefstand-cluster wrapper, its allow-list and the sudoers file from origin/main (INSTALL_ARGS=--replace).
gpu-install-wrapper:
	$(GPU_NO_REWRITE); git fetch -q $(GPU_REPO_URL) main && d=$$(mktemp -d) && git archive FETCH_HEAD infra/gpu infra/cluster | tar -x -C "$$d" \
	  && git rev-parse FETCH_HEAD > "$$d/COMMIT" && chmod -R a+rX "$$d" \
	  && { sudo "$$d/infra/gpu/install-cluster-wrapper.sh" $(INSTALL_ARGS); rc=$$?; rm -rf "$$d"; exit $$rc; }

# The `gpu` smoke tests under the same lock (R11 D212, DEV11-20).
test-gpu-locked:
	$(GPU_LOCK) make test-gpu
