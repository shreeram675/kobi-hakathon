import React from "react";

/** Matches http(s) URLs, excluding trailing punctuation that belongs to the sentence. */
const URL_RE = /https?:\/\/[^\s)\]},;'"]+[^\s)\]},;'".:]/g;

export function domainOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

/**
 * Remove full URLs from analyst prose, keeping the citation readable:
 *   "(source: https://example.com/very/long/path)" → "(source: example.com)"
 *   bare "https://example.com/path" mid-sentence   → "example.com"
 */
export function stripInlineSources(text: string): string {
  return text
    .replace(URL_RE, (url) => domainOf(url))
    .replace(/\(\s*sources?:\s*([^)]*)\)/gi, (_m, inner: string) => {
      const domains = inner
        .split(/[,\s]+/)
        .map((d: string) => d.trim())
        .filter(Boolean);
      const unique = Array.from(new Set(domains));
      return `(source: ${unique.join(", ")})`;
    })
    .replace(/\s{2,}/g, " ")
    .trim();
}

/**
 * Render analyst prose with every URL replaced by a compact domain hyperlink.
 * Existing briefs embed full URLs mid-sentence; this keeps the citation but
 * shows only the clickable domain.
 */
export function LinkifiedText({ text }: { text: string }) {
  const parts: React.ReactNode[] = [];
  let last = 0;
  let match: RegExpExecArray | null;
  const re = new RegExp(URL_RE.source, "g");
  while ((match = re.exec(text)) !== null) {
    if (match.index > last) parts.push(text.slice(last, match.index));
    const url = match[0];
    parts.push(
      <a
        key={`${match.index}-${url}`}
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        className="font-medium text-teal hover:underline"
        title={url}
      >
        {domainOf(url)}
      </a>,
    );
    last = match.index + url.length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return <>{parts}</>;
}
