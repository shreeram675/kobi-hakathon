import { cn } from "@/lib/format";

export interface ProgressProps {
  /** 0..1 */
  value: number;
  className?: string;
  /** track height in px */
  height?: number;
  /** explicit bar colour (hex). Falls back to teal. */
  color?: string;
}

export function Progress({ value, className, height = 6, color }: ProgressProps) {
  const clamped = Math.max(0, Math.min(1, value || 0));
  return (
    <div
      className={cn("w-full overflow-hidden rounded-pill bg-soft-grey", className)}
      style={{ height }}
    >
      <div
        className="h-full rounded-pill transition-[width] duration-500 ease-out"
        style={{
          width: `${clamped * 100}%`,
          backgroundColor: color ?? "var(--teal)",
        }}
      />
    </div>
  );
}
