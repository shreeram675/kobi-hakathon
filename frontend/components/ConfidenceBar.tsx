import { Progress } from "@/components/ui/progress";
import { confidenceHex } from "@/lib/colors";
import { cn } from "@/lib/format";

/** Coloured progress bar + numeric label. green >=0.80, amber 0.50-0.79, red <0.50. */
export function ConfidenceBar({
  value,
  className,
  showLabel = true,
  width = 96,
}: {
  value: number | null | undefined;
  className?: string;
  showLabel?: boolean;
  width?: number;
}) {
  const has = value != null && !Number.isNaN(value);
  return (
    <div className={cn("flex items-center gap-2", className)}>
      <div style={{ width }} className="shrink-0">
        <Progress value={has ? value! : 0} color={confidenceHex(value)} />
      </div>
      {showLabel && (
        <span className="stat-num w-9 shrink-0 text-right text-xs tabular-nums text-ink/70">
          {has ? value!.toFixed(2) : "—"}
        </span>
      )}
    </div>
  );
}
