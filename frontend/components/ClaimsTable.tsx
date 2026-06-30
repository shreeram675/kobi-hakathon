import { StatusBadge, VolatilityChip } from "./badges";
import { SourcePillRow } from "./SourcePill";
import { fieldLabel } from "@/lib/schema";
import { renderValue } from "@/lib/format";
import type { Claim } from "@/lib/types";

/** Claims table (Node 7). */
export function ClaimsTable({ claims }: { claims: Claim[] }) {
  if (!claims.length) {
    return (
      <p className="rounded-card border border-dashed border-line bg-soft-grey/30 px-4 py-6 text-center text-sm text-ink/45">
        No claims extracted yet.
      </p>
    );
  }
  return (
    <div className="overflow-hidden rounded-card border border-line bg-white shadow-sm">
      <div className="hidden grid-cols-[160px_56px_minmax(0,2fr)_96px_minmax(0,1fr)] gap-3 border-b border-line bg-soft-grey/40 px-4 py-2 text-[10px] font-semibold uppercase tracking-wide text-ink/45 md:grid">
        <span>Field</span>
        <span>Volatility</span>
        <span>Value</span>
        <span>Status</span>
        <span>Source</span>
      </div>
      <div className="max-h-[420px] divide-y divide-line overflow-y-auto scroll-thin">
        {claims.map((c) => (
          <div
            key={c.claim_id}
            className="grid grid-cols-1 gap-2 px-4 py-2.5 md:grid-cols-[160px_56px_minmax(0,2fr)_96px_minmax(0,1fr)] md:items-center md:gap-3"
          >
            <span className="truncate text-sm font-medium text-ink">
              {fieldLabel(c.field_path)}
            </span>
            <VolatilityChip volatility={c.volatility} />
            <div className="truncate text-sm text-ink/80">
              {renderValue(c.value_json)}
            </div>
            <StatusBadge status={c.status} />
            <SourcePillRow urls={c.source_url ? [c.source_url] : []} />
          </div>
        ))}
      </div>
    </div>
  );
}
