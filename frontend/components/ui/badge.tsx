import { type HTMLAttributes } from "react";
import { cn } from "@/lib/format";

export type Tone = "green" | "amber" | "red" | "grey" | "blue" | "teal" | "navy";

const TONE_CLASSES: Record<Tone, string> = {
  green: "bg-soft-green text-green",
  amber: "bg-soft-amber text-amber",
  red: "bg-soft-red text-red",
  grey: "bg-soft-grey text-ink/60",
  blue: "bg-[#e6effb] text-blue",
  teal: "bg-[#e2f3f3] text-teal",
  navy: "bg-[#e7edf4] text-navy",
};

const DOT_CLASSES: Record<Tone, string> = {
  green: "bg-green",
  amber: "bg-amber",
  red: "bg-red",
  grey: "bg-ink/40",
  blue: "bg-blue",
  teal: "bg-teal",
  navy: "bg-navy",
};

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: Tone;
  dot?: boolean;
}

export function Badge({
  className,
  tone = "grey",
  dot = false,
  children,
  ...props
}: BadgeProps) {
  return (
    <span className={cn("pill", TONE_CLASSES[tone], className)} {...props}>
      {dot && (
        <span className={cn("h-1.5 w-1.5 rounded-full", DOT_CLASSES[tone])} />
      )}
      {children}
    </span>
  );
}
