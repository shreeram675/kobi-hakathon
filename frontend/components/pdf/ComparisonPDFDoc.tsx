import React from 'react';
import { Document, Page, View, Text, Link, StyleSheet } from '@react-pdf/renderer';
import type {
  AgentState,
  ComparisonBrief,
  FieldReportEntry,
  CategoryVerdict,
  ProgramStrategicProfile,
} from '@/lib/types';
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

const PROG_COLORS = ['#009898', '#1D4ED8', '#0B2A4A', '#16A34A', '#D97706'] as const;
const PROG_BG     = ['#E6F7F7', '#EFF6FF', '#E8EEF5', '#ECFDF5', '#FEF9EC'] as const;

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
    paddingTop: 24,
    paddingBottom: 24,
    paddingLeft: 28,
    paddingRight: 28,
    marginBottom: 16,
  },
  heroTag:   { fontSize: 7, fontFamily: 'Helvetica-Bold', color: C.teal, letterSpacing: 2, marginBottom: 10 },
  heroTitle: { fontSize: 20, fontFamily: 'Helvetica-Bold', color: C.white, marginBottom: 12, lineHeight: 1.3 },
  progPill: {
    borderRadius: 4,
    paddingTop: 3,
    paddingBottom: 3,
    paddingLeft: 8,
    paddingRight: 8,
    marginRight: 6,
    marginBottom: 4,
  },
  progPillText: { fontSize: 8, fontFamily: 'Helvetica-Bold' },

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
  subHeader: {
    fontSize: 10,
    fontFamily: 'Helvetica-Bold',
    color: C.navy,
    marginTop: 14,
    marginBottom: 6,
  },

  qualityRow:  { flexDirection: 'row', marginBottom: 8 },
  qualityCard: {
    flex: 1,
    borderRadius: 6,
    borderWidth: 0.5,
    borderColor: C.line,
    paddingTop: 12,
    paddingBottom: 12,
    paddingLeft: 14,
    paddingRight: 14,
    marginRight: 8,
    backgroundColor: C.white,
  },
  qualitySlot:  { fontSize: 6.5, fontFamily: 'Helvetica-Bold', letterSpacing: 0.5, marginBottom: 3 },
  qualityName:  { fontSize: 9.5, fontFamily: 'Helvetica-Bold', color: C.navy, marginBottom: 6 },
  qualityScore: { fontSize: 20, fontFamily: 'Helvetica-Bold' },
  qualitySub:   { fontSize: 7, color: C.inkFaint, marginTop: 2 },

  execBox: {
    backgroundColor: '#EBF8F8',
    borderRadius: 6,
    borderLeftWidth: 4,
    borderLeftColor: C.teal,
    paddingTop: 12,
    paddingBottom: 12,
    paddingLeft: 14,
    paddingRight: 14,
    marginBottom: 14,
  },
  execTag:     { fontSize: 7, fontFamily: 'Helvetica-Bold', color: C.teal, letterSpacing: 1, marginBottom: 6 },
  execWinner:  { fontSize: 9, fontFamily: 'Helvetica-Bold', color: C.navy, marginBottom: 6 },
  execSummary: { fontSize: 9, color: C.inkMid, lineHeight: 1.5 },

  verdictRow:  { flexDirection: 'row', marginBottom: 8 },
  verdictCard: {
    flex: 1,
    backgroundColor: C.softGrey,
    borderRadius: 5,
    borderWidth: 0.5,
    borderColor: C.line,
    paddingTop: 10,
    paddingBottom: 10,
    paddingLeft: 10,
    paddingRight: 10,
    marginRight: 8,
  },
  verdictCatLabel: { fontSize: 6.5, fontFamily: 'Helvetica-Bold', color: C.inkFaint, letterSpacing: 0.5, marginBottom: 4 },
  verdictWinner:   { fontSize: 9, fontFamily: 'Helvetica-Bold', color: C.navy, marginBottom: 3 },
  verdictInsight:  { fontSize: 7.5, color: C.inkMid, lineHeight: 1.4, marginBottom: 4 },
  verdictLink:     { fontSize: 6.5, color: C.teal, textDecoration: 'underline', marginBottom: 1 },

  diffRow: {
    flexDirection: 'row',
    borderBottomWidth: 0.5,
    borderBottomColor: C.line,
    paddingTop: 8,
    paddingBottom: 8,
    paddingLeft: 4,
    paddingRight: 4,
  },
  diffRowAlt:     { backgroundColor: C.softGrey },
  diffContent:    { flex: 1, paddingRight: 12 },
  diffTopic:      { fontSize: 8.5, fontFamily: 'Helvetica-Bold', color: C.navy, marginBottom: 2 },
  diffInsight:    { fontSize: 8.5, color: C.inkMid, lineHeight: 1.4, marginBottom: 3 },
  diffNote:       { fontSize: 7.5, color: C.amber, lineHeight: 1.3, marginBottom: 3 },
  diffSourceLine: { fontSize: 6.5, color: C.teal, textDecoration: 'underline', marginBottom: 1 },
  diffAdvantage:  { fontSize: 8, fontFamily: 'Helvetica-Bold', width: 80, textAlign: 'right', marginTop: 2 },

  profileBlock: {
    borderWidth: 0.5,
    borderColor: C.line,
    borderRadius: 6,
    marginRight: 8,
    marginBottom: 8,
    overflow: 'hidden',
  },
  profileHeader: {
    flexDirection: 'row',
    paddingTop: 6,
    paddingBottom: 6,
    paddingLeft: 10,
    paddingRight: 10,
    borderBottomWidth: 0.5,
    borderBottomColor: C.line,
  },
  profileLetter: {
    fontSize: 8,
    fontFamily: 'Helvetica-Bold',
    width: 18,
    height: 18,
    borderRadius: 9,
    textAlign: 'center',
    paddingTop: 4,
    marginRight: 6,
  },
  profileName: { fontSize: 8.5, fontFamily: 'Helvetica-Bold', color: C.navy, flex: 1, marginTop: 3 },
  profileCols: { flexDirection: 'row' },
  profileCol:  { flex: 1, paddingTop: 8, paddingBottom: 8, paddingLeft: 8, paddingRight: 8 },
  profileColLabel: { fontSize: 6.5, fontFamily: 'Helvetica-Bold', letterSpacing: 0.5, marginBottom: 4 },
  profileItem: { fontSize: 7.5, color: C.inkMid, lineHeight: 1.4, marginBottom: 2 },

  personaCard: {
    flex: 1,
    borderRadius: 5,
    borderWidth: 0.5,
    borderColor: C.line,
    paddingTop: 10,
    paddingBottom: 10,
    paddingLeft: 10,
    paddingRight: 10,
    marginRight: 8,
  },
  personaProgram: { fontSize: 7, fontFamily: 'Helvetica-Bold', letterSpacing: 0.5, marginBottom: 4 },
  personaBestFor: { fontSize: 8.5, color: C.inkMid, lineHeight: 1.4 },

  // Field table (2-program)
  tableHeader: {
    flexDirection: 'row',
    backgroundColor: C.navy,
    paddingTop: 5,
    paddingBottom: 5,
    paddingLeft: 6,
    paddingRight: 6,
    borderRadius: 4,
    marginBottom: 1,
  },
  tableHeaderCell: { fontSize: 7.5, fontFamily: 'Helvetica-Bold', color: C.white },
  catBanner:       { backgroundColor: '#E8EEF5', paddingTop: 4, paddingBottom: 4, paddingLeft: 6, paddingRight: 6, marginTop: 10 },
  catBannerText:   { fontSize: 7, fontFamily: 'Helvetica-Bold', color: C.navy, letterSpacing: 0.5 },
  tableRow: {
    flexDirection: 'row',
    borderBottomWidth: 0.5,
    borderBottomColor: C.line,
    paddingTop: 5,
    paddingBottom: 5,
    paddingLeft: 4,
    paddingRight: 4,
  },
  tableRowAlt:      { backgroundColor: C.softGrey },
  tableFieldCol:    { width: '26%', paddingRight: 6 },
  tableFieldName:   { fontSize: 7.5, fontFamily: 'Helvetica-Bold', color: C.navy, marginBottom: 1 },
  tableValueCol:    { width: '37%', paddingRight: 6 },
  tableValue:       { fontSize: 8, color: C.inkMid, lineHeight: 1.3, marginBottom: 2 },
  tableConfLine:    { fontSize: 6.5, marginBottom: 2 },
  tableSourceLine:  { fontSize: 6.5, color: C.teal, textDecoration: 'underline', marginBottom: 1.5 },
  tableSourceLabel: { fontSize: 6, fontFamily: 'Helvetica-Bold', color: C.inkFaint, marginBottom: 1 },
  tableEmpty:       { fontSize: 8, color: C.inkFaint },

  // Multi-program stacked
  multiFieldBlock:       { borderWidth: 0.5, borderColor: C.line, borderRadius: 5, marginBottom: 6, overflow: 'hidden' },
  multiFieldHeader:      { backgroundColor: C.navy, paddingTop: 4, paddingBottom: 4, paddingLeft: 8, paddingRight: 8 },
  multiFieldHeaderText:  { fontSize: 7.5, fontFamily: 'Helvetica-Bold', color: C.white },
  multiProgRow:          { flexDirection: 'row', borderBottomWidth: 0.5, borderBottomColor: C.line, paddingTop: 5, paddingBottom: 5, paddingLeft: 8, paddingRight: 8 },
  multiProgRowAlt:       { backgroundColor: C.softGrey },
  multiProgLabel:        { width: '22%', paddingRight: 6 },
  multiProgLetter:       { fontSize: 7.5, fontFamily: 'Helvetica-Bold', marginBottom: 1 },
  multiProgName:         { fontSize: 6.5, color: C.inkFaint },
  multiProgContent:      { flex: 1 },
  multiProgValue:        { fontSize: 8, color: C.inkMid, lineHeight: 1.3, marginBottom: 2 },
  multiProgConf:         { fontSize: 6.5, marginBottom: 1.5 },
  multiProgSrcLink:      { fontSize: 6.5, color: C.teal, textDecoration: 'underline', marginBottom: 1.5 },

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

function progColor(idx: number): string { return PROG_COLORS[idx % PROG_COLORS.length]; }
function progBg(idx: number): string    { return PROG_BG[idx % PROG_BG.length]; }

// ── Reusable row components ───────────────────────────────────────────────────

function VerdictRow({ row }: { row: CategoryVerdict[] }) {
  return (
    <View style={s.verdictRow} wrap={false}>
      {row.map((v, ci) => (
        <View key={v.category} style={[s.verdictCard, ci === row.length - 1 ? { marginRight: 0 } : {}]}>
          <Text style={s.verdictCatLabel}>{v.label.toUpperCase()}</Text>
          <Text style={[s.verdictWinner]}>{v.winner}</Text>
          <Text style={s.verdictInsight}>{v.insight}</Text>
          {v.source_urls && v.source_urls.length > 0 && v.source_urls.slice(0, 3).map((url, i) => (
            <Link key={i} src={url} style={s.verdictLink}>
              {`${domainOf(url)}  —  ${url.length > 55 ? url.slice(0, 52) + '…' : url}`}
            </Link>
          ))}
        </View>
      ))}
      {Array.from({ length: 3 - row.length }).map((_, pi) => (
        <View key={`pad-${pi}`} style={{ flex: 1, marginRight: 0 }} />
      ))}
    </View>
  );
}

function ProfileRow({ row, programs }: { row: ProgramStrategicProfile[]; programs: string[] }) {
  return (
    <View style={{ flexDirection: 'row', marginBottom: 8 }} wrap={false}>
      {row.map((profile, ci) => {
        const progIdx = programs.indexOf(profile.program);
        const pColor  = progColor(progIdx >= 0 ? progIdx : ci);
        const pBg     = progBg(progIdx >= 0 ? progIdx : ci);
        return (
          <View key={profile.program} style={[s.profileBlock, { flex: 1 }, ci === row.length - 1 ? { marginRight: 0 } : {}]}>
            <View style={[s.profileHeader, { backgroundColor: pBg }]}>
              <Text style={[s.profileLetter, { color: pColor, backgroundColor: pBg }]}>
                {String.fromCharCode(65 + (progIdx >= 0 ? progIdx : ci))}
              </Text>
              <Text style={s.profileName}>{profile.program}</Text>
            </View>
            <View style={s.profileCols}>
              <View style={[s.profileCol, { borderRightWidth: 0.5, borderRightColor: C.line }]}>
                <Text style={[s.profileColLabel, { color: C.green }]}>STRENGTHS</Text>
                {profile.advantages.length > 0
                  ? profile.advantages.map((a, j) => <Text key={j} style={s.profileItem}>{`· ${a}`}</Text>)
                  : <Text style={[s.profileItem, { color: C.inkFaint }]}>No data</Text>
                }
              </View>
              <View style={s.profileCol}>
                <Text style={[s.profileColLabel, { color: C.amber }]}>GAPS</Text>
                {profile.gaps.length > 0
                  ? profile.gaps.map((g, j) => <Text key={j} style={s.profileItem}>{`· ${g}`}</Text>)
                  : <Text style={[s.profileItem, { color: C.inkFaint }]}>No data</Text>
                }
              </View>
            </View>
          </View>
        );
      })}
    </View>
  );
}

// ── Comparison brief section ──────────────────────────────────────────────────

function BriefSection({ brief, programs }: { brief: ComparisonBrief; programs: string[] }) {
  // Category verdicts in rows of 3
  const cvRows: CategoryVerdict[][] = [];
  for (let i = 0; i < brief.category_verdicts.length; i += 3) cvRows.push(brief.category_verdicts.slice(i, i + 3));

  // Strategic profiles in rows of 2
  const profileRows: ProgramStrategicProfile[][] = [];
  for (let i = 0; i < (brief.strategic_profiles ?? []).length; i += 2) {
    profileRows.push(brief.strategic_profiles.slice(i, i + 2));
  }

  const winnerColor = (name: string) => {
    const idx = programs.indexOf(name);
    return idx >= 0 ? progColor(idx) : C.navy;
  };

  return (
    <View>
      {/* Executive summary — always kept together */}
      <View style={s.execBox} wrap={false}>
        <Text style={s.execTag}>COMPETITIVE INTELLIGENCE BRIEF</Text>
        {brief.overall_winner
          ? <Text style={[s.execWinner, { color: winnerColor(brief.overall_winner) }]}>Overall leader: {brief.overall_winner}</Text>
          : <Text style={[s.execWinner, { color: C.inkLight }]}>Evenly matched — no clear overall leader</Text>
        }
        <Text style={s.execSummary}>{brief.executive_summary}</Text>
      </View>

      {/* Category verdicts — subheader anchored to first row */}
      {brief.category_verdicts.length > 0 && (
        <View>
          <View wrap={false}>
            <Text style={s.subHeader}>Category Verdicts</Text>
            {cvRows[0] && <VerdictRow row={cvRows[0]} />}
          </View>
          {cvRows.slice(1).map((row, ri) => <VerdictRow key={ri} row={row} />)}
        </View>
      )}

      {/* Key differentiators — subheader anchored to first row */}
      {brief.key_differentiators.length > 0 && (
        <View>
          <View style={{ borderWidth: 0.5, borderColor: C.line, borderRadius: 5, overflow: 'hidden' }}>
            {/* subheader + first diff row together */}
            <View wrap={false}>
              <View style={{ backgroundColor: C.softGrey, paddingTop: 6, paddingBottom: 6, paddingLeft: 4, paddingRight: 4, borderBottomWidth: 0.5, borderBottomColor: C.line }}>
                <Text style={s.subHeader}>Key Differentiators</Text>
              </View>
              {brief.key_differentiators[0] && (() => {
                const d = brief.key_differentiators[0];
                return (
                  <View style={s.diffRow}>
                    <View style={s.diffContent}>
                      <Text style={s.diffTopic}>{d.topic}</Text>
                      <Text style={s.diffInsight}>{d.insight}</Text>
                      {d.rejected_note && <Text style={s.diffNote}>{d.rejected_note}</Text>}
                      {d.source_urls?.slice(0, 4).map((url, j) => (
                        <Link key={j} src={url} style={s.diffSourceLine}>
                          {`${j + 1}. ${domainOf(url)}  —  ${url.length > 80 ? url.slice(0, 77) + '…' : url}`}
                        </Link>
                      ))}
                    </View>
                    <Text style={[s.diffAdvantage, { color: winnerColor(d.advantage) }]}>{d.advantage} ↑</Text>
                  </View>
                );
              })()}
            </View>
            {/* Remaining diff rows */}
            {brief.key_differentiators.slice(1).map((d, i) => (
              <View key={i} style={[s.diffRow, (i + 1) % 2 === 1 ? s.diffRowAlt : {}]} wrap={false}>
                <View style={s.diffContent}>
                  <Text style={s.diffTopic}>{d.topic}</Text>
                  <Text style={s.diffInsight}>{d.insight}</Text>
                  {d.rejected_note && <Text style={s.diffNote}>{d.rejected_note}</Text>}
                  {d.source_urls?.slice(0, 4).map((url, j) => (
                    <Link key={j} src={url} style={s.diffSourceLine}>
                      {`${j + 1}. ${domainOf(url)}  —  ${url.length > 80 ? url.slice(0, 77) + '…' : url}`}
                    </Link>
                  ))}
                </View>
                <Text style={[s.diffAdvantage, { color: winnerColor(d.advantage) }]}>{d.advantage} ↑</Text>
              </View>
            ))}
          </View>
        </View>
      )}

      {/* Strategic profiles — subheader anchored to first profile row */}
      {brief.strategic_profiles && brief.strategic_profiles.length > 0 && (
        <View>
          <View wrap={false}>
            <Text style={s.subHeader}>Strategic Advantages &amp; Gaps</Text>
            {profileRows[0] && <ProfileRow row={profileRows[0]} programs={programs} />}
          </View>
          {profileRows.slice(1).map((row, ri) => <ProfileRow key={ri} row={row} programs={programs} />)}
        </View>
      )}

      {/* Target audience — all kept together since it's compact */}
      {brief.personas && brief.personas.length > 0 && (
        <View wrap={false}>
          <Text style={s.subHeader}>Target Audience</Text>
          <View style={{ flexDirection: 'row' }}>
            {brief.personas.map((p, i) => {
              const pi     = programs.indexOf(p.program);
              const pColor = progColor(pi >= 0 ? pi : i);
              const pBg    = progBg(pi >= 0 ? pi : i);
              return (
                <View key={i} style={[s.personaCard, { backgroundColor: pBg }, i === brief.personas.length - 1 ? { marginRight: 0 } : {}]}>
                  <Text style={[s.personaProgram, { color: pColor }]}>{p.program.toUpperCase()}</Text>
                  <Text style={s.personaBestFor}>{p.best_for}</Text>
                </View>
              );
            })}
          </View>
        </View>
      )}
    </View>
  );
}

// ── 2-program field comparison table ─────────────────────────────────────────

function CellContent({
  entry,
}: {
  entry: FieldReportEntry | null | undefined;
}) {
  if (!entry || entry.status === 'not_found') {
    return <Text style={s.tableEmpty}>—</Text>;
  }
  const confPct = entry.confidence != null ? Math.round(entry.confidence * 100) : null;
  return (
    <>
      <Text style={s.tableValue}>{String(renderValue(entry.value) ?? '—').slice(0, 300)}</Text>
      {confPct != null && (
        <Text style={[s.tableConfLine, { color: confColor(entry.confidence) }]}>
          {`Conf: ${confPct}%`}{entry.corroboration_count > 1 ? `  ·  ${entry.corroboration_count}×` : ''}
        </Text>
      )}
      {entry.source_urls && entry.source_urls.length > 0 && (
        <View>
          <Text style={s.tableSourceLabel}>SOURCES</Text>
          {entry.source_urls.slice(0, 3).map((url, i) => (
            <Link key={i} src={url} style={s.tableSourceLine}>
              {`${i + 1}. ${domainOf(url)}  ${url.length > 52 ? url.slice(0, 49) + '…' : url}`}
            </Link>
          ))}
        </View>
      )}
    </>
  );
}

function TableRowTwo({
  fp, mapA, mapB, rowIdx,
}: {
  fp: string;
  mapA: Map<string, FieldReportEntry>;
  mapB: Map<string, FieldReportEntry>;
  rowIdx: number;
}) {
  const eA = mapA.get(fp) ?? null;
  const eB = mapB.get(fp) ?? null;
  return (
    <View style={[s.tableRow, rowIdx % 2 === 1 ? s.tableRowAlt : {}]}>
      <View style={s.tableFieldCol}>
        <Text style={s.tableFieldName}>{fieldLabel(fp)}</Text>
      </View>
      <View style={s.tableValueCol}><CellContent entry={eA} /></View>
      <View style={{ flex: 1 }}><CellContent entry={eB} /></View>
    </View>
  );
}

function FieldTableTwo({
  programA, programB, mapA, mapB,
}: {
  programA: string; programB: string;
  mapA: Map<string, FieldReportEntry>; mapB: Map<string, FieldReportEntry>;
}) {
  const shortA = programA.length > 22 ? programA.slice(0, 20) + '…' : programA;
  const shortB = programB.length > 22 ? programB.slice(0, 20) + '…' : programB;

  return (
    <View>
      <View style={s.tableHeader} wrap={false}>
        <Text style={[s.tableHeaderCell, { width: '26%' }]}>FIELD</Text>
        <Text style={[s.tableHeaderCell, { width: '37%', color: PROG_COLORS[0] }]}>A: {shortA}</Text>
        <Text style={[s.tableHeaderCell, { flex: 1,      color: PROG_COLORS[1] }]}>B: {shortB}</Text>
      </View>

      {CATEGORY_ORDER.map(cat => {
        const allFields = Array.from(FOCUSED_SCHEMA_FIELD_PATHS).filter(fp => fp.startsWith(cat + '.'));
        const visible   = allFields.filter(fp => mapA.has(fp) || mapB.has(fp));
        if (visible.length === 0) return null;

        return (
          <View key={cat}>
            {/* Banner + first row anchored together */}
            <View wrap={false}>
              <View style={s.catBanner}>
                <Text style={s.catBannerText}>{CATEGORY_LABELS[cat as Category].toUpperCase()}</Text>
              </View>
              {visible[0] && <TableRowTwo fp={visible[0]} mapA={mapA} mapB={mapB} rowIdx={0} />}
            </View>
            {/* Remaining rows */}
            {visible.slice(1).map((fp, i) => (
              <View key={fp} wrap={false}>
                <TableRowTwo fp={fp} mapA={mapA} mapB={mapB} rowIdx={i + 1} />
              </View>
            ))}
          </View>
        );
      })}
    </View>
  );
}

// ── N-program stacked field table ─────────────────────────────────────────────

function MultiFieldBlock({
  fp,
  programs,
  colorIndices,
  fieldMaps,
}: {
  fp: string;
  programs: string[];
  colorIndices: number[];
  fieldMaps: Map<string, FieldReportEntry>[];
}) {
  return (
    <View style={s.multiFieldBlock} wrap={false}>
      <View style={s.multiFieldHeader}>
        <Text style={s.multiFieldHeaderText}>{fieldLabel(fp)}</Text>
      </View>
      {programs.map((prog, pi) => {
        const ci    = colorIndices[pi];
        const entry = fieldMaps[pi]?.get(fp) ?? null;
        const hasVal = entry && entry.status !== 'not_found';
        return (
          <View key={pi} style={[s.multiProgRow, pi % 2 === 1 ? s.multiProgRowAlt : {}]}>
            <View style={s.multiProgLabel}>
              <Text style={[s.multiProgLetter, { color: progColor(ci) }]}>
                {String.fromCharCode(65 + ci)}: {prog.split(' ')[0]}
              </Text>
              {prog.includes(' ') && <Text style={s.multiProgName}>{prog}</Text>}
            </View>
            <View style={s.multiProgContent}>
              {hasVal ? (
                <>
                  <Text style={s.multiProgValue}>{String(renderValue(entry!.value) ?? '—').slice(0, 260)}</Text>
                  {entry!.confidence != null && (
                    <Text style={[s.multiProgConf, { color: confColor(entry!.confidence) }]}>
                      {`Conf: ${Math.round(entry!.confidence * 100)}%`}
                      {entry!.corroboration_count > 1 ? `  ·  ${entry!.corroboration_count}×` : ''}
                    </Text>
                  )}
                  {entry!.source_urls && entry!.source_urls.length > 0 && entry!.source_urls.slice(0, 4).map((url, i) => (
                    <Link key={i} src={url} style={s.multiProgSrcLink}>
                      {`${i + 1}. ${domainOf(url)}  —  ${url.length > 80 ? url.slice(0, 77) + '…' : url}`}
                    </Link>
                  ))}
                </>
              ) : (
                <Text style={{ fontSize: 7.5, color: C.inkFaint }}>Not found</Text>
              )}
            </View>
          </View>
        );
      })}
    </View>
  );
}

function FieldTableMulti({
  programs, colorIndices, fieldMaps,
}: {
  programs: string[];
  colorIndices: number[];
  fieldMaps: Map<string, FieldReportEntry>[];
}) {
  return (
    <View>
      {CATEGORY_ORDER.map(cat => {
        const allFields = Array.from(FOCUSED_SCHEMA_FIELD_PATHS).filter(fp => fp.startsWith(cat + '.'));
        const visible   = allFields.filter(fp => fieldMaps.some(m => {
          const e = m.get(fp);
          return e && e.status !== 'not_found';
        }));
        if (visible.length === 0) return null;

        return (
          <View key={cat}>
            {/* Banner + first field block anchored together */}
            <View wrap={false}>
              <View style={s.catBanner}>
                <Text style={s.catBannerText}>{CATEGORY_LABELS[cat as Category].toUpperCase()}</Text>
              </View>
              {visible[0] && (
                <MultiFieldBlock fp={visible[0]} programs={programs} colorIndices={colorIndices} fieldMaps={fieldMaps} />
              )}
            </View>
            {/* Remaining blocks */}
            {visible.slice(1).map(fp => (
              <MultiFieldBlock key={fp} fp={fp} programs={programs} colorIndices={colorIndices} fieldMaps={fieldMaps} />
            ))}
          </View>
        );
      })}
    </View>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

interface Props { state: AgentState }

export function ComparisonPDFDoc({ state }: Props) {
  const generatedDate = fmtDate(new Date().toISOString());
  const analysisDate  = fmtDate(state.updated_at ?? state.created_at);
  const runIdShort    = state.run_id.replace(/^run_/, '').slice(0, 12);

  const compRun = state.comparison_run;
  const isMulti = !!compRun && compRun.total_programs > 2;

  const programA = state.comparison_output?.program_a ?? state.program_name ?? state.user_input;
  const programB = state.comparison_output?.program_b ?? state.compare_b?.program_name ?? '';
  const stateB   = state.compare_b ?? null;

  const mapA = new Map<string, FieldReportEntry>();
  (state.field_report?.entries ?? []).forEach(e => mapA.set(e.field_path, e));
  const mapB = new Map<string, FieldReportEntry>();
  (stateB?.field_report?.entries ?? []).forEach(e => mapB.set(e.field_path, e));

  const programs = compRun?.programs ?? [programA, programB];

  const completedEntries = isMulti
    ? programs.map((prog, idx) => ({
        prog, idx,
        st: compRun!.program_states[idx] as AgentState | null,
        status: compRun!.program_statuses[idx],
      })).filter(e => e.status === 'done' && e.st !== null)
    : [];

  const displayPrograms = isMulti ? completedEntries.map(e => e.prog) : [programA, programB];
  const colorIndices    = isMulti ? completedEntries.map(e => e.idx)  : [0, 1];

  const qualityScores = isMulti
    ? completedEntries.map(e => Math.round((e.st?.data_quality ?? 0) * 100))
    : [Math.round((state.data_quality ?? 0) * 100), Math.round((stateB?.data_quality ?? 0) * 100)];

  const bestIdx = qualityScores.indexOf(Math.max(...qualityScores));

  const fieldMaps = isMulti
    ? completedEntries.map(({ st }) => {
        const m = new Map<string, FieldReportEntry>();
        (st?.field_report?.entries ?? []).forEach(e => m.set(e.field_path, e));
        return m;
      })
    : [mapA, mapB];

  const brief = state.comparison_brief ?? null;

  // Quality cards in rows of 3
  const qualityItems = displayPrograms.map((prog, i) => ({
    prog, ci: colorIndices[i], score: qualityScores[i] ?? 0, isBest: i === bestIdx,
    fr: isMulti ? completedEntries[i]?.st?.field_report : (i === 0 ? state.field_report : stateB?.field_report),
  }));
  const qualityRows: typeof qualityItems[] = [];
  for (let i = 0; i < qualityItems.length; i += 3) qualityRows.push(qualityItems.slice(i, i + 3));

  const docTitle = isMulti
    ? `Multi-Program Comparison – ${displayPrograms.length} Programs`
    : `Competitive Intelligence Report – ${programA} vs ${programB}`;

  return (
    <Document title={docTitle} author="Kobi Intelligence Platform">
      <Page size="A4" style={s.page}>

        {/* Fixed footer */}
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

        {/* ── Cover: hero + meta + quality anchored together ── */}
        <View wrap={false}>
          <View style={s.heroBlock}>
            <Text style={s.heroTag}>
              {isMulti ? 'MULTI-PROGRAM COMPARISON REPORT' : 'COMPETITIVE INTELLIGENCE REPORT'}
            </Text>
            <Text style={s.heroTitle}>
              {isMulti ? `${displayPrograms.length}-Program Analysis` : `${programA}  vs  ${programB}`}
            </Text>
            <View style={{ flexDirection: 'row', flexWrap: 'wrap' }}>
              {displayPrograms.map((prog, i) => {
                const ci = colorIndices[i];
                return (
                  <View key={i} style={[s.progPill, { backgroundColor: progBg(ci) }]}>
                    <Text style={[s.progPillText, { color: progColor(ci) }]}>
                      {String.fromCharCode(65 + ci)}: {prog}
                    </Text>
                  </View>
                );
              })}
            </View>
          </View>

          <View style={s.metaRow}>
            {[
              { label: 'RUN ID',        value: runIdShort,                    fs: 8.5 },
              { label: 'ANALYSIS DATE', value: analysisDate,                  fs: 8.5 },
              { label: 'GENERATED',     value: generatedDate,                 fs: 8.5 },
              { label: 'PROGRAMS',      value: String(displayPrograms.length), fs: 14  },
            ].map((m, i, arr) => (
              <View key={m.label} style={[s.metaCard, i === arr.length - 1 ? { marginRight: 0 } : {}]}>
                <Text style={s.metaLabel}>{m.label}</Text>
                <Text style={[s.metaValue, { fontSize: m.fs }]}>{m.value}</Text>
              </View>
            ))}
          </View>
        </View>

        {/* ── Data quality — section header + first row anchored ── */}
        <View wrap={false}>
          <Text style={s.sectionHeader}>Data Quality</Text>
          {qualityRows[0] && (
            <View style={s.qualityRow}>
              {qualityRows[0].map(({ prog, ci, score, isBest, fr }, qi) => (
                <View
                  key={prog}
                  style={[
                    s.qualityCard,
                    qi === qualityRows[0].length - 1 ? { marginRight: 0 } : {},
                    isBest ? { borderColor: C.green, borderWidth: 1 } : {},
                  ]}
                >
                  <Text style={[s.qualitySlot, { color: progColor(ci) }]}>
                    {isBest ? '★ BEST  ' : ''}{String.fromCharCode(65 + ci)}: PROGRAM
                  </Text>
                  <Text style={s.qualityName}>{prog}</Text>
                  <Text style={[s.qualityScore, { color: score >= 70 ? C.green : score >= 40 ? C.amber : C.red }]}>
                    {score}%
                  </Text>
                  {fr && (
                    <Text style={s.qualitySub}>
                      {fr.extracted_count} fields extracted
                      {fr.ambiguous_count > 0 ? `  ·  ${fr.ambiguous_count} ambiguous` : ''}
                    </Text>
                  )}
                </View>
              ))}
              {Array.from({ length: 3 - qualityRows[0].length }).map((_, pi) => (
                <View key={`pad-${pi}`} style={{ flex: 1 }} />
              ))}
            </View>
          )}
        </View>
        {/* Additional quality rows */}
        {qualityRows.slice(1).map((row, ri) => (
          <View key={ri} style={s.qualityRow} wrap={false}>
            {row.map(({ prog, ci, score, isBest, fr }, qi) => (
              <View
                key={prog}
                style={[
                  s.qualityCard,
                  qi === row.length - 1 ? { marginRight: 0 } : {},
                  isBest ? { borderColor: C.green, borderWidth: 1 } : {},
                ]}
              >
                <Text style={[s.qualitySlot, { color: progColor(ci) }]}>
                  {isBest ? '★ BEST  ' : ''}{String.fromCharCode(65 + ci)}: PROGRAM
                </Text>
                <Text style={s.qualityName}>{prog}</Text>
                <Text style={[s.qualityScore, { color: score >= 70 ? C.green : score >= 40 ? C.amber : C.red }]}>
                  {score}%
                </Text>
                {fr && (
                  <Text style={s.qualitySub}>
                    {fr.extracted_count} fields extracted
                    {fr.ambiguous_count > 0 ? `  ·  ${fr.ambiguous_count} ambiguous` : ''}
                  </Text>
                )}
              </View>
            ))}
          </View>
        ))}

        {/* ── AI Brief — flows naturally, no forced page break ── */}
        {brief ? (
          <View>
            <View wrap={false}>
              <Text style={s.sectionHeader}>Competitive Intelligence Brief</Text>
            </View>
            <BriefSection brief={brief} programs={displayPrograms} />
          </View>
        ) : (
          <View style={{ marginTop: 14, paddingTop: 10, paddingBottom: 10, paddingLeft: 12, paddingRight: 12, backgroundColor: C.softGrey, borderRadius: 5 }} wrap={false}>
            <Text style={{ fontSize: 8, color: C.inkLight }}>
              Competitive intelligence brief was not available at the time this PDF was generated.
            </Text>
          </View>
        )}

        {/* ── Field comparison — starts on new page since it's a distinct section ── */}
        <View break>
          <View wrap={false}>
            <Text style={s.sectionHeader}>Field-by-Field Comparison</Text>
          </View>
          {isMulti ? (
            <FieldTableMulti programs={displayPrograms} colorIndices={colorIndices} fieldMaps={fieldMaps} />
          ) : (
            <FieldTableTwo programA={programA} programB={programB} mapA={mapA} mapB={mapB} />
          )}
        </View>

        {/* ── Disclaimer ── */}
        <View style={s.disclaimer} wrap={false}>
          <Text style={s.disclaimerText}>
            {`This report was generated automatically by the Kobi Intelligence Platform on ${generatedDate}. All data points are sourced from publicly available information as of the analysis date (${analysisDate}). Confidence scores reflect cross-source corroboration quality. High-volatility fields change frequently — verify before use. Source URLs provided for independent verification. For informational purposes only.`}
          </Text>
        </View>

      </Page>
    </Document>
  );
}
