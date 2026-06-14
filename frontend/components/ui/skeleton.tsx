import { cn } from "@/lib/format";

export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "animate-pulse rounded-card bg-soft-grey/80",
        className,
      )}
    />
  );
}
