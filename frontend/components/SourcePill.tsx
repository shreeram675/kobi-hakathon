import { ExternalLink } from "lucide-react";
import { hostnameOf, truncate } from "@/lib/format";

/** Clickable URL chip. */
export function SourcePill({ url }: { url: string }) {
  return (
    <a
      href={url}
      target="_blank"
      rel="noreferrer noopener"
      title={url}
      className="pill max-w-[180px] gap-1 border border-line bg-soft-grey/60 text-ink/70 transition-colors hover:border-teal/40 hover:bg-[#e2f3f3] hover:text-teal"
    >
      <ExternalLink className="h-3 w-3 shrink-0" />
      <span className="truncate">{truncate(hostnameOf(url), 26)}</span>
    </a>
  );
}

export function SourcePillRow({ urls }: { urls: string[] }) {
  if (!urls?.length) {
    return <span className="text-xs text-ink/35">—</span>;
  }
  const shown = urls.slice(0, 3);
  const extra = urls.length - shown.length;
  return (
    <div className="flex flex-wrap items-center gap-1">
      {shown.map((u, i) => (
        <SourcePill key={`${u}-${i}`} url={u} />
      ))}
      {extra > 0 && (
        <span className="pill bg-soft-grey text-ink/50">+{extra}</span>
      )}
    </div>
  );
}
