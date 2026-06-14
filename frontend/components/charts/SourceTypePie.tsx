"use client";

import { Donut } from "./Donut";
import { colorForSourceType } from "@/lib/colors";
import { titleCase } from "@/lib/format";
import type { RetrievedUrl } from "@/lib/types";

/** PieChart of source_type distribution across retrieved URLs. */
export function SourceTypePie({ urls }: { urls: RetrievedUrl[] }) {
  const counts = new Map<string, number>();
  urls.forEach((u) => counts.set(u.source_type, (counts.get(u.source_type) ?? 0) + 1));
  const data = Array.from(counts.entries())
    .sort((a, b) => b[1] - a[1])
    .map(([name, value]) => ({
      name: titleCase(name),
      value,
      color: colorForSourceType(name),
    }));

  return (
    <Donut
      data={data}
      centerValue={urls.length}
      centerLabel="URLs"
      size={150}
      thickness={20}
    />
  );
}
