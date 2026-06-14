import { UserCheck } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { fieldLabel } from "@/lib/schema";
import { signed } from "@/lib/format";
import type { HumanReviewItem } from "@/lib/types";

/** Flagged field list — distinct from auto-resolved conflicts. */
export function HumanReviewQueue({ items }: { items: HumanReviewItem[] }) {
  if (!items.length) {
    return (
      <div className="flex items-center gap-2 rounded-card border border-dashed border-line bg-soft-green/40 px-4 py-4 text-sm text-green">
        <UserCheck className="h-4 w-4" />
        Review queue is clear — no fields need human attention.
      </div>
    );
  }
  return (
    <div className="overflow-hidden rounded-card border border-red/30 bg-soft-red/30">
      <div className="flex items-center gap-2 border-b border-red/20 px-4 py-2.5">
        <UserCheck className="h-4 w-4 text-red" />
        <p className="text-sm font-semibold text-red">
          Human review required
        </p>
        <Badge tone="red" className="ml-auto">
          {items.length} field{items.length === 1 ? "" : "s"}
        </Badge>
      </div>
      <ul className="divide-y divide-red/15">
        {items.map((item) => (
          <li
            key={item.field_path}
            className="flex items-start gap-3 px-4 py-2.5"
          >
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-ink">
                {fieldLabel(item.field_path)}
              </p>
              <p className="truncate font-mono text-[10px] text-ink/40">
                {item.field_path}
              </p>
              <p className="mt-0.5 text-xs text-ink/60">{item.reason}</p>
            </div>
            <span
              className="stat-num shrink-0 rounded-pill bg-white px-2 py-0.5 text-[11px] font-semibold text-red tabular-nums"
              title="Score gap between conflicting claims"
            >
              Δ {signed(item.score_gap)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
