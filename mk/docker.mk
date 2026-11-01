# Docker / compose targets (T0.3). Included by the root Makefile (-include mk/*.mk).
# Compose has no arithmetic, so every published host port is exported here as default + PORT_OFFSET
# (D214, Y1.4): PORT_OFFSET unset or 0 = defaults (CI, laptops), 10000 = the owner's dev stack on the VM.
# Prefer `make up` over a raw `docker compose`; a raw call needs `make ports-env` first (`make check-ports`).
.PHONY: up down logs stack-run compose-lint image-smoke ports ports-env check-ports project

ENV_FILE ?= .env
# From the environment, else the PORT_OFFSET line of ENV_FILE, else 0. Validated before any shell use.
# $(value) keeps an environment value literal: a `$(shell ...)` in it must be rejected, never run.
ifeq ($(origin PORT_OFFSET),undefined)
PORT_OFFSET := $(shell sed -n 's/^PORT_OFFSET=//p' $(ENV_FILE) 2>/dev/null | tail -n 1)
else
PORT_OFFSET := $(value PORT_OFFSET)
endif
PORT_OFFSET := $(or $(strip $(PORT_OFFSET)),0)
# The largest default port is 11500, so the offset must keep every port <= 65535.
MAX_PORT_OFFSET := 54035
digits_left = $(subst 0,,$(subst 1,,$(subst 2,,$(subst 3,,$(subst 4,,$(subst 5,,$(subst 6,,$(subst 7,,$(subst 8,,$(subst 9,,$(1)))))))))))
ifneq ($(call digits_left,$(PORT_OFFSET)),)
$(error PORT_OFFSET must be a non-negative integer without sign or spaces)
endif
ifneq ($(PORT_OFFSET),0)
ifneq ($(filter 0%,$(PORT_OFFSET)),)
$(error PORT_OFFSET must not have leading zeros)
endif
ifeq ($(shell test $(PORT_OFFSET) -le $(MAX_PORT_OFFSET) && echo ok),)
$(error PORT_OFFSET must be at most $(MAX_PORT_OFFSET) so that every port stays <= 65535)
endif
endif

# Shared dev project (PARALLEL-PLAN section 7): with an offset, every worktree uses `pruefstand-dev` unless the
# environment or ENV_FILE names another project. Without an offset compose keeps its own default.
ifeq ($(origin COMPOSE_PROJECT_NAME),undefined)
COMPOSE_PROJECT_NAME := $(shell sed -n 's/^COMPOSE_PROJECT_NAME=//p' $(ENV_FILE) 2>/dev/null | tail -n 1)
else
COMPOSE_PROJECT_NAME := $(value COMPOSE_PROJECT_NAME)
endif
ifeq ($(strip $(COMPOSE_PROJECT_NAME)),)
ifneq ($(PORT_OFFSET),0)
COMPOSE_PROJECT_NAME := pruefstand-dev
endif
endif
ifneq ($(strip $(COMPOSE_PROJECT_NAME)),)
export COMPOSE_PROJECT_NAME
endif

# The one port table: <service>:<exported variable>:<default host port>. docker.md section 3 is the source.
PORT_TABLE := qdrant:QDRANT_HTTP_PORT:6333 qdrant-grpc:QDRANT_GRPC_PORT:6334 llm:LLM_HOST_PORT:8080 \
    embed:EMBED_HOST_PORT:8090 rag-demo:RAG_DEMO_HOST_PORT:8000 rerank-cpu:RERANK_HOST_PORT:8201 \
    llm-proxy:LLM_PROXY_PORT:11500
port_svc = $(word 1,$(subst :, ,$(1)))
port_var = $(word 2,$(subst :, ,$(1)))
port_val = $(shell echo $$(( $(word 3,$(subst :, ,$(1))) + $(PORT_OFFSET) )))
$(foreach e,$(PORT_TABLE),$(eval export $(call port_var,$(e)) := $(call port_val,$(e))))

PROFILES ?= core
SERVICES ?=
COMPOSE_FILES ?=
WAIT ?=
VOLUMES ?=
SMOKE_TAG ?= pruefstand-smoke
STACK_LOCK ?= $(HOME)/pruefstand/stack.lock
# Seconds to wait for the stack lock (flock -w); empty = wait forever.
STACK_LOCK_WAIT ?=
EXECUTOR_PROJECT ?= pruefstand-exec
DEFAULT_PORTS := 6333 6334 8000 8080 8090 8201 11500

COMPOSE_BASE = docker compose -f docker-compose.yml $(addprefix -f ,$(COMPOSE_FILES))
COMPOSE = $(COMPOSE_BASE) $(addprefix --profile ,$(PROFILES))

up:
	$(COMPOSE) up -d $(if $(WAIT),--wait) $(SERVICES)

# Named volumes (qdrant_data) survive `down`; `make down VOLUMES=1` removes them too.
down:
	$(COMPOSE_BASE) --profile '*' down --remove-orphans $(if $(VOLUMES),-v)

logs:
	$(COMPOSE_BASE) --profile '*' logs --tail=200 $(SERVICES)

project:
	@echo '$(COMPOSE_PROJECT_NAME)'

# One stack session = one lock hold (A13-M8): another agent's `up` cannot replace these containers between
# this `up` and the checks. CMD runs in a subshell and the EXIT trap always tears the stack down, whatever CMD
# does (exit N, set -e, a signal); the exit code of CMD (or of a failed `up`) is preserved.
# CMD must not contain single quotes; never call it from inside the lock.
# Signal handling (D357): bash, not sh, because dash cannot `set -m` without a tty, which left CMD in the
# caller's process group so `kill -TERM -$$pid` hit nothing and CMD survived a TERM sent to make alone. make
# forwards its own TERM to the shell and a group signal delivers a second one, so every handler first ignores
# further TERM/INT (a second delivery used to abort the EXIT trap before `down`). The handler is installed
# before CMD is forked; a signal between `&` and `pid=$$!` is replayed through `stop`. A TERM that reaches
# the new group while its leader is still between fork and exec is lost, so `k` re-sends TERM every 0.2 s
# until the group is gone and falls back to KILL after 2 s.
stack-run:
	@test -n '$(CMD)' || { echo 'usage: make stack-run CMD="..."' >&2; exit 2; }
	$(if $(findstring ',$(CMD)),$(error CMD must not contain single quotes))
	mkdir -p $(dir $(STACK_LOCK))
	flock -F $(if $(STACK_LOCK_WAIT),-w $(STACK_LOCK_WAIT)) $(STACK_LOCK) bash -c 'k() { kill -TERM -$$1 2>/dev/null; for i in 1 2 3 4 5 6 7 8 9 10; do sleep 0.2; kill -0 -$$1 2>/dev/null || return 0; kill -TERM -$$1 2>/dev/null; done; kill -KILL -$$1 2>/dev/null; }; trap "trap \"\" TERM INT; $(MAKE) --no-print-directory down" EXIT; trap "trap \"\" TERM INT; exit 143" TERM INT; $(MAKE) --no-print-directory up WAIT=1 || exit $$?; pid=; stop=; set -m; trap "trap \"\" TERM INT; stop=1; test -z \"\$$pid\" || { k \$$pid; exit 143; }" TERM INT; ( $(CMD) ) & pid=$$!; test -z "$$stop" || { k $$pid; exit 143; }; wait $$pid'

compose-lint:
	uv run python scripts/check_compose.py

image-smoke:
	docker build -f infra/docker/python-uv.Dockerfile --build-arg PKG=pruefstand \
	    --build-arg GIT_SHA="$$(git rev-parse HEAD 2>/dev/null || echo unknown)" -t $(SMOKE_TAG) .

ports:
	@$(foreach e,$(PORT_TABLE),printf '%s %s\n' '$(call port_svc,$(e))' '$(call port_val,$(e))';)

# Writes the effective ports literally into $(ENV_FILE) (one managed block, idempotent, other lines untouched),
# so a plain `docker compose` binds the same ports as `make up`.
ports-env:
	@touch $(ENV_FILE)
	@tmp=$$(mktemp) && \
	awk '/^# >>> ports \(make ports-env\)/{skip=1;next} /^# <<< ports/{skip=0;next} !skip' $(ENV_FILE) > $$tmp && \
	{ cat $$tmp; \
	  echo '# >>> ports (make ports-env)'; \
	  $(if $(filter-out 0,$(PORT_OFFSET)),grep -q '^COMPOSE_PROJECT_NAME=.' $$tmp || echo 'COMPOSE_PROJECT_NAME=pruefstand-dev';) \
	  $(foreach e,$(PORT_TABLE),echo '$(call port_var,$(e))=$(call port_val,$(e))';) \
	  echo '# <<< ports'; } > $(ENV_FILE) && rm -f $$tmp
	@echo "ports-env: wrote the port block (PORT_OFFSET=$(PORT_OFFSET)) to $(ENV_FILE)"

# Warns when a container of any compose project except the executor's publishes a default (executor) port and
# names the project; STRICT=1 makes it fail. CHECK_PORTS_PS overrides the `docker ps` call (tests); its lines are
# "<project> <container> <ports>".
CHECK_PORTS_PS ?= docker ps --filter label=com.docker.compose.project --format '{{.Label "com.docker.compose.project"}} {{.Names}} {{.Ports}}'
check-ports:
	@bad=0; \
	for line in $$($(CHECK_PORTS_PS) | tr ' ' '|'); do \
	  proj=$${line%%|*}; rest=$${line#*|}; name=$${rest%%|*}; \
	  [ "$$proj" = "$(EXECUTOR_PROJECT)" ] && continue; \
	  hosts=$$(printf '%s' "$$rest" | grep -oE ':[0-9]+(-[0-9]+)?->' | sed 's/^://;s/->$$//' | sort -u); \
	  for p in $(DEFAULT_PORTS); do \
	    for h in $$hosts; do \
	      lo=$${h%-*}; hi=$${h#*-}; \
	      if [ "$$p" -ge "$$lo" ] && [ "$$p" -le "$$hi" ]; then \
	        echo "WARNING: project $$proj, container $$name publishes default port $$p (executor port); run make ports-env or use make up" >&2; bad=1; break; \
	      fi; \
	    done; \
	  done; \
	done; \
	if [ $$bad -eq 1 ] && [ -n "$(STRICT)" ]; then exit 1; fi; exit 0
