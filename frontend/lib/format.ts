import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** 0..1 -> "84%" */
export function pct(value: number | null | undefined, digits = 0): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

/** 0..1 -> "0.84" */
export function ratio(value: number | null | undefined, digits = 2): string {
  if (value == null || Number.isNaN(value)) return "—";
  return value.toFixed(digits);
}

/** signed gap, e.g. +0.18 / -0.04 */
export function signed(value: number | null | undefined, digits = 2): string {
  if (value == null || Number.isNaN(value)) return "—";
  const sign = value > 0 ? "+" : value < 0 ? "−" : "±";
  return `${sign}${Math.abs(value).toFixed(digits)}`;
}

export function compact(value: number | null | undefined): string {
  if (value == null) return "—";
  return new Intl.NumberFormat("en", { notation: "compact" }).format(value);
}

/** Render any extracted value to a readable string. */
export function renderValue(value: unknown): string {
  if (value == null) return "—";
  if (Array.isArray(value)) {
    return value.map((v) => renderValue(v)).join(", ");
  }
  if (typeof value === "object") {
    try {
      return Object.entries(value as Record<string, unknown>)
        .map(([k, v]) => `${k.replace(/_/g, " ")}: ${renderValue(v)}`)
        .join("; ");
    } catch {
      return JSON.stringify(value);
    }
  }
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

export function truncate(text: string | null | undefined, max = 64): string {
  if (!text) return "";
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const diff = Date.now() - then;
  const sec = Math.round(diff / 1000);
  if (sec < 5) return "just now";
  if (sec < 60) return `${sec}s ago`;
  const min = Math.round(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.round(hr / 24);
  return `${day}d ago`;
}

/** mm:ss elapsed between two ISO timestamps (end defaults to now). */
export function elapsed(startIso: string, endIso?: string): string {
  const start = new Date(startIso).getTime();
  const end = endIso ? new Date(endIso).getTime() : Date.now();
  let s = Math.max(0, Math.round((end - start) / 1000));
  const m = Math.floor(s / 60);
  s = s % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function hostnameOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

/** Rough token estimate when chunks carry no explicit token_count. */
export function estimateTokens(text: string | null | undefined): number {
  if (!text) return 0;
  return Math.max(1, Math.round(text.length / 4));
}

export function titleCase(text: string): string {
  return text.replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
