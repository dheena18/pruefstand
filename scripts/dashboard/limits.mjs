// Size caps of the published data tree (ui-spec §2.3, N5.1, D259). The Python side owns them in
// `pruefstand.core.models.dashboard`; `test/build/limits.test.ts` fails if this copy drifts.
export const MAX_INDEX_RUNS = 200;
export const MAX_CASE_RUNS = 20;
export const MAX_SHARD_CASES = 500;
export const PLACEHOLDER = "_empty";
