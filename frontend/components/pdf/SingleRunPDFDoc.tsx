import React from 'react';
import { Document, Page, View, Text, Link, StyleSheet } from '@react-pdf/renderer';
import type { AgentState, FieldReportEntry } from '@/lib/types';
import {
  CATEGORY_ORDER, CATEGORY_LABELS, FOCUSED_SCHEMA_FIELD_PATHS, fieldLabel, type Category,
} from '@/lib/schema';
import { renderValue } from '@/lib/format';

// ── Brand colours ─────────────────────────────────────────────────────────────

const C = {
  navy:      '#0B2A4A',
  teal:      '#009898',
  green:     '#16A34A',
  amber:     '#D97706',
  red:       '#DC2626',
  ink:       '#1A2332',
  inkMid:    '#374151',
  inkLight:  '#6B7280',
  inkFaint:  '#9CA3AF',
  softGrey:  '#F9FAFB',
  softGrey2: '#F1F3F5',
  line:      '#E5E7EB',
  white:     '#FFFFFF',
} as const;

// ── Stylesheet ────────────────────────────────────────────────────────────────

const s = StyleSheet.create({
  page: {
    fontFamily: 'Helvetica',
    fontSize: 9,
    color: C.ink,
    paddingTop: 44,
    paddingBottom: 52,
    paddingLeft: 44,
    paddingRight: 44,
    backgroundColor: C.white,
  },
  footer: {
    position: 'absolute',
    bottom: 20,
    left: 44,
    right: 44,
    flexDirection: 'row',
    justifyContent: 'space-between',
    borderTopWidth: 0.5,
    borderTopColor: C.line,
    paddingTop: 5,
  },
  footerText: { fontSize: 6.5, color: C.inkFaint },

  heroBlock: {
    backgroundColor: C.navy,
    borderRadius: 7,
    paddingTop: 26,
    paddingBottom: 26,
    paddingLeft: 28,
    paddingRight: 28,
    marginBottom: 16,
  },
  heroTag:     { fontSize: 7, fontFamily: 'Helvetica-Bold', color: C.teal, letterSpacing: 2, marginBottom: 10 },
  heroTitle:   { fontSize: 24, fontFamily: 'Helvetica-Bold', color: C.white, marginBottom: 4 },
  heroBrand:   { fontSize: 11, color: '#94A3B8', marginBottom: 2 },
  heroCountry: { fontSize: 9.5, color: '#64748B' },

  metaRow:  { flexDirection: 'row', marginBottom: 14 },
  metaCard: {
    flex: 1,
    backgroundColor: C.softGrey,
    borderRadius: 5,
    paddingTop: 8,
    paddingBottom: 8,
    paddingLeft: 10,
    paddingRight: 10,
    marginRight: 8,
    borderLeftWidth: 2.5,
    borderLeftColor: C.teal,
  },
  metaLabel: { fontSize: 6.5, fontFamily: 'Helvetica-Bold', color: C.inkFaint, letterSpacing: 0.8, marginBottom: 3 },
  metaValue: { fontSize: 10, fontFamily: 'Helvetica-Bold', color: C.navy },

  sectionHeader: {
    fontSize: 12,
    fontFamily: 'Helvetica-Bold',
    color: C.navy,
    marginTop: 20,
    marginBottom: 8,
    paddingBottom: 4,
    borderBottomWidth: 1.5,
    borderBottomColor: C.teal,
  },

  coverageRow:  { flexDirection: 'row', marginBottom: 8 },
  coverageCard: {
    flex: 1,
    backgroundColor: C.softGrey,
    borderRadius: 5,
    paddingTop: 10,
    paddingBottom: 10,
    paddingLeft: 10,
    paddingRight: 10,
    marginRight: 8,
    borderLeftWidth: 3,
    borderLeftColor: C.teal,
  },
  coverageCatLabel: { fontSize: 6.5, fontFamily: 'Helvetica-Bold', color: C.inkLight, letterSpacing: 0.5, marginBottom: 4 },
  coveragePct:      { fontSize: 14, fontFamily: 'Helvetica-Bold', color: C.navy, marginBottom: 1 },
  coverageSub:      { fontSize: 7, color: C.inkFaint },

  catBanner: {
    backgroundColor: C.navy,
    borderRadius: 4,
    paddingTop: 4,
    paddingBottom: 4,
    paddingLeft: 8,
    paddingRight: 8,
    marginTop: 14,
    marginBottom: 0,
  },
  catBannerText: { fontSize: 7.5, fontFamily: 'Helvetica-Bold', color: C.white, letterSpacing: 0.5 },

  fieldRow: {
    flexDirection: 'row',
    borderBottomWidth: 0.5,
    borderBottomColor: C.line,
    paddingTop: 6,
    paddingBottom: 6,
    paddingLeft: 4,
    paddingRight: 4,
  },
  fieldRowAlt:    { backgroundColor: C.softGrey },
  fieldNameCol:   { width: '32%', paddingRight: 8 },
  fieldName:      { fontSize: 8, fontFamily: 'Helvetica-Bold', color: C.navy, marginBottom: 2 },
  fieldStatusTag: { fontSize: 6.5, color: C.amber },
  fieldValueCol:  { flex: 1 },
  fieldValue:     { fontSize: 8.5, color: C.inkMid, lineHeight: 1.4, marginBottom: 3 },
  fieldMeta:      { fontSize: 7, color: C.inkFaint, marginBottom: 3 },
  sourcesLabel:   { fontSize: 6.5, fontFamily: 'Helvetica-Bold', color: C.inkLight, marginTop: 2, marginBottom: 1.5 },
  sourceLink:     { fontSize: 7, color: C.teal, textDecoration: 'underline', marginBottom: 1.5 },

  gapRow: {
    flexDirection: 'row',
    paddingTop: 5,
    paddingBottom: 5,
    paddingLeft: 4,
    paddingRight: 4,
    borderBottomWidth: 0.5,
    borderBottomColor: C.line,
  },
  gapName:   { flex: 1, fontSize: 8.5, color: C.inkLight },
  gapStatus: { fontSize: 8, color: C.amber, width: 130, textAlign: 'right' },

  disclaimer:     { marginTop: 20, paddingTop: 10, borderTopWidth: 0.5, borderTopColor: C.line },
  disclaimerText: { fontSize: 6.5, color: C.inkFaint, lineHeight: 1.5 },
});

// ── Helpers ───────────────────────────────────────────────────────────────────

function domainOf(url: string): string {
  try { return new URL(url).hostname.replace(/^www\./, ''); } catch { return url; }
}

function confColor(conf: number | null | undefined): string {
  if (conf == null) return C.inkFaint;
  if (conf >= 0.80) return C.green;
  if (conf >= 0.60) return C.teal;
  return C.amber;
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '—';
  return d.toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' });
}

// ── Field row — extracted as component so it can be reused without duplication ─

function FieldRowView({ entry, rowIdx }: { entry: FieldReportEntry; rowIdx: number }) {
  const valStr  = String(renderValue(entry.value) ?? '—').slice(0, 520);
  const confPct = entry.confidence != null ? Math.round(entry.confidence * 100) : null;
  return (
    <View style={[s.fieldRow, rowIdx % 2 === 1 ? s.fieldRowAlt : {}]}>
      <View style={s.fieldNameCol}>
        <Text style={s.fieldName}>{fieldLabel(entry.field_path)}</Text>
        {entry.status === 'ambiguous' && (
          <Text style={s.fieldStatusTag}>Ambiguous</Text>
        )}
      </View>
      <View style={s.fieldValueCol}>
        <Text style={s.fieldValue}>{valStr}</Text>
        {entry.conflict_type && entry.conflict_type !== 'contradictory' && entry.all_values && entry.all_values.length > 1 && (
          <Text style={[s.fieldMeta, { color: '#0f7c7d', fontStyle: 'italic' }]}>
            {`[${entry.conflict_type}] ` + entry.all_values.map(av => av.context ? `${av.context}: ${av.value}` : av.value).join('  ·  ')}
          </Text>
        )}
        {confPct != null && (
          <Text style={[s.fieldMeta, { color: confColor(entry.confidence) }]}>
            {`Confidence: ${confPct}%`}
            {entry.corroboration_count > 1 ? `  ·  ${entry.corroboration_count}× corroborated` : ''}
          </Text>
        )}
        {entry.source_urls && entry.source_urls.length > 0 && (
          <View>
            <Text style={s.sourcesLabel}>SOURCES</Text>
            {entry.source_urls.slice(0, 5).map((url, i) => (
              <Link key={i} src={url} style={s.sourceLink}>
                {`${i + 1}. ${domainOf(url)}  —  ${url.length > 90 ? url.slice(0, 87) + '…' : url}`}
              </Link>
            ))}
          </View>
        )}
      </View>
    </View>
  );
}

// ── Component ─────────────────────────────────────────────────────────────────

interface Props { state: AgentState }

export function SingleRunPDFDoc({ state }: Props) {
  const entries: FieldReportEntry[] = state.field_report?.entries ?? [];
  const focused = entries.filter(e => FOCUSED_SCHEMA_FIELD_PATHS.has(e.field_path));

  const programName   = state.program_name ?? state.user_input;
  const runIdShort    = state.run_id.replace(/^run_/, '').slice(0, 12);
  const analysisDate  = fmtDate(state.updated_at ?? state.created_at);
  const generatedDate = fmtDate(new Date().toISOString());
  const quality       = Math.round((state.data_quality ?? 0) * 100);
  const fr            = state.field_report;
  const totalFields   = (fr?.extracted_count ?? 0) + (fr?.ambiguous_count ?? 0) + (fr?.not_found_count ?? 0);

  const coverageStats = CATEGORY_ORDER.map(cat => {
    const cf  = focused.filter(e => e.field_path.startsWith(cat + '.'));
    const ext = cf.filter(e => e.status === 'extracted').length;
    const tot = cf.length;
    return { cat, label: CATEGORY_LABELS[cat as Category], ext, tot, pct: tot > 0 ? Math.round((ext / tot) * 100) : 0 };
  }).filter(s => s.tot > 0);

  const extractedByCat = CATEGORY_ORDER.map(cat => {
    const fields = focused.filter(
      e => e.field_path.startsWith(cat + '.') && (e.status === 'extracted' || e.status === 'ambiguous')
    );
    return { cat, label: CATEGORY_LABELS[cat as Category], fields };
  }).filter(g => g.fields.length > 0);

  const gaps = focused.filter(e => e.status === 'not_found');

  // Coverage rows: 4 cards per row
  const covRows: typeof coverageStats[] = [];
  for (let i = 0; i < coverageStats.length; i += 4) covRows.push(coverageStats.slice(i, i + 4));

  return (
    <Document title={`Analysis Report – ${programName}`} author="Kobi Intelligence Platform">
      <Page size="A4" style={s.page}>

        {/* Fixed footer on every page */}
        <View style={s.footer} fixed>
          <Text style={s.footerText}>
            Kobi Intelligence Platform · Run: {runIdShort} · Generated: {generatedDate}
          </Text>
          <Text
            style={s.footerText}
            render={({ pageNumber, totalPages }: { pageNumber: number; totalPages: number }) =>
              `Page ${pageNumber} of ${totalPages}`
            }
          />
        </View>

        {/* ── Cover: hero + meta kept together so they never split ── */}
        <View wrap={false}>
          <View style={s.heroBlock}>
            <Text style={s.heroTag}>ANALYSIS REPORT</Text>
            <Text style={s.heroTitle}>{programName}</Text>
            {state.brand && state.brand !== programName && (
              <Text style={s.heroBrand}>{state.brand}</Text>
            )}
            {state.country_or_region && (
              <Text style={s.heroCountry}>{state.country_or_region}</Text>
            )}
          </View>

          <View style={s.metaRow}>
            {[
              { label: 'RUN ID',           value: runIdShort,    fs: 8.5 },
              { label: 'ANALYSIS DATE',    value: analysisDate,  fs: 8.5 },
              { label: 'GENERATED',        value: generatedDate, fs: 8.5 },
              { label: 'DATA QUALITY',     value: `${quality}%`, fs: 11,
                color: quality >= 70 ? C.green : quality >= 40 ? C.amber : C.red },
              { label: 'FIELDS EXTRACTED', value: `${fr?.extracted_count ?? 0} / ${totalFields}`, fs: 11 },
            ].map((m, i, arr) => (
              <View key={m.label} style={[s.metaCard, i === arr.length - 1 ? { marginRight: 0 } : {}]}>
                <Text style={s.metaLabel}>{m.label}</Text>
                <Text style={[s.metaValue, { fontSize: m.fs, color: m.color ?? C.navy }]}>{m.value}</Text>
              </View>
            ))}
          </View>
        </View>

        {/* ── Coverage by category ── */}
        {coverageStats.length > 0 && (
          <View>
            {/* Section header + first row kept together */}
            <View wrap={false}>
              <Text style={s.sectionHeader}>Coverage by Category</Text>
              {covRows[0] && (
                <View style={s.coverageRow}>
                  {covRows[0].map(({ cat, label, ext, tot, pct }, ci) => (
                    <View
                      key={cat}
                      style={[
                        s.coverageCard,
                        ci === covRows[0].length - 1 ? { marginRight: 0 } : {},
                        { borderLeftColor: pct >= 80 ? C.green : pct >= 50 ? C.teal : C.amber },
                      ]}
                    >
                      <Text style={s.coverageCatLabel}>{label.toUpperCase()}</Text>
                      <Text style={s.coveragePct}>{pct}%</Text>
                      <Text style={s.coverageSub}>{ext} of {tot} fields</Text>
                    </View>
                  ))}
                  {Array.from({ length: 4 - covRows[0].length }).map((_, pi) => (
                    <View key={`pad-${pi}`} style={{ flex: 1, marginRight: pi < 4 - covRows[0].length - 1 ? 8 : 0 }} />
                  ))}
                </View>
              )}
            </View>
            {/* Remaining rows flow naturally */}
            {covRows.slice(1).map((row, ri) => (
              <View key={ri} style={s.coverageRow} wrap={false}>
                {row.map(({ cat, label, ext, tot, pct }, ci) => (
                  <View
                    key={cat}
                    style={[
                      s.coverageCard,
                      ci === row.length - 1 ? { marginRight: 0 } : {},
                      { borderLeftColor: pct >= 80 ? C.green : pct >= 50 ? C.teal : C.amber },
                    ]}
                  >
                    <Text style={s.coverageCatLabel}>{label.toUpperCase()}</Text>
                    <Text style={s.coveragePct}>{pct}%</Text>
                    <Text style={s.coverageSub}>{ext} of {tot} fields</Text>
                  </View>
                ))}
                {Array.from({ length: 4 - row.length }).map((_, pi) => (
                  <View key={`pad-${pi}`} style={{ flex: 1, marginRight: pi < 4 - row.length - 1 ? 8 : 0 }} />
                ))}
              </View>
            ))}
          </View>
        )}

        {/* ── Extracted intelligence ── */}
        {extractedByCat.length > 0 && (
          <View>
            {/* Section header anchored to first category banner */}
            <View wrap={false}>
              <Text style={s.sectionHeader}>Extracted Intelligence</Text>
              {/* First category banner + its first row — prevents orphan header at page bottom */}
              {extractedByCat[0] && (
                <View>
                  <View style={s.catBanner}>
                    <Text style={s.catBannerText}>{extractedByCat[0].label.toUpperCase()}</Text>
                  </View>
                  {extractedByCat[0].fields[0] && (
                    <FieldRowView entry={extractedByCat[0].fields[0]} rowIdx={0} />
                  )}
                </View>
              )}
            </View>
            {/* Remaining rows of first category */}
            {extractedByCat[0]?.fields.slice(1).map((entry, i) => (
              <View key={entry.field_path} wrap={false}>
                <FieldRowView entry={entry} rowIdx={i + 1} />
              </View>
            ))}

            {/* Remaining categories: banner anchored to first row */}
            {extractedByCat.slice(1).map(({ cat, label, fields }) => (
              <View key={cat}>
                {/* Banner + first row together → no orphan banner */}
                <View wrap={false}>
                  <View style={s.catBanner}>
                    <Text style={s.catBannerText}>{label.toUpperCase()}</Text>
                  </View>
                  {fields[0] && <FieldRowView entry={fields[0]} rowIdx={0} />}
                </View>
                {/* Subsequent rows: each stays on one page */}
                {fields.slice(1).map((entry, i) => (
                  <View key={entry.field_path} wrap={false}>
                    <FieldRowView entry={entry} rowIdx={i + 1} />
                  </View>
                ))}
              </View>
            ))}
          </View>
        )}

        {/* ── Data gaps ── */}
        {gaps.length > 0 && (
          <View>
            <View wrap={false}>
              <Text style={s.sectionHeader}>Data Gaps — Fields Not Found</Text>
              {/* First gap row anchored to header */}
              {gaps[0] && (
                <View style={[s.gapRow, { backgroundColor: C.softGrey }]}>
                  <Text style={s.gapName}>{fieldLabel(gaps[0].field_path)}</Text>
                  <Text style={s.gapStatus}>Not found during analysis</Text>
                </View>
              )}
            </View>
            <View style={{ backgroundColor: C.softGrey, borderRadius: 5, paddingTop: 0, paddingBottom: 4 }}>
              {gaps.slice(1).map((entry, i) => (
                <View
                  key={entry.field_path}
                  style={[s.gapRow, (i + 1) % 2 === 1 ? { backgroundColor: C.softGrey2 } : {}]}
                  wrap={false}
                >
                  <Text style={s.gapName}>{fieldLabel(entry.field_path)}</Text>
                  <Text style={s.gapStatus}>Not found during analysis</Text>
                </View>
              ))}
            </View>
          </View>
        )}

        {/* ── Disclaimer ── */}
        <View style={s.disclaimer} wrap={false}>
          <Text style={s.disclaimerText}>
            {`This report was generated automatically by the Kobi Intelligence Platform on ${generatedDate}. All data points are sourced from publicly available information as of the analysis date (${analysisDate}). Confidence scores reflect cross-source corroboration quality. High-volatility fields (earn rates, tier thresholds, app ratings) change frequently — verify before use. Source URLs are provided for each extracted data point to enable independent verification.`}
          </Text>
        </View>

      </Page>
    </Document>
  );
}
