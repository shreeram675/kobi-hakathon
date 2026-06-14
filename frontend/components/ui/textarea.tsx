import { forwardRef, type TextareaHTMLAttributes } from "react";
import { cn } from "@/lib/format";

export const Textarea = forwardRef<
  HTMLTextAreaElement,
  TextareaHTMLAttributes<HTMLTextAreaElement>
>(({ className, ...props }, ref) => (
  <textarea
    ref={ref}
    className={cn(
      "w-full resize-none rounded-card border border-line bg-white px-4 py-3 text-sm text-ink placeholder:text-ink/35 shadow-sm transition focus:border-teal focus:outline-none focus:ring-2 focus:ring-teal/30",
      className,
    )}
    {...props}
  />
));
Textarea.displayName = "Textarea";

export const Input = forwardRef<
  HTMLInputElement,
  React.InputHTMLAttributes<HTMLInputElement>
>(({ className, ...props }, ref) => (
  <input
    ref={ref}
    className={cn(
      "w-full rounded-card border border-line bg-white px-3.5 py-2.5 text-sm text-ink placeholder:text-ink/35 shadow-sm transition focus:border-teal focus:outline-none focus:ring-2 focus:ring-teal/30",
      className,
    )}
    {...props}
  />
));
Input.displayName = "Input";
