import { MetricCard, type MetricCardProps } from "./MetricCard";
import { cn } from "@/lib/format";

/** Horizontal metric strip (4-up by default). */
export function StatRow({
  items,
  columns = 4,
  className,
}: {
  items: MetricCardProps[];
  columns?: 2 | 3 | 4 | 5;
  className?: string;
}) {
  const cols: Record<number, string> = {
    2: "grid-cols-2",
    3: "grid-cols-2 sm:grid-cols-3",
    4: "grid-cols-2 lg:grid-cols-4",
    5: "grid-cols-2 sm:grid-cols-3 lg:grid-cols-5",
  };
  return (
    <div className={cn("grid gap-3", cols[columns], className)}>
      {items.map((item, i) => (
        <MetricCard key={`${item.label}-${i}`} {...item} />
      ))}
    </div>
  );
}
