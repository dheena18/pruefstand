import { t, type Locale } from "@/lib/i18n";

import { TenantBadge, tenantKind } from "./TenantBadge";

export interface ChunkCardProps {
  locale: Locale;
  /** 1-based rank (the retrieval order). */
  rank: number;
  chunkId: string;
  caseTenant: string;
  /** Tenant of the chunk from `retrieved_chunk_tenant_ids` (R3); absent or empty → no badge. */
  chunkTenant?: string | undefined;
}

/** One retrieved chunk: rank, id, tenant badge. The text is not published (sanitised data). */
export function ChunkCard({ locale, rank, chunkId, caseTenant, chunkTenant }: ChunkCardProps) {
  const kind = tenantKind(chunkTenant, caseTenant);
  return (
    <li className="chunk" data-kind={kind}>
      <span className="chunk__rank">#{rank}</span>
      <span className="mono chunk__id">{chunkId}</span>
      {chunkTenant === undefined ? null : (
        <TenantBadge locale={locale} tenant={chunkTenant} caseTenant={caseTenant} />
      )}
      <span className="chunk__note">{t(locale, "chunk.text_withheld")}</span>
    </li>
  );
}
