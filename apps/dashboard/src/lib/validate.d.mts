import type { ValidateFunction } from "ajv";

export type Kind = "run" | "gate" | "index" | "slices" | "cases" | "labels";
export type Validators = Record<Kind, ValidateFunction>;
export type CheckResult = { ok: true } | { ok: false; unsupported: boolean; message: string };

export const KINDS: Record<Kind, string>;
export const SCHEMA_VERSION: "1";
export function makeValidators(schemas: Record<string, object>): Validators;
export function check(validators: Validators, kind: Kind, data: unknown): CheckResult;
