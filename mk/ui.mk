# Dashboard UI test harness (T8.3, ui-spec §14.2). Included by the root Makefile (-include mk/*.mk).
.PHONY: ui-e2e ui-basepath ui-update-snapshots ui-lighthouse

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

# Visual baselines are written only inside the Playwright container (fonts and rasterisation differ elsewhere).
# Needs Docker; run it on the VM (never on a laptop) and commit apps/dashboard/e2e/__screenshots__/.
PLAYWRIGHT_IMAGE ?= mcr.microsoft.com/playwright:v1.56.1-noble
ui-update-snapshots:
	scripts/dashboard/build_set.sh populated
	scripts/dashboard/build_set.sh empty
	docker run --rm --network host --ipc=host -v "$(CURDIR)":/work -w /work/apps/dashboard \
	  -e UI_VISUAL=1 -e CI=1 $(PLAYWRIGHT_IMAGE) \
	  sh -c "corepack enable && pnpm install --frozen-lockfile && pnpm exec playwright test visual --update-snapshots"

# Lighthouse CI against the populated build (budgets in apps/dashboard/lighthouserc.cjs).
ui-lighthouse:
	scripts/dashboard/build_set.sh populated
	cd apps/dashboard && npx --yes @lhci/cli@0.14.0 autorun --config=lighthouserc.cjs
