# VM helper (D660). Included by the root Makefile (-include mk/*.mk).
.PHONY: check-vm

# `make check` queued so that at most 2 full runs go at once on the shared VM (scripts/vm_check.sh).
check-vm:
	scripts/vm_check.sh
