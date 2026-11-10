# Dashboard UI test harness (T8.3, ui-spec §14.2). Included by the root Makefile (-include mk/*.mk).
.PHONY: ui-e2e ui-basepath

# PR projects: populated-{360,1280}, empty-{360,1280} against the two fixture-set builds (X1.2).
ui-e2e:
	scripts/dashboard/build_set.sh populated
	scripts/dashboard/build_set.sh empty
	cd apps/dashboard && pnpm exec playwright test

# basePath smoke (N5.5): build `populated-bp` with basePath=/pruefstand, serve it under /pruefstand/ (serve_under_base.sh),
# run e2e/basepath.spec.ts in project populated-basepath-1280.
ui-basepath:
	NEXT_BASE_PATH=/pruefstand scripts/dashboard/build_set.sh populated --out populated-bp
	cd apps/dashboard && UI_BASEPATH=1 pnpm exec playwright test
