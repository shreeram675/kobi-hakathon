/**
 * Deterministic mock data generators that produce a complete, schema-faithful
 * AgentState. The engine slices this into progressive views as stages "run".
 *
 * This stands in for the Python/LangGraph backend until the real REST API
 * (GET /api/run/{id}) is wired up — the shapes match schemas.py exactly.
 */

import {
  CATEGORY_LABELS,
  CATEGORY_ORDER,
  FOCUSED_SCHEMA_FIELD_PATHS,
  SCHEMA_FIELD_PATHS,
  TOTAL_FIELDS,
  categoryOf,
  fieldLabel,
  volatilityFor,
} from "../schema";
import type {
  AdjudicatedClaim,
  AgentState,
  Claim,
  ClaimStatus,
  ComparisonItem,
  ComparisonOutcome,
  ComparisonOutput,
  ConflictRecord,
  DebateRound,
  ExtractedField,
  ExtractedObjectPacket,
  FieldReport,
  FieldReportEntry,
  HumanReviewItem,
  NormalizedObjectPacket,
  PipelineError,
  ProgramIdentity,
  RetrievedUrl,
  ScrapedUrlBlock,
  SearchQuery,
  SemanticChunk,
} from "../types";
import { estimateTokens } from "../format";

// ---- tiny seeded RNG so a run is stable across rebuilds ----

function makeRng(seedStr: string) {
  let h = 1779033703 ^ seedStr.length;
  for (let i = 0; i < seedStr.length; i++) {
    h = Math.imul(h ^ seedStr.charCodeAt(i), 3432918353);
    h = (h << 13) | (h >>> 19);
  }
  return () => {
    h = Math.imul(h ^ (h >>> 16), 2246822507);
    h = Math.imul(h ^ (h >>> 13), 3266489909);
    h ^= h >>> 16;
    return (h >>> 0) / 4294967296;
  };
}

export interface ProgramProfile {
  program_name: string;
  brand: string;
  domain: string;
  industry: string;
  category: string;
  parent: string;
  geography: string;
  country: string;
  values: Record<string, unknown>;
}

const PROFILES: ProgramProfile[] = [
  {
    program_name: "Marriott Bonvoy",
    brand: "Marriott International",
    domain: "marriott.com",
    industry: "Hotel",
    category: "Hotel",
    parent: "Marriott International, Inc.",
    geography: "Global",
    country: "United States",
    values: {
      "program_basics.program_name": "Marriott Bonvoy",
      "program_basics.brand": "Marriott International",
      "program_basics.industry": "Hotel",
      "program_basics.program_type": "points-based, tiered loyalty",
      "program_basics.geography": "Global (139 countries)",
      "program_basics.membership_count": "228 million members",
      "program_basics.ownership_or_parent_company": "Marriott International, Inc.",
      "earn_mechanics.base_earn_rate": "10 points per USD 1 at most brands",
      "earn_mechanics.earn_rate_unit": "points per USD",
      "earn_mechanics.bonus_categories": ["Dining: 2x via Eat Around Town", "Co-brand card: up to 17x"],
      "earn_mechanics.non_transactional_earn": ["Surveys", "Eat Around Town dining", "Credit card spend"],
      "burn_mechanics.redemption_options": ["Free nights", "Airline transfer", "Experiences", "Gift cards"],
      "burn_mechanics.redemption_thresholds": "From 5,000 points per night",
      "burn_mechanics.point_value_cpp": "0.84 cents per point",
      "burn_mechanics.expiry_policy": "Points expire after 24 months of inactivity",
      "tier_system.tier_names": ["Member", "Silver Elite", "Gold Elite", "Platinum Elite", "Titanium Elite", "Ambassador Elite"],
      "tier_system.qualification_criteria": ["Qualifying nights per year", "Annual spend (Ambassador)"],
      "tier_system.tier_thresholds": "Titanium: 75 nights; Ambassador: 100 nights + USD 23k",
      "tier_system.tier_benefits": ["Suite upgrades", "Lounge access", "Late checkout", "Welcome gift"],
      "tier_system.qualification_period": "Calendar year (Jan–Dec)",
      "partnerships.partner_names": ["United Airlines", "Emirates", "Hertz", "Uber", "Starbucks"],
      "partnerships.partnership_type": "Airline transfer + co-brand card + lifestyle",
      "partnerships.details": "3:1 transfer to most airlines; 60k bonus miles per 60k points to United",
      "digital_experience.mobile_app_available": "Yes",
      "digital_experience.app_ratings": ["App Store: 4.8", "Google Play: 4.6"],
      "digital_experience.app_store_rating": "4.8 / 5 (App Store)",
      "digital_experience.play_store_rating": "4.6 / 5 (Google Play)",
      "digital_experience.personalization_features": ["Mobile check-in", "Chat with hotel", "Room preferences"],
      "digital_experience.gamification_features": ["Limited-time point multiplier events", "Milestone bonuses"],
      "member_sentiment.ratings": ["Trustpilot: 3.4/5", "Reddit r/marriott: mixed"],
      "member_sentiment.common_praise": ["Broad property network", "Generous elite recognition"],
      "member_sentiment.common_complaints": ["Dynamic award pricing", "Inconsistent elite benefits"],
      "member_sentiment.sources_checked": ["FlyerTalk", "Reddit r/marriott", "Trustpilot"],
      "competitive_position.key_differentiators": ["Largest hotel footprint", "Broad transfer partners"],
      "competitive_position.weaknesses": ["Dynamic pricing erodes value", "Award availability at peaks"],
      "competitive_position.closest_competitors": ["Hilton Honors", "World of Hyatt", "IHG One Rewards"],
      "competitive_position.recent_changes_last_6_months": "Introduced points pooling and updated free-night certificates",
    },
  },
  {
    program_name: "Hilton Honors",
    brand: "Hilton",
    domain: "hilton.com",
    industry: "Hotel",
    category: "Hotel",
    parent: "Hilton Worldwide Holdings",
    geography: "Global",
    country: "United States",
    values: {
      "program_basics.program_name": "Hilton Honors",
      "program_basics.brand": "Hilton",
      "program_basics.industry": "Hotel",
      "program_basics.program_type": "points-based, tiered loyalty",
      "program_basics.geography": "Global (122 countries)",
      "program_basics.membership_count": "180 million members",
      "program_basics.ownership_or_parent_company": "Hilton Worldwide Holdings Inc.",
      "earn_mechanics.base_earn_rate": "10 base points per USD 1 at most hotels",
      "earn_mechanics.earn_rate_unit": "points per USD",
      "earn_mechanics.bonus_categories": ["Diamond: +100% bonus", "Co-brand card: up to 14x"],
      "earn_mechanics.non_transactional_earn": ["Surveys", "Dining program", "Credit card spend"],
      "burn_mechanics.redemption_options": ["Free nights", "Points + Money", "Amazon shopping", "Experiences"],
      "burn_mechanics.redemption_thresholds": "No published award chart; dynamic from ~5,000 points",
      "burn_mechanics.point_value_cpp": "0.50 cents per point",
      "burn_mechanics.expiry_policy": "Points expire after 24 months of inactivity",
      "tier_system.tier_names": ["Member", "Silver", "Gold", "Diamond"],
      "tier_system.qualification_criteria": ["Qualifying nights", "Qualifying stays", "Base points"],
      "tier_system.tier_thresholds": "Gold: 40 nights; Diamond: 60 nights",
      "tier_system.tier_benefits": ["Free breakfast", "Room upgrades", "5th night free on awards"],
      "tier_system.qualification_period": "Calendar year",
      "partnerships.partner_names": ["American Airlines", "Lyft", "Amazon", "Hertz"],
      "partnerships.partnership_type": "Airline earn + lifestyle + retail",
      "partnerships.details": "Points unusually do not transfer well to airlines (10:1)",
      "digital_experience.mobile_app_available": "Yes",
      "digital_experience.app_ratings": ["App Store: 4.9", "Google Play: 4.6"],
      "digital_experience.app_store_rating": "4.9 / 5 (App Store)",
      "digital_experience.play_store_rating": "4.6 / 5 (Google Play)",
      "digital_experience.personalization_features": ["Digital key", "Room selection", "Mobile check-in"],
      "digital_experience.gamification_features": ["Points Pooling", "Bonus point promotions"],
      "member_sentiment.ratings": ["Trustpilot: 2.9/5", "Reddit r/hilton: positive on app"],
      "member_sentiment.common_praise": ["Best-in-class app", "5th night free", "Free breakfast"],
      "member_sentiment.common_complaints": ["Low point value", "Poor airline transfers"],
      "member_sentiment.sources_checked": ["FlyerTalk", "Reddit r/hilton", "Trustpilot"],
      "competitive_position.key_differentiators": ["Top-rated mobile app", "Digital key adoption", "5th night free"],
      "competitive_position.weaknesses": ["Lowest point value among majors", "Weak transfer partners"],
      "competitive_position.closest_competitors": ["Marriott Bonvoy", "World of Hyatt", "IHG One Rewards"],
      "competitive_position.recent_changes_last_6_months": "Expanded points pooling limits and added new co-brand card tiers",
    },
  },
  {
    program_name: "Delta SkyMiles",
    brand: "Delta Air Lines",
    domain: "delta.com",
    industry: "Airline",
    category: "Airline",
    parent: "Delta Air Lines, Inc.",
    geography: "Global",
    country: "United States",
    values: {
      "program_basics.program_name": "Delta SkyMiles",
      "program_basics.brand": "Delta Air Lines",
      "program_basics.industry": "Airline",
      "program_basics.program_type": "miles-based, revenue-driven",
      "program_basics.geography": "Global (SkyTeam network)",
      "program_basics.membership_count": "120 million members",
      "earn_mechanics.base_earn_rate": "5 miles per USD 1 on Delta fares",
      "earn_mechanics.earn_rate_unit": "miles per USD",
      "burn_mechanics.point_value_cpp": "1.2 cents per mile",
      "tier_system.tier_names": ["Member", "Silver Medallion", "Gold Medallion", "Platinum Medallion", "Diamond Medallion"],
      "tier_system.tier_thresholds": "Diamond: 28,000 MQDs",
      "digital_experience.app_ratings": ["App Store: 4.8", "Google Play: 4.4"],
      "competitive_position.closest_competitors": ["United MileagePlus", "American AAdvantage"],
      "competitive_position.recent_changes_last_6_months": "Moved fully to spend-based MQD qualification",
    },
  },
];

export function pickProfile(userInput: string): ProgramProfile {
  const lower = userInput.toLowerCase();
  const match = PROFILES.find(
    (p) =>
      lower.includes(p.program_name.toLowerCase()) ||
      lower.includes(p.brand.toLowerCase()) ||
      lower.includes(p.domain.split(".")[0]),
  );
  return match ?? PROFILES[0];
}

export function pickSecondProfile(first: ProgramProfile, userInput?: string): ProgramProfile {
  if (userInput) {
    const lower = userInput.toLowerCase();
    const explicit = PROFILES.find(
      (p) =>
        p.program_name !== first.program_name &&
        (lower.includes(p.program_name.toLowerCase()) || lower.includes(p.brand.toLowerCase())),
    );
    if (explicit) return explicit;
  }
  return PROFILES.find((p) => p.program_name !== first.program_name) ?? PROFILES[1];
}

const SOURCE_TYPES = ["official", "review", "forum", "news", "financial"];

// ---- per-field outcome model ----

type FieldOutcome = "accepted" | "debated" | "review" | "missing" | "rejected";

interface FieldCell {
  field_path: string;
  category: string;
  outcome: FieldOutcome;
  value: unknown | null;
  confidence: number | null;
  source_urls: string[];
  snippet: string | null;
  corroboration: number;
}

function genericValueFor(profile: ProgramProfile, fieldPath: string, rng: () => number): unknown {
  const leaf = fieldLabel(fieldPath).toLowerCase();
  const cat = categoryOf(fieldPath);
  const arrayish = /names|options|features|partners|categories|sources|competitors|benefits|ratings|criteria|differentiators|weaknesses|risks|exclusions/.test(
    fieldPath,
  );
  if (arrayish) {
    const n = 2 + Math.floor(rng() * 2);
    return Array.from({ length: n }, (_, i) => `${CATEGORY_LABELS[cat]} ${leaf} #${i + 1}`);
  }
  return `${profile.program_name} ${leaf}`;
}

function buildCells(profile: ProgramProfile, urls: RetrievedUrl[], seed: string): FieldCell[] {
  const rng = makeRng(seed + ":cells");
  return SCHEMA_FIELD_PATHS.map((fieldPath, idx) => {
    const known = profile.values[fieldPath];
    const focused = FOCUSED_SCHEMA_FIELD_PATHS.has(fieldPath);
    const r = rng();

    let outcome: FieldOutcome;
    if (known !== undefined) {
      // known fields are mostly accepted, occasionally debated (volatile ones)
      outcome = volatilityFor(fieldPath) === "high" && r < 0.28 ? "debated" : "accepted";
    } else if (focused) {
      outcome = r < 0.55 ? "accepted" : r < 0.72 ? "debated" : r < 0.88 ? "review" : "missing";
    } else {
      outcome = r < 0.32 ? "accepted" : r < 0.45 ? "review" : r < 0.55 ? "rejected" : "missing";
    }

    const value =
      outcome === "missing"
        ? null
        : known !== undefined
          ? known
          : outcome === "rejected"
            ? null
            : genericValueFor(profile, fieldPath, rng);

    let confidence: number | null;
    switch (outcome) {
      case "accepted":
        confidence = 0.78 + rng() * 0.21;
        break;
      case "debated":
        confidence = 0.55 + rng() * 0.22;
        break;
      case "review":
        confidence = 0.28 + rng() * 0.24;
        break;
      case "rejected":
        confidence = 0;
        break;
      default:
        confidence = null;
    }

    const srcCount =
      outcome === "accepted" ? 1 + Math.floor(rng() * 3) : outcome === "debated" ? 2 : outcome === "review" ? 1 : 0;
    const source_urls = pickUrls(urls, srcCount, idx);

    return {
      field_path: fieldPath,
      category: categoryOf(fieldPath),
      outcome,
      value,
      confidence: confidence == null ? null : Number(confidence.toFixed(2)),
      source_urls,
      snippet:
        outcome === "missing"
          ? null
          : `"…${fieldLabel(fieldPath)} for ${profile.program_name} as stated in the source…"`,
      corroboration: srcCount,
    };
  });
}

function pickUrls(urls: RetrievedUrl[], count: number, salt: number): string[] {
  if (count <= 0 || urls.length === 0) return [];
  const out: string[] = [];
  for (let i = 0; i < count; i++) {
    out.push(urls[(salt * 7 + i * 13) % urls.length].url);
  }
  return Array.from(new Set(out));
}

function outcomeToClaimStatus(outcome: FieldOutcome): ClaimStatus {
  switch (outcome) {
    case "accepted":
      return "supported";
    case "debated":
      return "conflicting";
    case "review":
      return "not_found/manual_review_needed";
    case "rejected":
      return "rejected_unsupported";
    default:
      return "null";
  }
}

function outcomeToReportStatus(outcome: FieldOutcome): FieldReportEntry["status"] {
  switch (outcome) {
    case "accepted":
      return "extracted";
    case "debated":
      return "ambiguous";
    case "rejected":
      return "flagged";
    default:
      return "not_found";
  }
}

// ---- builders for each pipeline stage ----

function buildIdentity(profile: ProgramProfile, raw: string): ProgramIdentity {
  return {
    identity_id: `identity_${hash(profile.program_name)}`,
    raw_input: raw,
    program_name: profile.program_name,
    brand: profile.brand,
    domain: profile.domain,
    country_or_region: profile.country,
    confidence: 0.96,
    status: "resolved",
  };
}

function buildQueries(profile: ProgramProfile, seed: string): SearchQuery[] {
  const rng = makeRng(seed + ":q");
  const templates: Array<[string, string]> = [
    ["official", `${profile.program_name} earning and redemption terms`],
    ["official", `${profile.program_name} elite tier benefits site:${profile.domain}`],
    ["official", `${profile.brand} loyalty program annual members`],
    ["review", `${profile.program_name} app store rating reviews`],
    ["review", `${profile.program_name} Trustpilot member reviews`],
    ["forum", `${profile.program_name} FlyerTalk award value`],
    ["forum", `${profile.program_name} Reddit point value complaints`],
    ["news", `${profile.program_name} program changes ${new Date().getFullYear()}`],
    ["news", `${profile.brand} loyalty news devaluation`],
    ["financial", `${profile.parent} annual report loyalty deferred revenue`],
    ["official", `${profile.program_name} transfer partners list`],
    ["review", `${profile.program_name} customer service complaints`],
  ];
  return templates.map(([source_type, query], i) => ({
    query_id: `query_${hash(seed + i)}`,
    external_query_id: `Q${String(i + 1).padStart(2, "0")}`,
    query,
    source_type,
    intent: source_type === "official" ? "primary_terms" : `${source_type}_signal`,
    target_fields: SCHEMA_FIELD_PATHS.filter(() => rng() < 0.12).slice(0, 3),
  }));
}

function buildUrls(profile: ProgramProfile, queries: SearchQuery[], seed: string): RetrievedUrl[] {
  const rng = makeRng(seed + ":u");
  const hosts: Record<string, string[]> = {
    official: [profile.domain, `help.${profile.domain}`],
    review: ["trustpilot.com", "apps.apple.com", "play.google.com"],
    forum: ["flyertalk.com", "reddit.com", "thepointsguy.com"],
    news: ["skift.com", "reuters.com", "loyaltylobby.com"],
    financial: ["sec.gov", "investor." + profile.domain],
  };
  const urls: RetrievedUrl[] = [];
  queries.forEach((q) => {
    const pool = hosts[q.source_type] ?? ["example.com"];
    const n = 3 + Math.floor(rng() * 3);
    for (let i = 0; i < n; i++) {
      const host = pool[Math.floor(rng() * pool.length)];
      const slug = q.query.toLowerCase().replace(/[^a-z0-9]+/g, "-").slice(0, 40);
      const url = `https://${host}/${slug}-${i}`;
      urls.push({
        url,
        canonical_url: url.split("?")[0],
        title: `${profile.program_name} — ${q.source_type} result ${i + 1}`,
        score: Number((0.45 + rng() * 0.54).toFixed(2)),
        query: q.query,
        query_id: q.query_id,
        external_query_id: q.external_query_id,
        source_type: q.source_type,
      });
    }
  });
  return urls;
}

function buildBlocks(urls: RetrievedUrl[], profile: ProgramProfile, seed: string): ScrapedUrlBlock[] {
  const rng = makeRng(seed + ":b");
  return urls.map((u) => {
    const ok = rng() > 0.16;
    return {
      url: u.url,
      canonical_url: u.canonical_url,
      content: ok
        ? `# ${u.title}\n\n${profile.program_name} is operated by ${profile.brand}. The program offers points earning, tiered benefits, and partner redemptions. ${"Detailed evidence text. ".repeat(40)}`
        : null,
      title: u.title,
      scrape_status: ok ? "success" : "failed",
      error: ok ? null : rng() > 0.5 ? "HTTP 403 (blocked)" : "Timeout after 30s",
    };
  });
}

function buildChunks(
  blocks: ScrapedUrlBlock[],
  seed: string,
): { semantic: SemanticChunk[]; extraction: SemanticChunk[]; skipped: SemanticChunk[] } {
  const rng = makeRng(seed + ":c");
  const semantic: SemanticChunk[] = [];
  const extraction: SemanticChunk[] = [];
  const skipped: SemanticChunk[] = [];
  const good = blocks.filter((b) => b.scrape_status === "success");
  let n = 0;
  good.forEach((b) => {
    const count = 2 + Math.floor(rng() * 3);
    for (let i = 0; i < count; i++) {
      n += 1;
      const text = (b.content ?? "").slice(0, 600 + Math.floor(rng() * 1200));
      const chunk: SemanticChunk = {
        chunk_id: `chunk_${hash(seed + n)}`,
        chunk_text: text,
        source_url: b.url,
        target_fields: SCHEMA_FIELD_PATHS.filter(() => rng() < 0.08).slice(0, 4),
        source_type: null,
        token_count: estimateTokens(text),
      };
      semantic.push(chunk);
      // chunks scoring high enough go to extraction; low-signal ones get skipped
      if (rng() > 0.28) extraction.push(chunk);
      else skipped.push(chunk);
    }
  });
  return { semantic, extraction, skipped };
}

function buildPackets(
  cells: FieldCell[],
  chunks: SemanticChunk[],
  seed: string,
): { extracted: ExtractedObjectPacket[]; normalized: NormalizedObjectPacket[] } {
  const accepted = cells.filter((c) => c.outcome === "accepted" || c.outcome === "debated");
  const extracted: ExtractedObjectPacket[] = [];
  // group ~6 fields per packet
  for (let i = 0; i < accepted.length; i += 6) {
    const group = accepted.slice(i, i + 6);
    const chunk = chunks[i % Math.max(1, chunks.length)];
    const fields: Record<string, ExtractedField> = {};
    group.forEach((c) => {
      fields[c.field_path] = {
        value: c.value,
        status: c.outcome === "debated" ? "AMBIGUOUS" : "EXTRACTED",
        source_url: c.source_urls[0] ?? null,
        source_snippet: c.snippet,
        confidence: c.confidence,
      };
    });
    extracted.push({
      object_type: "loyalty_intelligence",
      fields,
      source_url: chunk?.source_url ?? "https://example.com",
      chunk_id: chunk?.chunk_id ?? `chunk_${i}`,
      scope: { batch: i / 6 },
    });
  }
  const normalized: NormalizedObjectPacket[] = extracted.map((p, i) => ({
    ...p,
    identity_hash: hash(seed + ":norm" + i),
    normalized_at: new Date().toISOString(),
  }));
  return { extracted, normalized };
}

function buildFieldReport(cells: FieldCell[], profile: ProgramProfile): FieldReport {
  const entries: FieldReportEntry[] = cells.map((c) => ({
    field_path: c.field_path,
    category: c.category,
    status: outcomeToReportStatus(c.outcome),
    value: c.value,
    source_urls: c.source_urls,
    source_snippet: c.snippet,
    confidence: c.confidence,
    corroboration_count: c.corroboration,
  }));
  return {
    entity_name: profile.program_name,
    generated_at: new Date().toISOString(),
    entries,
    extracted_count: entries.filter((e) => e.status === "extracted").length,
    ambiguous_count: entries.filter((e) => e.status === "ambiguous").length,
    not_found_count: entries.filter((e) => e.status === "not_found").length,
    flagged_count: entries.filter((e) => e.status === "flagged").length,
  };
}

function buildClaims(cells: FieldCell[], runId: string): Claim[] {
  return cells
    .filter((c) => c.outcome !== "missing")
    .map((c) => ({
      claim_id: `claim_${hash(runId + c.field_path)}`,
      run_id: runId,
      field_path: c.field_path,
      value_json: c.value,
      status: outcomeToClaimStatus(c.outcome),
      source_url: c.source_urls[0] ?? null,
      access_date: c.source_urls.length ? new Date().toISOString().slice(0, 10) : null,
      quote: c.snippet,
      confidence: c.confidence ?? 0,
      volatility: volatilityFor(c.field_path),
    }));
}

function buildConflicts(cells: FieldCell[], claims: Claim[], runId: string): ConflictRecord[] {
  const debated = cells.filter((c) => c.outcome === "debated");
  return debated.map((c, i) => {
    const claim = claims.find((cl) => cl.field_path === c.field_path);
    const gap = Number((0.05 + (i % 4) * 0.06).toFixed(2));
    const resolution: ConflictRecord["resolution_status"] =
      gap > 0.18 ? "manual_review_needed" : gap > 0.1 ? "debate_required" : "auto_resolved";
    return {
      conflict_id: `conflict_${hash(runId + c.field_path)}`,
      run_id: runId,
      field_path: c.field_path,
      claim_ids: claim ? [claim.claim_id, `claim_alt_${hash(c.field_path)}`] : [],
      score_gap: gap,
      resolution_status: resolution,
      judge_reason:
        resolution === "auto_resolved"
          ? "Higher-authority official source outweighs the conflicting forum claim."
          : resolution === "debate_required"
            ? "Two credible sources disagree; routed to adversarial debate."
            : "Sources conflict with no clear authority; escalated to human review.",
    };
  });
}

function buildDebate(
  conflicts: ConflictRecord[],
  labels: { a: string; b: string },
): { adjudicated: AdjudicatedClaim[]; review: HumanReviewItem[] } {
  const adjudicated: AdjudicatedClaim[] = [];
  const review: HumanReviewItem[] = [];

  conflicts.forEach((conflict) => {
    const rounds: DebateRound[] = [
      { round: 1, phase: "opening", agent: labels.a, argument: `${labels.a}: The official source for ${fieldLabel(conflict.field_path)} is authoritative and current.` },
      { round: 2, phase: "opening_b", agent: labels.b, argument: `${labels.b}: The community/forum evidence reflects the lived member reality, which differs from marketing copy.` },
      { round: 3, phase: "cross", agent: labels.a, argument: `${labels.a} (cross): The forum post predates the latest program update; recency favours the official value.` },
      { round: 4, phase: "cross_b", agent: labels.b, argument: `${labels.b} (cross): The official page omits the regional exception documented in the thread.` },
      { round: 5, phase: "evidence", agent: "Evidence Referee", argument: `Weighing source authority (${conflict.field_path}): official=0.9, forum=0.6, recency favours official.` },
      {
        round: 6,
        phase: "final_decision",
        agent: "Adjudicator",
        argument:
          conflict.resolution_status === "manual_review_needed"
            ? "No decisive winner — escalating to human review."
            : `Decision: accept the higher-authority claim (score gap ${conflict.score_gap.toFixed(2)}).`,
      },
    ];
    adjudicated.push({
      conflict_id: conflict.conflict_id,
      field_path: conflict.field_path,
      resolution_status: conflict.resolution_status,
      winning_claim_id:
        conflict.resolution_status === "manual_review_needed" ? null : conflict.claim_ids[0] ?? null,
      decision: rounds[5].argument,
      rounds,
      confidence: conflict.resolution_status === "manual_review_needed" ? 0.4 : 0.82,
      value_a: `${labels.a} reported value for ${fieldLabel(conflict.field_path)}`,
      value_b: `${labels.b} reported value for ${fieldLabel(conflict.field_path)}`,
      url_a: `https://${labels.a.toLowerCase().replace(/\s+/g, "")}.com/loyalty`,
      url_b: `https://${labels.b.toLowerCase().replace(/\s+/g, "")}.com/loyalty`,
    });
    if (conflict.resolution_status === "manual_review_needed") {
      review.push({
        field_path: conflict.field_path,
        reason: "Conflicting sources with no clear authority after debate.",
        claim_ids: conflict.claim_ids,
        score_gap: conflict.score_gap,
        flagged_at: new Date().toISOString(),
      });
    }
  });
  return { adjudicated, review };
}

function coverageFromCells(cells: FieldCell[]) {
  const supported = cells.filter((c) => c.outcome === "accepted" || c.outcome === "debated").length;
  const manual = cells.filter((c) => c.outcome === "review").length;
  const rejected = cells.filter((c) => c.outcome === "rejected").length;
  const nul = cells.filter((c) => c.outcome === "missing").length;
  return {
    total_fields: TOTAL_FIELDS,
    supported_fields: supported,
    manual_review_fields: manual,
    null_fields: nul,
    rejected_fields: rejected,
  };
}

function buildBriefText(profile: ProgramProfile, cells: FieldCell[]): string {
  const v = (p: string) => profile.values[p];
  const competitors = (v("competitive_position.closest_competitors") as string[] | undefined)?.join(", ");
  return [
    `## ${profile.program_name} — Loyalty Intelligence Brief`,
    "",
    `**Operator:** ${profile.brand} · **Industry:** ${profile.industry} · **Geography:** ${v("program_basics.geography") ?? profile.geography}`,
    "",
    `### Overview`,
    `${profile.program_name} is a ${v("program_basics.program_type") ?? "points-based"} program operated by ${profile.brand}, reporting ${v("program_basics.membership_count") ?? "a large member base"}. Members earn at a base rate of ${v("earn_mechanics.base_earn_rate") ?? "the published base rate"} with accelerators on co-brand spend and partner activity.`,
    "",
    `### Earn & Burn`,
    `The estimated point value is ${v("burn_mechanics.point_value_cpp") ?? "not disclosed"}, redeemable for ${(v("burn_mechanics.redemption_options") as string[] | undefined)?.join(", ") ?? "core redemption options"}. ${v("burn_mechanics.expiry_policy") ?? "Expiry terms apply on inactivity."}`,
    "",
    `### Elite Tiers`,
    `The tier ladder runs ${(v("tier_system.tier_names") as string[] | undefined)?.join(" → ") ?? "from entry to top tier"}, qualified by ${(v("tier_system.qualification_criteria") as string[] | undefined)?.join(", ") ?? "nights and spend"} over a ${v("tier_system.qualification_period") ?? "calendar year"}.`,
    "",
    `### Competitive Position`,
    `Key differentiators include ${(v("competitive_position.key_differentiators") as string[] | undefined)?.join(", ") ?? "scale and partner breadth"}. Closest competitors are ${competitors ?? "peer programs"}. Documented weaknesses: ${(v("competitive_position.weaknesses") as string[] | undefined)?.join(", ") ?? "value erosion risk"}.`,
    "",
    `_All claims above are grounded in retrieved sources; ${cells.filter((c) => c.outcome === "review").length} fields require manual review and ${cells.filter((c) => c.outcome === "missing").length} were not found._`,
  ].join("\n");
}

function hash(input: string | number): string {
  let h = 5381;
  const s = String(input);
  for (let i = 0; i < s.length; i++) h = (h * 33) ^ s.charCodeAt(i);
  return (h >>> 0).toString(16).padStart(8, "0");
}

// ---- public: build a complete single-program AgentState ----

export function buildFullState(
  runId: string,
  userInput: string,
  mode: AgentState["mode"],
  profile: ProgramProfile,
  createdAt: string,
): AgentState {
  const seed = runId;
  const identity = buildIdentity(profile, userInput);
  const queries = buildQueries(profile, seed);
  const urls = buildUrls(profile, queries, seed);
  const blocks = buildBlocks(urls, profile, seed);
  const { semantic, extraction, skipped } = buildChunks(blocks, seed);
  const cells = buildCells(profile, urls, seed);
  const { extracted, normalized } = buildPackets(cells, extraction, seed);
  const fieldReport = buildFieldReport(cells, profile);
  const claims = buildClaims(cells, runId);
  const conflicts = buildConflicts(cells, claims, runId);
  const { adjudicated, review } = buildDebate(conflicts, { a: "Advocate A", b: "Advocate B" });
  const coverage = coverageFromCells(cells);
  const dataQuality = Number(
    ((coverage.supported_fields + coverage.manual_review_fields * 0.3) / coverage.total_fields).toFixed(2),
  );

  const successful = blocks.filter((b) => b.scrape_status === "success").length;
  const allTokens = semantic.reduce((sum, c) => sum + (c.token_count ?? 0), 0);

  const errors: PipelineError[] = blocks
    .filter((b) => b.scrape_status === "failed")
    .slice(0, 2)
    .map((b) => ({ stage: "firecrawl_scraper", message: `${b.error} — ${b.url}`, created_at: new Date().toISOString() }));

  const supportedClaimIds = claims.filter((c) => c.status === "supported").map((c) => c.claim_id);
  const briefText = buildBriefText(profile, cells);

  return {
    run_id: runId,
    mode,
    user_input: userInput,
    validation_messages: [
      { role: "user", content: userInput },
      { role: "assistant", content: `Resolved to ${profile.program_name} (${profile.brand}).` },
    ],
    validation_result: {
      status: "resolved",
      confidence: identity.confidence,
      identity,
      possible_matches: [],
      follow_up_questions: [],
      reason: null,
    },
    program_identity: identity,
    program_name: profile.program_name,
    brand: profile.brand,
    domain: profile.domain,
    country_or_region: profile.country,
    query_generation_result: {
      detected_category: profile.category,
      resolved_corporate_parent: profile.parent,
      geography: profile.geography,
      query_strategy_summary: `Prioritise official ${profile.domain} terms, corroborate with review/forum sentiment, and cross-check program changes against news and financial filings.`,
      priority_fields: [
        "earn_mechanics.base_earn_rate",
        "burn_mechanics.point_value_cpp",
        "tier_system.tier_thresholds",
        "partnerships.partner_names",
      ],
      estimated_web_coverage: 0.82,
      field_query_map: queries.reduce<Record<string, string[]>>((acc, q) => {
        q.target_fields.forEach((f) => {
          acc[f] = acc[f] ?? [];
          acc[f].push(q.external_query_id ?? q.query_id);
        });
        return acc;
      }, {}),
      queries,
    },
    search_queries: queries,
    retrieval_result: {
      total_queries: queries.length,
      requested_results_per_query: 5,
      raw_result_count: urls.length,
      unique_result_count: new Set(urls.map((u) => u.canonical_url)).size,
      urls,
    },
    retrieved_urls: urls,
    firecrawl_result: {
      total_urls: blocks.length,
      successful_scrapes: successful,
      failed_scrapes: blocks.length - successful,
      blocks,
    },
    scraped_blocks: blocks,
    raw_documents: blocks
      .filter((b) => b.scrape_status === "success")
      .map((b) => ({
        url: b.url,
        url_hash: hash(b.url),
        content: b.content ?? "",
        word_count: (b.content ?? "").split(/\s+/).length,
        query_id: null,
        entity_name: profile.program_name,
        domain: profile.domain,
        retrieved_at: new Date().toISOString(),
        source_authority: Number((0.5 + Math.random() * 0.4).toFixed(2)),
        metadata: {},
      })),
    semantic_chunks: semantic,
    extraction_chunks: extraction,
    skipped_chunks: skipped,
    schema_config: { object_type: "loyalty_intelligence", field_count: TOTAL_FIELDS, total_tokens: allTokens },
    extracted_packets: extracted,
    normalized_packets: normalized,
    field_report: fieldReport,
    extracted_claims: claims,
    conflicts,
    adjudicated,
    human_review_queue: review,
    adjudicated_claims: claims.filter((c) => c.status === "supported" || c.status === "conflicting"),
    schema_coverage: coverage,
    data_quality: dataQuality,
    final_brief: {
      brief_id: `brief_${hash(runId)}`,
      run_id: runId,
      brief_text: briefText,
      cited_claim_ids: supportedClaimIds.slice(0, 12),
      word_count: briefText.split(/\s+/).length,
      entailment_passed: true,
      unsupported_sentences: [],
    },
    comparison_output: null,
    conversation_answer: null,
    errors,
    created_at: createdAt,
    updated_at: createdAt,
    stage_status: {},
    active_stage: null,
    status: "running",
    conversation: [],
  };
}

// ---- comparison overlay ----

const OUTCOME_BY_DELTA = (a: FieldCell, b: FieldCell): ComparisonOutcome => {
  const aHas = a.outcome !== "missing" && a.outcome !== "rejected";
  const bHas = b.outcome !== "missing" && b.outcome !== "rejected";
  if (!aHas && !bHas) return "null";
  if (!aHas) return "missing_in_a";
  if (!bHas) return "missing_in_b";
  if (a.outcome === "review" || b.outcome === "review") return "manual_review_needed";
  const same = JSON.stringify(a.value) === JSON.stringify(b.value);
  return same ? "match" : "factual_mismatch";
};

export function buildComparison(
  runId: string,
  stateA: AgentState,
  stateB: AgentState,
): ComparisonOutput {
  const cellsA = reconstructCells(stateA);
  const cellsB = reconstructCells(stateB);
  const items: ComparisonItem[] = SCHEMA_FIELD_PATHS.map((fp) => {
    const a = cellsA.get(fp)!;
    const b = cellsB.get(fp)!;
    const outcome = OUTCOME_BY_DELTA(a, b);
    return {
      field_path: fp,
      outcome,
      summary:
        outcome === "match"
          ? "Both programs report equivalent values."
          : outcome === "factual_mismatch"
            ? `A reports "${truncateVal(a.value)}" vs B "${truncateVal(b.value)}".`
            : outcome === "missing_in_a"
              ? `Only ${stateB.program_name} has data for this field.`
              : outcome === "missing_in_b"
                ? `Only ${stateA.program_name} has data for this field.`
                : outcome === "manual_review_needed"
                  ? "Conflicting low-confidence data on one side; needs review."
                  : "Neither program had retrievable data.",
      claim_ids: [],
    };
  });
  return {
    comparison_id: `comparison_${hash(runId)}`,
    run_id: runId,
    program_a: stateA.program_name ?? "Program A",
    program_b: stateB.program_name ?? "Program B",
    items,
  };
}

function truncateVal(v: unknown): string {
  const s = Array.isArray(v) ? v.join(", ") : String(v ?? "—");
  return s.length > 40 ? s.slice(0, 39) + "…" : s;
}

/** Recover the per-field cell view from a built state's field_report + claims. */
function reconstructCells(state: AgentState): Map<string, FieldCell> {
  const map = new Map<string, FieldCell>();
  const claims = new Map(state.extracted_claims.map((c) => [c.field_path, c]));
  (state.field_report?.entries ?? []).forEach((e) => {
    const claim = claims.get(e.field_path);
    const outcome: FieldOutcome =
      e.status === "extracted"
        ? "accepted"
        : e.status === "ambiguous"
          ? "debated"
          : e.status === "flagged"
            ? "rejected"
            : claim?.status === "null" || claim == null
              ? "missing"
              : "review";
    map.set(e.field_path, {
      field_path: e.field_path,
      category: e.category,
      outcome,
      value: e.value,
      confidence: e.confidence,
      source_urls: e.source_urls,
      snippet: e.source_snippet,
      corroboration: e.corroboration_count,
    });
  });
  return map;
}

export { SOURCE_TYPES };
