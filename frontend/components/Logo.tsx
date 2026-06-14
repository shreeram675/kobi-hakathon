import Link from "next/link";
import { cn } from "@/lib/format";

/** Kobie logo: navy/teal gradient diamond mark + wordmark. */
export function Logo({
  className,
  subtitle = true,
}: {
  className?: string;
  subtitle?: boolean;
}) {
  return (
    <Link href="/" className={cn("group flex items-center gap-2.5", className)}>
      <span className="relative grid h-9 w-9 place-items-center rounded-[10px] bg-gradient-to-br from-navy via-[#155e6b] to-teal shadow-[0_4px_14px_rgba(15,124,125,0.45)]">
        <span className="absolute inset-0 rounded-[10px] ring-1 ring-inset ring-white/15" />
        <KMark className="h-4 w-4 text-white" />
      </span>
      <span className="flex flex-col leading-none">
        <span className="text-[15px] font-semibold tracking-tight text-white">
          Kobie
        </span>
        {subtitle && (
          <span className="mt-0.5 text-[10px] font-medium uppercase tracking-[0.16em] text-white/45">
            Loyalty Intelligence
          </span>
        )}
      </span>
    </Link>
  );
}

function KMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" className={className} aria-hidden>
      <path
        d="M6 3v18M6 12l9-9M6 12l9 9"
        stroke="currentColor"
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
