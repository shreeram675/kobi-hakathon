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
      <span className="relative grid h-9 w-9 place-items-center rounded-[10px] bg-gradient-to-br from-[#1a3a5c] via-[#c25e10] to-[#F47920] shadow-[0_4px_14px_rgba(244,121,32,0.5)]">
        <span className="absolute inset-0 rounded-[10px] ring-1 ring-inset ring-white/15" />
        <KMark className="h-4 w-4 text-white" />
      </span>
      <span className="flex flex-col leading-none">
        <span className="flex items-center gap-1 text-[15px] font-semibold tracking-tight text-white">
          Kobie
          <HeartMark className="h-3.5 w-3.5 text-[#F47920]" />
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

function HeartMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className={className} aria-hidden>
      <path d="M12 21s-7.5-4.6-10.2-9.3C.3 8.9 1.6 5.2 5 4.2c2-.6 4 .1 5.2 1.9L12 8.3l1.8-2.2c1.2-1.8 3.2-2.5 5.2-1.9 3.4 1 4.7 4.7 3.2 7.5C19.5 16.4 12 21 12 21z" />
    </svg>
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
