import { t, type Locale } from "@/lib/i18n";

export type TenantKind = "own" | "shared" | "leak" | "unknown";

/** `shared_public` is the tenant id of the shared corpus (laws); anything else but the case's tenant is foreign. */
export const SHARED_TENANT = "shared_public";

/** Own, shared or foreign (R3). An empty or missing tenant is unknown: the target did not report it. */
export function tenantKind(chunkTenant: string | undefined, caseTenant: string): TenantKind {
  if (chunkTenant === undefined || chunkTenant === "") return "unknown";
  if (chunkTenant === SHARED_TENANT) return "shared";
  return chunkTenant === caseTenant ? "own" : "leak";
}

export interface TenantBadgeProps {
  locale: Locale;
  tenant: string;
  caseTenant: string;
}

/** Tenant of a chunk as text, never colour alone; a foreign tenant reads "⚠ LEAK" in the fail colour (ui-spec §5). */
export function TenantBadge({ locale, tenant, caseTenant }: TenantBadgeProps) {
  const kind = tenantKind(tenant, caseTenant);
  if (kind === "unknown") return null;
  return (
    <span className={`tenant-badge tenant-badge--${kind}`}>
      {kind === "leak" ? <span className="tenant-badge__leak">⚠ LEAK </span> : null}
      <span className="mono">{tenant}</span>
      {kind === "leak" ? (
        <span className="sr-only"> {t(locale, "chunk.leak", { tenant })}</span>
      ) : null}
    </span>
  );
}
