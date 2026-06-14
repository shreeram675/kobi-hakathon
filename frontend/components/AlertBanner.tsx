import { AlertTriangle, Info, ShieldAlert } from "lucide-react";
import { type ReactNode } from "react";
import { cn } from "@/lib/format";

type Level = "amber" | "red" | "info";

const STYLES: Record<Level, { wrap: string; bar: string; icon: ReactNode }> = {
  amber: {
    wrap: "bg-soft-amber/70 border-amber/30 text-amber",
    bar: "bg-amber",
    icon: <AlertTriangle className="h-4 w-4" />,
  },
  red: {
    wrap: "bg-soft-red/70 border-red/30 text-red",
    bar: "bg-red",
    icon: <ShieldAlert className="h-4 w-4" />,
  },
  info: {
    wrap: "bg-[#e6effb]/70 border-blue/30 text-blue",
    bar: "bg-blue",
    icon: <Info className="h-4 w-4" />,
  },
};

/** Amber / red dual-accent conflict/review alert. */
export function AlertBanner({
  level = "amber",
  title,
  children,
  className,
}: {
  level?: Level;
  title: ReactNode;
  children?: ReactNode;
  className?: string;
}) {
  const s = STYLES[level];
  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-card border px-4 py-3",
        s.wrap,
        className,
      )}
      role="alert"
    >
      <span className={cn("absolute inset-y-0 left-0 w-1", s.bar)} aria-hidden />
      <div className="flex items-start gap-2.5">
        <span className="mt-0.5 shrink-0">{s.icon}</span>
        <div className="min-w-0">
          <p className="text-sm font-semibold leading-snug">{title}</p>
          {children && (
            <div className="mt-0.5 text-xs leading-relaxed text-ink/70">
              {children}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
