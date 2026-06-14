"use client";

import { Search } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { colorForSourceType } from "@/lib/colors";
import { titleCase } from "@/lib/format";
import type { SearchQuery } from "@/lib/types";

/** Queries grouped by source_type with a count badge per group. */
export function QueryList({ queries }: { queries: SearchQuery[] }) {
  const groups = new Map<string, SearchQuery[]>();
  queries.forEach((q) => {
    const arr = groups.get(q.source_type) ?? [];
    arr.push(q);
    groups.set(q.source_type, arr);
  });
  const ordered = Array.from(groups.entries()).sort((a, b) => b[1].length - a[1].length);

  return (
    <div className="space-y-4">
      {ordered.map(([sourceType, items]) => (
        <div key={sourceType}>
          <div className="mb-1.5 flex items-center gap-2">
            <span
              className="h-2.5 w-2.5 rounded-sm"
              style={{ background: colorForSourceType(sourceType) }}
            />
            <span className="text-xs font-semibold uppercase tracking-wide text-ink/60">
              {titleCase(sourceType)}
            </span>
            <Badge tone="navy" className="px-2 py-0.5">
              {items.length}
            </Badge>
          </div>
          <ul className="space-y-1">
            {items.map((q) => (
              <li
                key={q.query_id}
                className="flex items-start gap-2 rounded-md border border-line bg-white px-2.5 py-1.5 text-xs"
              >
                <Search className="mt-0.5 h-3 w-3 shrink-0 text-ink/35" />
                <span className="min-w-0 flex-1 text-ink/80">{q.query}</span>
                {q.external_query_id && (
                  <span className="stat-num shrink-0 font-mono text-[10px] text-ink/35">
                    {q.external_query_id}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
