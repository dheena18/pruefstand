// Runtime validation shared by the data layer (TypeScript) and scripts/dashboard/validate_data.mjs (Node):
// the same JSON Schemas, the same Ajv options (ui-spec §2.4). Plain ESM so both can import it.
import Ajv2020 from "ajv/dist/2020.js";
import addFormats from "ajv-formats";

/** Document kind -> schema file stem in `schemas/`. */
export const KINDS = {
    run: "run_manifest",
    gate: "gate_report",
    index: "dashboard_run_index",
    slices: "dashboard_slices",
    cases: "dashboard_cases",
    labels: "labels",
};

/** The only `schema_version` this build understands. */
export const SCHEMA_VERSION = "1";

/**
 * Compile one validator per kind.
 * @param {Record<string, object>} schemas schema documents by file stem (see KINDS)
 */
export function makeValidators(schemas) {
    const ajv = new Ajv2020({ allErrors: true, strict: false });
    addFormats(ajv);
    const validators = {};
    for (const [kind, stem] of Object.entries(KINDS)) {
        const schema = schemas[stem];
        if (schema === undefined) throw new Error(`missing schema ${stem}`);
        validators[kind] = ajv.compile(schema);
    }
    return validators;
}

/**
 * Check one parsed document.
 * @returns {{ok: true} | {ok: false, unsupported: boolean, message: string}}
 */
export function check(validators, kind, data) {
    const validate = validators[kind];
    if (validate === undefined) throw new Error(`unknown kind ${kind}`);
    const version = data !== null && typeof data === "object" ? data.schema_version : undefined;
    if (version !== SCHEMA_VERSION) {
        return {
            ok: false,
            unsupported: true,
            message: `unsupported schema_version ${JSON.stringify(version)} (this build reads "${SCHEMA_VERSION}")`,
        };
    }
    if (validate(data)) return { ok: true };
    const first = (validate.errors ?? [])
        .slice(0, 3)
        .map((e) => `${e.instancePath || "/"} ${e.message}`);
    return { ok: false, unsupported: false, message: first.join("; ") };
}
