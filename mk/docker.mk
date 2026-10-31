# Docker / compose targets (T0.3). Included by the root Makefile (-include mk/*.mk).
# Compose has no arithmetic, so every published host port is exported here as default + PORT_OFFSET
# (D214, Y1.4): PORT_OFFSET unset or 0 = defaults (CI, laptops), 10000 = the owner's dev stack on the VM.
# Prefer `make up` over a raw `docker compose`; a raw call needs `make ports-env` first (`make check-ports`).
.PHONY: up down logs stack-run compose-lint image-smoke ports ports-env check-ports

ENV_FILE ?= .env
PORT_OFFSET ?= $(or $(shell sed -n 's/^PORT_OFFSET=//p' $(ENV_FILE) 2>/dev/null | tail -n 1),0)
ifeq ($(shell printf '%s' '$(PORT_OFFSET)' | grep -cE '^[0-9]+$$'),0)
$(error PORT_OFFSET must be a non-negative integer, got '$(PORT_OFFSET)')
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
STACK_LOCK ?= $(HOME)/pruefstand/stack.lock
DEV_PROJECT ?= pruefstand-dev
DEFAULT_PORTS := 6333 6334 8000 8080 8090 8201 11500

COMPOSE_BASE = docker compose -f docker-compose.yml $(addprefix -f ,$(COMPOSE_FILES))
COMPOSE = $(COMPOSE_BASE) $(addprefix --profile ,$(PROFILES))

up:
	$(COMPOSE) up -d $(if $(WAIT),--wait) $(SERVICES)

down:
	$(COMPOSE_BASE) --profile '*' down --remove-orphans

logs:
	$(COMPOSE_BASE) --profile '*' logs --tail=200 $(SERVICES)

# One stack session = one lock hold (A13-M8): another agent's `up` cannot replace these containers between
# this `up` and the checks. CMD must not contain single quotes. Never call it from inside the lock.
stack-run:
	@test -n '$(CMD)' || { echo 'usage: make stack-run CMD="..."' >&2; exit 2; }
	$(if $(findstring ',$(CMD)),$(error CMD must not contain single quotes))
	mkdir -p $(dir $(STACK_LOCK))
	flock $(STACK_LOCK) sh -c '$(MAKE) up WAIT=1 && { $(CMD); rc=$$?; } || rc=$$?; $(MAKE) down; exit $$rc'

compose-lint:
	uv run python scripts/check_compose.py

image-smoke:
	docker build -f infra/docker/python-uv.Dockerfile --build-arg PKG=pruefstand \
	    --build-arg GIT_SHA="$$(git rev-parse HEAD 2>/dev/null || echo unknown)" -t pruefstand-smoke .

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
	  $(foreach e,$(PORT_TABLE),echo '$(call port_var,$(e))=$(call port_val,$(e))';) \
	  echo '# <<< ports'; } > $(ENV_FILE) && rm -f $$tmp
	@echo "ports-env: wrote the port block (PORT_OFFSET=$(PORT_OFFSET)) to $(ENV_FILE)"

# Warns when a container of the dev project publishes a default (executor) port; STRICT=1 makes it fail.
# CHECK_PORTS_PS overrides the `docker ps` call (tests).
CHECK_PORTS_PS ?= docker ps --filter label=com.docker.compose.project=$(DEV_PROJECT) --format '{{.Names}} {{.Ports}}'
check-ports:
	@bad=0; \
	for line in $$($(CHECK_PORTS_PS) | tr ' ' '|'); do \
	  name=$${line%%|*}; \
	  for p in $$(printf '%s' "$$line" | grep -oE ':[0-9]+->' | tr -d ':>-'); do \
	    case " $(DEFAULT_PORTS) " in *" $$p "*) \
	      echo "WARNING: $$name publishes default port $$p (executor port); run make ports-env or use make up" >&2; bad=1;; esac; \
	  done; \
	done; \
	if [ $$bad -eq 1 ] && [ -n "$(STRICT)" ]; then exit 1; fi; exit 0
