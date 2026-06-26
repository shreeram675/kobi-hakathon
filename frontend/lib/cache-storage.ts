/**
 * Persistent client-side store for Recent Searches.
 * Writes to localStorage so history survives page refreshes and server restarts.
 */

const RECENT_KEY = "kobie_recent_searches_v2";
const MAX_RECENT = 50;

export interface RecentSearch {
  run_id: string;
  user_input: string;
  programs?: string[];
  mode: "single" | "compare" | "converse";
  created_at: string;
  program_name?: string | null;
  status?: string;
  data_quality?: number;
}

function safeRead<T>(key: string, fallback: T): T {
  if (typeof window === "undefined") return fallback;
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function safeWrite(key: string, value: unknown): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // quota exceeded or private mode — ignore silently
  }
}

export function getRecentSearches(): RecentSearch[] {
  return safeRead<RecentSearch[]>(RECENT_KEY, []);
}

/**
 * Upsert by run_id: merge if exists (preserving position), prepend if new.
 */
export function upsertRecentSearch(search: RecentSearch): void {
  const existing = getRecentSearches();
  const idx = existing.findIndex((s) => s.run_id === search.run_id);
  let updated: RecentSearch[];
  if (idx >= 0) {
    updated = [...existing];
    updated[idx] = { ...existing[idx], ...search };
  } else {
    updated = [search, ...existing].slice(0, MAX_RECENT);
  }
  safeWrite(RECENT_KEY, updated);
}

export function removeRecentSearch(runId: string): void {
  safeWrite(RECENT_KEY, getRecentSearches().filter((s) => s.run_id !== runId));
}

export function clearRecentSearches(): void {
  safeWrite(RECENT_KEY, []);
}
