"use client";

import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { TOKENS, confidenceHex } from "@/lib/colors";
import type { RetrievedUrl } from "@/lib/types";
import { ChartTooltip } from "./ChartTooltip";

/** Histogram of retrieved_url relevance scores, bucketed into 0.1-wide bins. */
export function UrlScoreHistogram({
  urls,
  height = 160,
}: {
  urls: RetrievedUrl[];
  height?: number;
}) {
  const bins = Array.from({ length: 10 }, (_, i) => ({
    bucket: `${(i / 10).toFixed(1)}`,
    label: `${(i / 10).toFixed(1)}–${((i + 1) / 10).toFixed(1)}`,
    mid: (i + 0.5) / 10,
    count: 0,
  }));
  urls.forEach((u) => {
    const idx = Math.min(9, Math.max(0, Math.floor(u.score * 10)));
    bins[idx].count += 1;
  });

  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={bins} margin={{ top: 8, right: 4, left: 4, bottom: 0 }}>
          <XAxis
            dataKey="bucket"
            tick={{ fontSize: 10, fill: "#64748b" }}
            tickLine={false}
            axisLine={{ stroke: TOKENS.line }}
            interval={0}
          />
          <YAxis
            allowDecimals={false}
            tick={{ fontSize: 10, fill: "#64748b" }}
            tickLine={false}
            axisLine={false}
            width={28}
          />
          <Tooltip
            cursor={{ fill: "rgba(15,124,125,0.06)" }}
            content={<ChartTooltip unit="URLs" labelKey="label" />}
          />
          <Bar dataKey="count" radius={[3, 3, 0, 0]} maxBarSize={34}>
            {bins.map((b, i) => (
              <Cell key={i} fill={confidenceHex(b.mid)} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
