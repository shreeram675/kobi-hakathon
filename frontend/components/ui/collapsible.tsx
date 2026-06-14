"use client";

import { ChevronRight } from "lucide-react";
import { useState, type ReactNode } from "react";
import { cn } from "@/lib/format";

export interface CollapsibleProps {
  header: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
  className?: string;
  headerClassName?: string;
}

export function Collapsible({
  header,
  children,
  defaultOpen = false,
  className,
  headerClassName,
}: CollapsibleProps) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className={cn("overflow-hidden", className)}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "flex w-full items-center gap-2 text-left transition-colors",
          headerClassName,
        )}
        aria-expanded={open}
      >
        <ChevronRight
          className={cn(
            "h-4 w-4 shrink-0 text-ink/40 transition-transform",
            open && "rotate-90",
          )}
        />
        <div className="min-w-0 flex-1">{header}</div>
      </button>
      {open && <div className="animate-fade-up">{children}</div>}
    </div>
  );
}
