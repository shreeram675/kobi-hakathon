"use client";

import {
  Bar,
  BarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { TOKENS } from "@/lib/colors";
import { estimateTokens } from "@/lib/format";
import type { SemanticChunk } from "@/lib/types";
import { ChartTooltip } from "./ChartTooltip";

function tokensOf(chunk: SemanticChunk): number {
  return chunk.token_count ?? estimateTokens(chunk.chunk_text);
}

/** Per-chunk token distribution across the extraction chunks. */
export function TokenBarChart({
  chunks,
  height = 160,
}: {
  chunks: SemanticChunk[];
  height?: number;
}) {
  const data = chunks
    .slice(0, 40)
    .map((c, i) => ({ name: `#${i + 1}`, tokens: tokensOf(c) }));

  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 4, left: -20, bottom: 0 }}>
          <XAxis
            dataKey="name"
            tick={{ fontSize: 9, fill: "#64748b" }}
            tickLine={false}
            axisLine={{ stroke: TOKENS.line }}
            interval={Math.max(0, Math.floor(data.length / 12))}
          />
          <YAxis
            tick={{ fontSize: 10, fill: "#64748b" }}
            tickLine={false}
            axisLine={false}
            width={36}
          />
          <Tooltip
            cursor={{ fill: "rgba(15,124,125,0.06)" }}
            content={<ChartTooltip unit="tokens" />}
          />
          <Bar dataKey="tokens" fill={TOKENS.teal} radius={[3, 3, 0, 0]} maxBarSize={20} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
