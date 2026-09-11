import { fetchJsonWithTimeout } from './http';
export type PickResult = 'pending' | 'win' | 'loss' | 'push';
export type PickMode = 'team' | 'player';

export interface Pick {
  id: string;
  source: string;
  pick: string;
  sport: string;
  date: string;
  units: number;
  odds: number | null;
  price_verified?: boolean;
  price_provenance?: 'verified' | 'unverified' | 'assumed' | 'missing';
  result: PickResult;
  pl: number;
  probability?: number | null;
  confidence?: number | string | null;
  start_time?: string | null;
  game_start_time?: string | null;
  away_team?: string;
  home_team?: string;
  team?: string;
  matchup?: string;
  game?: string;
  decision?: string;
  // True for rows that came from a scraped tipster feed rather than an
  // in-house model. Display-only: it drives the header's feed toggle and
  // nothing else.
  scraped?: boolean;
  research?: boolean;
  edge?: number | null;
  market_edge?: number | null;
  line?: number | null;
  market_line?: number | null;
  kelly?: number | string | null;
  kelly_units?: number | string | null;
  full_kelly?: number | string | null;
  quarter_kelly?: number | string | null;
  recommended_units?: number | string | null;
  reason?: string | null;
  rationale?: string | null;
  key_factors?: unknown;
  player?: string;
  player_name?: string;
  market?: string;
  scope?: string;
  external_player_feed?: boolean;
  ml_rank?: number | string | null;
  model_rank?: number | string | null;
  rank?: number | string | null;
  ml_rank_epoch?: string | null;
  ranking_epoch?: string | null;
  ranking_updated_at?: string | null;
  model_epoch?: string | null;
  consensus_applicable_models?: unknown;
  consensus_record_models?: unknown;
  [key: string]: unknown;
}

interface ModelBucket {
  ok?: boolean;
  picks?: unknown[];
  games?: unknown[];
  [key: string]: unknown;
}

interface ModelCachePayload {
  date?: string;
  generatedAt?: string;
  updatedAt?: string;
  models?: Record<string, ModelBucket>;
  external_feeds?: Record<string, ModelBucket>;
  [key: string]: unknown;
}

export interface SourceStatus {
  key: string;
  label: string;
  filterLabels: string[];
  sport: string;
  scraped: boolean;
  date: string;
  updatedAt: string | null;
  pickCount: number;
  researchCount: number;
  state: 'ready' | 'empty' | 'stale' | 'error' | 'missing';
  detail: string;
}

interface CacheManifest {
  files?: string[];
}

interface PlayerPropsPayload {
  date?: string;
  slate_date?: string;
  generatedAt?: string;
  updatedAt?: string;
  picks?: unknown[];
  props?: unknown[];
  player_props?: unknown[];
  recommendations?: unknown[];
  models?: Record<string, unknown>;
  sports?: Record<string, unknown>;
  leagues?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface ParlayLeg {
  legId: string;
  pickId?: string;
  source: string;
  sourceType?: string;
  sport: string;
  pick: string;
  decision?: string;
  oddsAmerican: number | null;
  decimalOdds?: number | null;
  estimatedProbability?: number | null;
  probabilitySource?: string;
  game?: string;
  market?: string;
  player?: string;
  result: PickResult;
  startTime?: string;
  consensusSources?: string[];
}

export interface ParlayCard {
  id: string;
  comboKey?: string;
  date?: string;
  category: string;
  categoryLabel: string;
  categoryShortLabel?: string;
  title?: string;
  fallback?: boolean;
  legCount: number;
  activeLegCount?: number;
  sportMix: string;
  sportPattern?: string;
  sports?: string[];
  hasPlayerProp?: boolean;
  pickMode?: PickMode | 'mixed';
  oddsAmerican: number | null;
  decimalOdds?: number | null;
  estimatedProbability?: number | null;
  geomeanProbability?: number | null;
  fairOdds?: number | null;
  parlayEv?: number | null;
  payoutQuality?: number | null;
  averageSourceForm?: number | null;
  consensusLegs?: number;
  result: PickResult;
  profitUnits?: number | null;
  stakeUnits?: number | null;
  whyQualified?: string;
  legs: ParlayLeg[];
}

export interface ParlayCategorySummary {
  key: string;
  label: string;
  shortLabel?: string;
  description?: string;
  count: number;
  threeLegCount?: number;
  fallbackCount?: number;
  weight?: number;
  record?: {
    wins?: number;
    losses?: number;
    pushes?: number;
    pending?: number;
    hitRate?: number | null;
    roi?: number | null;
    netUnits?: number | null;
    averageOdds?: number | null;
    recentForm?: string;
  };
}

export interface ParlayRanking {
  category: string;
  label: string;
  description?: string;
  wins: number;
  losses: number;
  pushes: number;
  pending: number;
  settled: number;
  hitRate: number | null;
  roi: number | null;
  netUnits: number;
  averageOdds: number | null;
  recentForm?: string;
}

export interface ParlayCardsPayload {
  date: string;
  generatedAt?: string;
  engineVersion?: string;
  summary?: {
    eligibleLegs?: number;
    generatedThreeLegCandidates?: number;
    displayedCards?: number;
    threeLegCards?: number;
    twoLegFallbackCards?: number;
    averageOdds?: number | null;
    record?: ParlayCategorySummary['record'];
  };
  categories?: ParlayCategorySummary[];
  rankings?: ParlayRanking[];
  cards?: ParlayCard[];
  notices?: string[];
  [key: string]: unknown;
}

export type ProfitDeskTier = 'edge' | 'value' | 'shadow' | 'watch' | 'avoid';
export type ProfitDeskLane = 'edge' | 'value';
export type ProfitDeskPriceQuality =
  | 'verified_two_sided'
  | 'verified_no_vig'
  | 'one_sided'
  | 'assumed'
  | 'missing'
  | 'stale';

export interface ProfitDeskPrice {
  quality?: ProfitDeskPriceQuality | string;
  source?: string;
  updatedAt?: string | null;
  ageHours?: number | null;
  fresh?: boolean;
  twoSided?: boolean;
  noVigProbability?: number | null;
  breakEvenProbability?: number | null;
}

export interface ProfitDeskEstimate {
  marketProbability?: number | null;
  alpha?: number | null;
  alphaStdError?: number | null;
  probability?: number | null;
  lowerProbability?: number | null;
  expectedValue?: number | null;
  conservativeExpectedValue?: number | null;
  probabilityPositiveEv?: number | null;
  value?: ProfitDeskEstimate;
}

export interface ProfitDeskEvidence {
  sourceSamples?: number;
  segmentSamples?: number;
  distinctDates?: number;
  sourceDistinctDates?: number;
  wins?: number;
  losses?: number;
  sourceWins?: number;
  sourceLosses?: number;
  flatNetUnits?: number | null;
  flatRoi?: number | null;
  sourceFlatNetUnits?: number | null;
  sourceFlatRoi?: number | null;
  priorOnly?: boolean;
}

export interface ProfitDeskBlocker {
  code?: string;
  label?: string;
  detail?: string;
}

export interface ProfitDeskCandidate {
  id?: string;
  sourceKey?: string;
  mode?: PickMode;
  tier?: ProfitDeskTier | string;
  portfolioSelected?: boolean;
  rank?: number | null;
  source?: string;
  sport?: string;
  pick?: string;
  game?: string;
  player?: string;
  market?: string;
  startTime?: string | null;
  result?: PickResult | string;
  decision?: string;
  oddsAmerican?: number | null;
  stakeUnits?: number | null;
  lane?: ProfitDeskLane | string | null;
  liveQualified?: boolean;
  closing?: ProfitDeskClosing;
  edgeQualified?: boolean;
  valueQualified?: boolean;
  price?: ProfitDeskPrice;
  estimate?: ProfitDeskEstimate;
  evidence?: ProfitDeskEvidence;
  blockers?: Array<ProfitDeskBlocker | string>;
  laneBlockers?: Partial<Record<'structural' | 'edge' | 'value', string[]>>;
  consensusSources?: string[];
}

export interface ProfitDeskModeSummary {
  candidateCount?: number;
  candidatesEvaluated?: number;
  observedPriceCandidates?: number;
  shadowQualified?: number;
  researchQualified?: number;
  edgeQualified?: number;
  valueQualified?: number;
  watchlist?: number;
  selected?: number;
  portfolioCandidates?: number;
  liveQualified?: number;
  evidenceRows?: number;
}

export interface ProfitDeskLiveRecord {
  wins?: number;
  losses?: number;
  pushes?: number;
  pending?: number;
  settled?: number;
  netUnits?: number | null;
  roi?: number | null;
  clvCount?: number;
  avgClv?: number | null;
}

export interface ProfitDeskClosing {
  oddsAmerican?: number | null;
  decimalOdds?: number | null;
  noVigProbability?: number | null;
  capturedAt?: string | null;
  provider?: string | null;
  clv?: number | null;
}

export interface ProfitDeskSummary extends ProfitDeskModeSummary {
  liveRecord?: ProfitDeskLiveRecord;
  liveRecordToDate?: ProfitDeskLiveRecord;
  modes?: Partial<Record<PickMode, ProfitDeskModeSummary>>;
}

export interface ProfitDeskPolicy {
  status?: string;
  mode?: string;
  firstLiveDate?: string | null;
  gates?: Record<string, unknown>;
  notes?: string[];
}

export interface ProfitDeskGateProgress {
  required?: number | boolean | null;
  actual?: number | boolean | null;
  passed?: boolean;
}

export interface ProfitDeskSourceCard {
  mode?: PickMode | string;
  sourceKey?: string;
  sport?: string;
  source?: string;
  samples?: number;
  distinctDates?: number;
  wins?: number;
  losses?: number;
  flatNetUnits?: number | null;
  flatRoi?: number | null;
  alpha?: number | null;
  probabilityPositiveEv?: number | null;
  gates?: Record<string, ProfitDeskGateProgress>;
  gatesPassed?: number;
  gatesTotal?: number;
  evidenceQualified?: boolean;
  candidatesToday?: number;
  liveToday?: number;
}

export interface ProfitDeskPayload {
  schemaVersion?: string | number;
  date: string;
  generatedAt?: string;
  engineVersion?: string;
  phase?: string;
  policy?: ProfitDeskPolicy;
  summary?: ProfitDeskSummary;
  candidates?: ProfitDeskCandidate[];
  portfolio?: Partial<Record<PickMode | 'all', ProfitDeskCandidate[]>>;
  sources?: ProfitDeskSourceCard[];
  [key: string]: unknown;
}

const HIDE_SCRAPED_KEY = 'pickledger_hide_scraped';
const HIDE_TENNIS_KEY = 'pickledger_hide_tennis';
let hideScrapedPicks = false;
let hideTennisPicks = false;
const RESULT_STORAGE_KEY = 'pickledger_static_results_v2';
const GAME_TIME_STORAGE_KEY = 'pickledger_static_game_times_v2';
// NBA Summer League and the FIFA World Cup archived 2026-07-19: both
// seasons ended (summer league finale + World Cup final same day).
const ARCHIVED_SPORTS = new Set(['NBA', 'NBA SUMMER', 'FIFA WC']);
const PLAYER_PROPS_ML_SOURCE = 'player_props_ml_v1';
// First snapshot produced by the ML slate-engine launch in commit b6f9dbe.
const PLAYER_PROPS_ML_FIRST_SNAPSHOT_AT = Date.parse('2026-06-16T19:04:34.909830Z');
const PLAYER_PROPS_PUBLIC_START_DATE = '2026-06-23';
const SOURCE_LABELS: Record<string, string> = {
  mlb_new: 'MLB Model',
  mlb_inning: 'MLB Inning',
  mlb_first_five: 'MLB First Five',
  mlb_team_total: 'MLB Team Total',
  mls: 'MLS Model',
  nfl: 'NFL Model',
  cfb: 'CFB Model',
  wnba: 'WNBA Model',
  nba: 'NBA New',
  nba_playoffs: 'NBA Playoffs',
  nba_summer: 'NBA Summer League',
  fifa_world_cup: 'FIFA Model',
  sportytrader: 'SportyTrader',
  sportytrader_nba: 'SportyTraderNBA',
  sportytrader_nba_summer: 'SportyTraderNBASummer',
  sportytrader_mlb: 'SportyTraderMLB',
  sportytrader_wnba: 'SportyTraderWNBA',
  sportytrader_fifa_world_cup: 'SportyTraderFIFAWorldCup',
  sportytrader_cfb: 'SportyTraderCFB',
  sportytrader_nfl: 'SportyTraderNFL',
  sportsgambler: 'SportsGambler',
  sportsgambler_nba: 'SportsGamblerNBA',
  sportsgambler_nba_summer: 'SportsGamblerNBASummer',
  sportsgambler_mlb: 'SportsGamblerMLB',
  sportsgambler_wnba: 'SportsGamblerWNBA',
  sportsgambler_fifa_world_cup: 'SportsGamblerFIFAWorldCup',
  sportsgambler_cfb: 'SportsGamblerCFB',
  sportsgambler_nfl: 'SportsGamblerNFL',
  scores24_nba_summer: 'Scores24NBASummer',
  scores24_wnba: 'Scores24WNBA',
  scores24_mlb: 'Scores24MLB',
  scores24_fifa_world_cup: 'Scores24FIFAWorldCup',
  scores24_cfb: 'Scores24CFB',
  scores24_nfl: 'Scores24NFL',
  forebet_mls: 'ForebetMLS',
  forebet_mlb: 'ForebetMLB',
  forebet_wnba: 'ForebetWNBA',
  forebet_cfb: 'ForebetCFB',
  forebet_nfl: 'ForebetNFL',
  scores24_tennis: 'Scores24Tennis',
  tennistonic_tennis: 'TennisTonic',
  tennis: 'Tennis Model',
};

// Bucket-key prefixes that identify a scraped tipster feed rather than an
// in-house model. Prefix-matched on purpose: the providers keep splitting into
// per-sport buckets (sportytrader_mlb, sportsgambler_wnba, …), and a new
// split should be covered without editing this list. In-house model keys
// (mlb_*, nba*, wnba, mls, nfl, tennis, fifa_world_cup, ipl) share no prefix
// with any provider, so there is nothing to collide with.
const SCRAPED_BUCKET_PREFIXES = [
  'scores24_',
  'sportytrader_',
  'sportsgambler_',
  'forebet_',
  'tennistonic_',
];

// Retired providers remain in immutable historical cache files, but their
// buckets must never enter any viewer, ranking, search result, or prop mode.
const RETIRED_BUCKET_PREFIXES = ['covers_'];

function isRetiredBucket(modelKey: string): boolean {
  const key = String(modelKey || '').trim().toLowerCase();
  return RETIRED_BUCKET_PREFIXES.some(prefix => key.startsWith(prefix));
}

function isScrapedBucket(modelKey: string): boolean {
  const key = String(modelKey || '').trim().toLowerCase();
  return SCRAPED_BUCKET_PREFIXES.some(prefix => key.startsWith(prefix));
}

const SOURCE_ALIASES: Record<string, string> = {
  'MLB NEW': 'MLB Model',
  'MLB New': 'MLB Model',
  'FIFA WC In-House': 'FIFA Model',
};

// The in-house MLB publishers each cover multiple markets under one bucket.
// The board tracks each market as its own source so a moneyline record can
// never hide a bad totals record (or vice versa). Applied at load time, so
// the split is retroactive across every committed cache day — the legacy
// "MLB Model" history decomposes into its ML and Total components with the
// underlying algorithms untouched.
const MARKET_SOURCE_LABELS: Record<string, Record<string, string>> = {
  mlb_new: { h2h: 'MLB ML', moneyline: 'MLB ML', totals: 'MLB Total', total: 'MLB Total' },
  mlb_first_five: { f5_side: 'MLB F5', f5_total: 'MLB F5 Total' },
  // Early-June wnba rows predate market_type stamping and were all
  // moneylines, so the empty-market fallback belongs to WNBA ML.
  wnba: { h2h: 'WNBA ML', moneyline: 'WNBA ML', '': 'WNBA ML', spread: 'WNBA Spread', totals: 'WNBA Total', total: 'WNBA Total' },
  // Summer league only ever bet moneylines; relabeled for naming
  // consistency with the other per-market sources. No spread/total
  // variants were built — the league's season ends 2026-07-19.
  nba_summer: { h2h: 'NBA Summer ML', moneyline: 'NBA Summer ML', '': 'NBA Summer ML' },
  mls: { moneyline: 'MLS ML', total: 'MLS Total', totals: 'MLS Total', spread: 'MLS Spread' },
  nfl: { h2h: 'NFL ML', moneyline: 'NFL ML', totals: 'NFL Total', total: 'NFL Total', spread: 'NFL Spread' },
  cfb: { h2h: 'CFB ML', moneyline: 'CFB ML', totals: 'CFB Total', total: 'CFB Total', spread: 'CFB Spread' },
};

function teamSourceLabel(modelKey: string, raw: Record<string, unknown>): string {
  const base = SOURCE_LABELS[modelKey] || modelKey;
  const byMarket = MARKET_SOURCE_LABELS[modelKey];
  if (!byMarket) return base;
  const market = String(raw.market || raw.market_type || '').trim().toLowerCase();
  return byMarket[market] ?? base;
}

const PLAYER_PROP_SOURCE_LABELS: Record<string, string> = {
  nba_player_props: 'NBAPlayerProps',
  mlb_player_props: 'MLBPlayerProps',
  wnba_player_props: 'WNBAPlayerProps',
  wnba_3pm: 'WNBA3PM',
  mlb_player_props_season: 'MLB Season Props',
  mlb_player_props_all_time: 'MLB All Time Props',
  mlb_player_props_hot_l10: 'MLB Hot L10 Props',
  mlb_player_props_matchup_h2h: 'MLB Matchup H2H Props',
  wnba_player_props_season: 'WNBA Season Props',
  wnba_player_props_all_time: 'WNBA All Time Props',
  wnba_player_props_hot_l10: 'WNBA Hot L10 Props',
  wnba_player_props_matchup_h2h: 'WNBA Matchup H2H Props',
};

// The MLB prop publisher ships several stat families out of one bucket, so a
// single blended record hides how each one actually does. Walks price and
// settle nothing like the hits/RBI props that dominate the slate, so they
// rank as their own model — the same per-market reasoning behind
// MARKET_SOURCE_LABELS on the team board, and the same shape as WNBA3PM.
// Resolved at load time, so the split is retroactive across every committed
// prop day with the underlying model untouched.
const MLB_PLAYER_PROPS_MODEL_KEY = 'mlb_player_props';
const MLB_WALKS_SOURCE = 'MLBWalks';

// Includes batter walks and the pitcher walks-allowed line; both are walk
// markets and neither carries enough volume to stand on its own.
function isWalkPropMarket(raw: Record<string, unknown>): boolean {
  return String(raw.stat_key || raw.market_type || raw.market || '')
    .toLowerCase()
    .includes('walk');
}

function playerPropSourceLabel(modelKey: string, raw: unknown): string {
  const base = PLAYER_PROP_SOURCE_LABELS[modelKey] || modelKey;
  if (modelKey !== MLB_PLAYER_PROPS_MODEL_KEY || !raw || typeof raw !== 'object') return base;
  return isWalkPropMarket(raw as Record<string, unknown>) ? MLB_WALKS_SOURCE : base;
}

let activePickMode: PickMode = 'team';
let teamPicks: Pick[] = [];
let researchPicks: Pick[] = [];
let playerPicks: Pick[] = [];
let resultOverrides: Record<string, PickResult> = {};
let gameTimes: Record<string, string> = {};
let latestTeamCache: ModelCachePayload | null = null;
let latestPlayerCache: PlayerPropsPayload | null = null;
let teamCachePayloads: ModelCachePayload[] = [];
let playerCachePayloads: PlayerPropsPayload[] = [];
let parlayPayloads: ParlayCardsPayload[] = [];
let latestParlayPayload: ParlayCardsPayload | null = null;
let profitDeskPayloads: ProfitDeskPayload[] = [];
let latestProfitDeskPayload: ProfitDeskPayload | null = null;
let pickHistoryStatus: 'idle' | 'loading' | 'ready' = 'idle';
let pickHistoryLoaded = false;
let pickHistoryPromise: Promise<void> | null = null;

function readStorage<T>(key: string, fallback: T): T {
  try {
    const parsed = JSON.parse(localStorage.getItem(key) || '');
    return parsed && typeof parsed === 'object' ? parsed as T : fallback;
  } catch {
    return fallback;
  }
}

function writeStorage(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // The viewer remains usable when storage is blocked.
  }
}

function normalizeResult(value: unknown): PickResult {
  const result = String(value || '').trim().toLowerCase();
  if (result === 'win' || result === 'w') return 'win';
  if (result === 'loss' || result === 'l') return 'loss';
  if (result === 'push' || result === 'p') return 'push';
  return 'pending';
}

function numberOrNull(value: unknown): number | null {
  if (value === '' || value == null) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function stableHash(value: string): string {
  let hash = 0x811c9dc5;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0).toString(36);
}

function stablePickId(raw: Record<string, unknown>, date: string, source: string): string {
  const existing = String(raw.id || '').trim();
  if (existing) return existing;
  return `pick-${stableHash(JSON.stringify([
    source,
    raw.sport,
    date,
    raw.pick,
    raw.selection || raw.prop || raw.bet,
    raw.player || raw.player_name,
    raw.market || raw.market_type,
    raw.ml_rank_epoch || raw.ranking_epoch || raw.model_epoch,
    raw.matchup || raw.game,
    raw.away_team,
    raw.home_team,
  ]))}`;
}

export function calculateProfit(pick: Pick, result: PickResult = pick.result): number {
  if (result === 'pending' || result === 'push') return 0;
  if (pick.price_verified !== true) return 0;
  const odds = numberOrNull(pick.odds);
  if (odds == null || odds === 0) return 0;
  if (result === 'loss') return -pick.units;
  return Number((odds > 0 ? pick.units * odds / 100 : pick.units * 100 / Math.abs(odds)).toFixed(2));
}

function normalizedPriceProvenance(raw: Record<string, unknown>, odds: number | null): {
  verified: boolean;
  provenance: Pick['price_provenance'];
} {
  if (odds == null || odds === 0) return { verified: false, provenance: 'missing' };
  const quality = String(raw.price_quality || raw.odds_quality || raw.market_price_quality || '').trim().toLowerCase();
  const verifiedQualities = new Set(['verified', 'verified_two_sided', 'verified_no_vig', 'observed_sportsbook']);
  const explicitlyVerified = raw.price_verified === true || raw.odds_verified === true || verifiedQualities.has(quality);
  if (explicitlyVerified) return { verified: true, provenance: 'verified' };
  const provenanceText = [
    raw.pricing_type,
    raw.price_source,
    raw.odds_source,
    raw.line_source,
    raw.market_source,
  ].map(value => String(value || '').trim().toLowerCase()).filter(Boolean).join(' ');
  const nonExecutable = /assumed|synthetic|proxy|fallback|default|estimated|model[_ ]price/.test(provenanceText);
  const usesAssumedPrice = raw.odds == null && raw.american_odds == null && raw.price == null && raw.assumed_odds != null;
  if (usesAssumedPrice || quality === 'assumed' || nonExecutable) return { verified: false, provenance: 'assumed' };
  const observedMarker = /posted|sportsbook|bookmaker|observed|executable/.test(provenanceText);
  if (raw.market_priced === true && observedMarker) return { verified: true, provenance: 'verified' };
  return { verified: false, provenance: 'unverified' };
}

function normalizePick(
  input: unknown,
  fallbackDate: string,
  fallbackSource: string,
  gameByMatchup: Map<string, Record<string, unknown>> = new Map(),
  playerProp = false,
): Pick | null {
  if (!input || typeof input !== 'object') return null;
  const raw = input as Record<string, unknown>;
  const pickText = String(raw.pick || raw.selection || raw.prop || raw.bet || '').trim();
  if (!pickText) return null;

  const rawSource = String((playerProp && fallbackSource) ? fallbackSource : (raw.source || fallbackSource || 'Unknown')).trim();
  const source = SOURCE_ALIASES[rawSource] || rawSource;
  const date = String(raw.date || raw.game_date || raw.slate_date || raw.Date || fallbackDate || '').trim();
  const matchup = String(raw.matchup || raw.game || raw.event || '').trim();
  const game = gameByMatchup.get(matchup);
  const id = stablePickId(raw, date, rawSource);
  const embeddedResult = normalizeResult(raw.result);
  const localResult = normalizeResult(resultOverrides[id]);
  const result = embeddedResult === 'pending' ? localResult : embeddedResult;
  const decision = String(raw.decision || '').trim().toUpperCase();
  const units = numberOrNull(raw.units ?? raw.stake_units ?? raw.recommended_units ?? raw.quarter_kelly)
    ?? (playerProp && decision === 'PASS' ? 0 : 1);
  const startTime = String(
    raw.start_time || raw.game_start_time ||
    game?.start_time || game?.game_start_time ||
    gameTimes[id] || '',
  ).trim() || null;
  const odds = numberOrNull(raw.odds ?? raw.assumed_odds ?? raw.american_odds ?? raw.price);
  const priceProvenance = normalizedPriceProvenance(raw, odds);

  const pick: Pick = {
    ...raw,
    id,
    source,
    pick: pickText,
    sport: String(raw.sport || raw.league || 'OTHER').trim().toUpperCase(),
    matchup: matchup || undefined,
    player: String(raw.player || raw.player_name || '').trim() || undefined,
    reason: String(raw.reason || raw.rationale || raw.notes || '').trim() || undefined,
    key_factors: raw.key_factors ?? raw.factors ?? raw.guardrail_reasons,
    date,
    units,
    odds,
    price_verified: priceProvenance.verified,
    price_provenance: priceProvenance.provenance,
    probability: numberOrNull(raw.probability ?? raw.model_probability ?? raw.predicted_probability),
    result,
    pl: 0,
    start_time: startTime,
    game_start_time: startTime,
  };
  pick.pl = calculateProfit(pick, result);
  return pick;
}

function isTrackedPick(pick: Pick): boolean {
  const decision = String(pick.decision || '').trim().toUpperCase();
  if (decision === 'BET' || decision === 'LEAN') return true;
  // In-house PASS still belongs on the public board. Scraped PASS stays
  // research-only so a demoted tip cannot look like a model post.
  return decision === 'PASS' && pick.scraped !== true;
}

function isTrackedPlayerProp(pick: Pick): boolean {
  const decision = String(pick.decision || '').trim().toUpperCase();
  return decision === 'BET' || decision === 'LEAN' || decision === 'PASS';
}

function isPlayerScopedPick(pick: Pick): boolean {
  return String(pick.scope || '').trim().toLowerCase() === 'player';
}

function isMlEraPlayerProp(pick: Pick): boolean {
  if (String(pick.probability_source || '').trim() !== PLAYER_PROPS_ML_SOURCE) return false;
  if (String(pick.date || '') < PLAYER_PROPS_PUBLIC_START_DATE) return false;
  const timestamp = Date.parse(String(
    pick.ranking_updated_at || pick.generated_at || pick.created_at || '',
  ));
  return Number.isFinite(timestamp) && timestamp >= PLAYER_PROPS_ML_FIRST_SNAPSHOT_AT;
}

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown> : {};
}

function bucketDate(bucket: ModelBucket, fallbackDate: string): string {
  const meta = recordValue(bucket.meta);
  return String(bucket.date || bucket.cache_date || meta.date || fallbackDate || '').trim();
}

function bucketUpdatedAt(bucket: ModelBucket, payload?: ModelCachePayload): string | null {
  const meta = recordValue(bucket.meta);
  const value = String(bucket.updatedAt || bucket.generatedAt || meta.updatedAt
    || payload?.updatedAt || payload?.generatedAt || '').trim();
  return value && Number.isFinite(Date.parse(value)) ? value : null;
}

function cacheBuckets(payload: ModelCachePayload): Record<string, ModelBucket> {
  const models = recordValue(payload.models) as Record<string, ModelBucket>;
  const feeds = recordValue(payload.external_feeds) as Record<string, ModelBucket>;
  const buckets: Record<string, ModelBucket> = { ...feeds };
  for (const [key, model] of Object.entries(models)) {
    const feed = feeds[key];
    if (!model || typeof model !== 'object') continue;
    if (!feed || typeof feed !== 'object') {
      buckets[key] = model;
      continue;
    }
    const modelDate = bucketDate(model, String(payload.date || ''));
    const feedDate = bucketDate(feed, String(payload.date || ''));
    if (modelDate !== feedDate) {
      buckets[key] = modelDate > feedDate ? model : feed;
      continue;
    }
    const modelTime = Date.parse(bucketUpdatedAt(model) || '') || 0;
    const feedTime = Date.parse(bucketUpdatedAt(feed) || '') || 0;
    const newer = feedTime > modelTime ? feed : model;
    const older = newer === model ? feed : model;
    buckets[key] = { ...older, ...newer, meta: { ...recordValue(older.meta), ...recordValue(newer.meta) } };
  }
  return buckets;
}

function normalizedBucketPicks(modelKey: string, bucket: ModelBucket, fallbackDate: string): Pick[] {
  if (isRetiredBucket(modelKey) || !bucket || typeof bucket !== 'object') return [];
  // The writer marks retained, previously successful same-day rows explicitly.
  // An arbitrary failed bucket still cannot publish picks.
  if (bucket.ok === false && bucket.preserved_after_refresh_error !== true) return [];
  const date = bucketDate(bucket, fallbackDate);
  const gameByMatchup = new Map<string, Record<string, unknown>>();
  for (const item of Array.isArray(bucket.games) ? bucket.games : []) {
    const game = recordValue(item);
    const matchup = String(game.matchup || game.game || '').trim();
    if (matchup) gameByMatchup.set(matchup, game);
  }
  const picks: Pick[] = [];
  for (const raw of Array.isArray(bucket.picks) ? bucket.picks : []) {
    if (!raw || typeof raw !== 'object') continue;
    const rawRecord = raw as Record<string, unknown>;
    const source = teamSourceLabel(modelKey, rawRecord);
    const input = MARKET_SOURCE_LABELS[modelKey] ? { ...rawRecord, source } : rawRecord;
    const pick = normalizePick(input, date, source, gameByMatchup);
    // A carried-forward bucket retains its own date, and a mixed-date row
    // cannot silently enter the selected slate.
    if (!pick || pick.date !== date || ARCHIVED_SPORTS.has(pick.sport)) continue;
    if (isScrapedBucket(modelKey)) pick.scraped = true;
    picks.push(pick);
  }
  return picks;
}

function picksFromCache(payload: ModelCachePayload): Pick[] {
  const picks: Pick[] = [];
  for (const [modelKey, bucket] of Object.entries(recordValue(payload.models))) {
    const model = bucket as ModelBucket;
    if (!model || model.shadow_mode === true) continue;
    picks.push(...normalizedBucketPicks(modelKey, model, String(payload.date || ''))
      .filter(pick => pick.shadow_mode !== true && isTrackedPick(pick)));
  }
  return picks;
}

function researchFromCache(payload: ModelCachePayload): Pick[] {
  const picks: Pick[] = [];
  for (const [key, bucket] of Object.entries(cacheBuckets(payload))) {
    const scraped = isScrapedBucket(key);
    if (!scraped && key !== 'cfb') continue;
    for (const pick of normalizedBucketPicks(key, bucket, String(payload.date || ''))) {
      if (isPlayerScopedPick(pick)) continue;
      const shadow = bucket.shadow_mode === true || pick.shadow_mode === true;
      if (!(scraped && String(pick.decision || '').trim().toUpperCase() === 'PASS') && !shadow) continue;
      picks.push({ ...pick, research: true, decision: 'PASS', units: 0, pl: 0 });
    }
  }
  return picks;
}

function playerPropRecords(payload: PlayerPropsPayload): Array<{ raw: unknown; source: string }> {
  const records: Array<{ raw: unknown; source: string }> = [];
  // Resolved per row rather than per bucket so one model key can publish
  // into more than one ranked source (see playerPropSourceLabel).
  const addBucket = (bucket: unknown, sourceFor: (raw: unknown) => string): void => {
    if (Array.isArray(bucket)) {
      bucket.forEach(raw => records.push({ raw, source: sourceFor(raw) }));
      return;
    }
    if (!bucket || typeof bucket !== 'object') return;
    const value = bucket as Record<string, unknown>;
    if (value.ok === false) return;
    for (const key of ['picks', 'props', 'player_props', 'recommendations']) {
      if (Array.isArray(value[key])) addBucket(value[key], sourceFor);
    }
  };

  addBucket(payload, () => 'Player Props');
  for (const containerKey of ['models', 'sports', 'leagues']) {
    const container = payload[containerKey];
    if (!container || typeof container !== 'object' || Array.isArray(container)) continue;
    for (const [modelKey, bucket] of Object.entries(container as Record<string, unknown>)) {
      addBucket(bucket, raw => playerPropSourceLabel(modelKey, raw));
    }
  }
  return records;
}

function picksFromPlayerProps(payload: PlayerPropsPayload): Pick[] {
  const date = String(payload.date || payload.slate_date || '').trim();
  return playerPropRecords(payload)
    .map(({ raw, source }) => normalizePick(raw, date, source, new Map(), true))
    .filter((pick): pick is Pick => Boolean(pick) && isTrackedPlayerProp(pick));
}

const DATED_CACHE_FILE = /^\d{4}-\d{2}-\d{2}\.json$/;
const HISTORY_FETCH_CONCURRENCY = 8;
const MODEL_CACHE_INDEX = './data/model_cache/index.json';
const MODEL_CACHE_LATEST = './data/model_cache/latest.json';
const MODEL_CACHE_DIR = './data/model_cache';
const PLAYER_CACHE_INDEX = './data/player_props_cache/index.json';
const PLAYER_CACHE_LATEST = './data/player_props_cache/latest.json';
const PLAYER_CACHE_DIR = './data/player_props_cache';
const PARLAY_CACHE_INDEX = './data/parlay_cards/index.json';
const PARLAY_CACHE_LATEST = './data/parlay_cards/latest.json';
const PARLAY_CACHE_DIR = './data/parlay_cards';
const PROFIT_CACHE_INDEX = './data/profit_desk/index.json';
const PROFIT_CACHE_LATEST = './data/profit_desk/latest.json';
const PROFIT_CACHE_DIR = './data/profit_desk';

function fetchJson<T>(path: string): Promise<T | null> {
  // Revalidate dated files so grading updates arrive without cache busting.
  return fetchJsonWithTimeout<T>(path, 'no-cache');
}

const latestLoadAvailable: Record<PickMode, boolean> = { team: false, player: false };

export function didLatestCacheLoad(): boolean {
  return latestLoadAvailable[activePickMode];
}

function mergePayloadsByDate<T>(
  existing: T[], incoming: T[], dateOf: (payload: T) => string, incomingWins = true,
): T[] {
  const byDate = new Map<string, T>();
  for (const payload of incomingWins ? [...existing, ...incoming] : [...incoming, ...existing]) {
    const date = dateOf(payload);
    if (date) byDate.set(date, payload);
  }
  return [...byDate.values()].sort((left, right) => dateOf(left).localeCompare(dateOf(right)));
}

async function mapPool<T, R>(items: T[], limit: number, mapper: (item: T) => Promise<R>): Promise<R[]> {
  if (!items.length) return [];
  const results: R[] = new Array(items.length);
  let next = 0;
  async function worker(): Promise<void> {
    while (true) {
      const index = next;
      next += 1;
      if (index >= items.length) return;
      results[index] = await mapper(items[index]);
    }
  }
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, () => worker()));
  return results;
}

async function listDatedCacheFiles(indexPath: string): Promise<string[]> {
  const manifest = await fetchJson<CacheManifest>(indexPath);
  return Array.isArray(manifest?.files)
    ? manifest.files.filter(file => DATED_CACHE_FILE.test(file))
    : [];
}

async function loadLatestOrLastDated<T>(latestPath: string, indexPath: string, dir: string): Promise<T | null> {
  const latest = await fetchJson<T>(latestPath);
  if (latest) return latest;
  const files = [...await listDatedCacheFiles(indexPath)].sort();
  const last = files[files.length - 1];
  return last ? fetchJson<T>(`${dir}/${last}`) : null;
}

/**
 * Load the normal first-paint cache plus the newest dated payload when it is
 * newer. A dated payload remains a separate record: callers merge by its own
 * date rather than blending yesterday's model buckets into today's slate.
 */
export async function loadLatestAndNewestDated<T>(
  latestPath: string,
  indexPath: string,
  dir: string,
  dateOf: (payload: T) => string,
): Promise<T[]> {
  const [latest, files] = await Promise.all([
    fetchJson<T>(latestPath),
    listDatedCacheFiles(indexPath),
  ]);
  const newestFile = [...files].sort().at(-1);
  if (!newestFile) return latest ? [latest] : [];

  const newestDate = newestFile.replace(/\.json$/, '');
  const latestDate = latest ? dateOf(latest).trim() : '';
  if (latest && latestDate >= newestDate) return [latest];

  const newest = await fetchJson<T>(`${dir}/${newestFile}`);
  // The manifest filename is the cache date contract. Do not let a malformed
  // or stale payload masquerade as the newer slate.
  if (!newest || dateOf(newest).trim() !== newestDate) return latest ? [latest] : [];
  return latest ? [latest, newest] : [newest];
}

function rebuildPicks(): void {
  const teamById = new Map<string, Pick>();
  const playerById = new Map<string, Pick>();
  const researchById = new Map<string, Pick>();
  teamCachePayloads.flatMap(picksFromCache).forEach(pick => {
    if (isPlayerScopedPick(pick)) playerById.set(pick.id, pick);
    else teamById.set(pick.id, pick);
  });
  playerCachePayloads.flatMap(picksFromPlayerProps).forEach(pick => playerById.set(pick.id, pick));
  teamCachePayloads.flatMap(researchFromCache).forEach(pick => researchById.set(pick.id, pick));
  teamPicks = sortPicks([...teamById.values()].filter(pick => !ARCHIVED_SPORTS.has(pick.sport)));
  researchPicks = sortPicks([...researchById.values()].filter(pick => !teamById.has(pick.id)));
  // External player-prop feeds (scope=player rows in the team cache) render
  // in Player mode alongside the in-house ML-era props; the
  // scope routing above already keeps them out of Team mode and rankings.
  playerPicks = sortPicks([...playerById.values()].filter(
    pick => !ARCHIVED_SPORTS.has(pick.sport) && (isMlEraPlayerProp(pick) || pick.external_player_feed === true),
  ));
}

async function loadLatestCaches(): Promise<void> {
  const [teamPayloads, player, parlays, profitRaw] = await Promise.all([
    loadLatestAndNewestDated<ModelCachePayload>(
      MODEL_CACHE_LATEST,
      MODEL_CACHE_INDEX,
      MODEL_CACHE_DIR,
      payload => String(payload.date || ''),
    ),
    loadLatestOrLastDated<PlayerPropsPayload>(PLAYER_CACHE_LATEST, PLAYER_CACHE_INDEX, PLAYER_CACHE_DIR),
    loadLatestOrLastDated<ParlayCardsPayload>(PARLAY_CACHE_LATEST, PARLAY_CACHE_INDEX, PARLAY_CACHE_DIR),
    loadLatestOrLastDated<ProfitDeskPayload>(PROFIT_CACHE_LATEST, PROFIT_CACHE_INDEX, PROFIT_CACHE_DIR),
  ]);
  latestLoadAvailable.team = teamPayloads.some(payload => Boolean(payload.date && payload.models));
  latestLoadAvailable.player = Boolean((player?.date || player?.slate_date) && player?.models);
  if (teamPayloads.length) {
    teamCachePayloads = mergePayloadsByDate(
      teamCachePayloads,
      teamPayloads,
      payload => String(payload.date || ''),
    );
    latestTeamCache = teamCachePayloads[teamCachePayloads.length - 1]
      || teamPayloads[teamPayloads.length - 1]
      || null;
  }
  if (player) {
    playerCachePayloads = mergePayloadsByDate(
      playerCachePayloads,
      [player],
      payload => String(payload.date || payload.slate_date || ''),
    );
    latestPlayerCache = playerCachePayloads[playerCachePayloads.length - 1] || player;
  }
  if (parlays) {
    parlayPayloads = mergePayloadsByDate(parlayPayloads, [parlays], payload => String(payload.date || ''));
    latestParlayPayload = parlayPayloads[parlayPayloads.length - 1] || parlays;
  }
  const profit = profitRaw ? withoutRetiredProfitDeskSources(profitRaw) : null;
  if (profit?.date) {
    profitDeskPayloads = mergePayloadsByDate(profitDeskPayloads, [profit], payload => String(payload.date || ''));
    latestProfitDeskPayload = profitDeskPayloads[profitDeskPayloads.length - 1] || profit;
  }
  rebuildPicks();
}

async function loadHistoryCaches(): Promise<void> {
  const [teamFiles, playerFiles, parlayFiles, profitFiles] = await Promise.all([
    listDatedCacheFiles(MODEL_CACHE_INDEX),
    listDatedCacheFiles(PLAYER_CACHE_INDEX),
    listDatedCacheFiles(PARLAY_CACHE_INDEX),
    listDatedCacheFiles(PROFIT_CACHE_INDEX),
  ]);
  const loadedTeam = new Set(teamCachePayloads.map(payload => String(payload.date || '')));
  const loadedPlayer = new Set(playerCachePayloads.map(payload => String(payload.date || payload.slate_date || '')));
  const loadedParlay = new Set(parlayPayloads.map(payload => String(payload.date || '')));
  const loadedProfit = new Set(profitDeskPayloads.map(payload => String(payload.date || '')));
  const [teamIncoming, playerIncoming, parlayIncoming, profitIncoming] = await Promise.all([
    mapPool(teamFiles.filter(file => !loadedTeam.has(file.replace(/\.json$/, ''))), HISTORY_FETCH_CONCURRENCY, file => (
      fetchJson<ModelCachePayload>(`${MODEL_CACHE_DIR}/${file}`)
    )),
    mapPool(playerFiles.filter(file => !loadedPlayer.has(file.replace(/\.json$/, ''))), HISTORY_FETCH_CONCURRENCY, file => (
      fetchJson<PlayerPropsPayload>(`${PLAYER_CACHE_DIR}/${file}`)
    )),
    mapPool(parlayFiles.filter(file => !loadedParlay.has(file.replace(/\.json$/, ''))), HISTORY_FETCH_CONCURRENCY, file => (
      fetchJson<ParlayCardsPayload>(`${PARLAY_CACHE_DIR}/${file}`)
    )),
    mapPool(profitFiles.filter(file => !loadedProfit.has(file.replace(/\.json$/, ''))), HISTORY_FETCH_CONCURRENCY, file => (
      fetchJson<ProfitDeskPayload>(`${PROFIT_CACHE_DIR}/${file}`)
    )),
  ]);
  teamCachePayloads = mergePayloadsByDate(
    teamCachePayloads,
    teamIncoming.filter((payload): payload is ModelCachePayload => Boolean(payload)),
    payload => String(payload.date || ''),
    false,
  );
  latestTeamCache = teamCachePayloads[teamCachePayloads.length - 1] || latestTeamCache;
  playerCachePayloads = mergePayloadsByDate(
    playerCachePayloads,
    playerIncoming.filter((payload): payload is PlayerPropsPayload => Boolean(payload)),
    payload => String(payload.date || payload.slate_date || ''),
    false,
  );
  latestPlayerCache = playerCachePayloads[playerCachePayloads.length - 1] || latestPlayerCache;
  parlayPayloads = mergePayloadsByDate(
    parlayPayloads,
    parlayIncoming.filter((payload): payload is ParlayCardsPayload => Boolean(payload)),
    payload => String(payload.date || ''),
    false,
  );
  latestParlayPayload = parlayPayloads[parlayPayloads.length - 1] || latestParlayPayload;
  profitDeskPayloads = mergePayloadsByDate(
    profitDeskPayloads,
    profitIncoming
      .filter((payload): payload is ProfitDeskPayload => Boolean(payload?.date))
      .map(withoutRetiredProfitDeskSources),
    payload => String(payload.date || ''),
    false,
  );
  latestProfitDeskPayload = profitDeskPayloads[profitDeskPayloads.length - 1] || latestProfitDeskPayload;
  rebuildPicks();
}

async function ensureHistory(): Promise<void> {
  if (pickHistoryLoaded) return;
  if (!pickHistoryPromise) {
    pickHistoryStatus = 'loading';
    pickHistoryPromise = loadHistoryCaches()
      .then(() => {
        pickHistoryLoaded = true;
        pickHistoryStatus = 'ready';
      })
      .catch(() => {
        pickHistoryPromise = null;
        pickHistoryStatus = 'idle';
      });
  }
  return pickHistoryPromise;
}

function isRetiredProviderName(value: unknown): boolean {
  const normalized = String(value || '').trim().toLowerCase();
  return isRetiredBucket(normalized)
    || normalized === 'covers'
    || normalized.startsWith('covers ')
    || normalized.startsWith('covers ·');
}

function withoutRetiredProfitDeskSources(payload: ProfitDeskPayload): ProfitDeskPayload {
  const sanitizeCandidate = (candidate: ProfitDeskCandidate): ProfitDeskCandidate => ({
    ...candidate,
    consensusSources: Array.isArray(candidate.consensusSources)
      ? candidate.consensusSources.filter(source => !isRetiredProviderName(source))
      : candidate.consensusSources,
  });
  const keepCandidate = (candidate: ProfitDeskCandidate): boolean => (
    !isRetiredProviderName(candidate.sourceKey) && !isRetiredProviderName(candidate.source)
  );
  const candidates = Array.isArray(payload.candidates)
    ? payload.candidates.filter(keepCandidate).map(sanitizeCandidate)
    : payload.candidates;
  const portfolio = payload.portfolio && typeof payload.portfolio === 'object'
    ? Object.fromEntries(Object.entries(payload.portfolio).map(([key, rows]) => [
      key,
      Array.isArray(rows) ? rows.filter(keepCandidate).map(sanitizeCandidate) : rows,
    ])) as ProfitDeskPayload['portfolio']
    : payload.portfolio;
  const sources = Array.isArray(payload.sources)
    ? payload.sources.filter(source => (
      !isRetiredProviderName(source.sourceKey) && !isRetiredProviderName(source.source)
    ))
    : payload.sources;
  return { ...payload, candidates, portfolio, sources };
}

function sortPicks(picks: Pick[]): Pick[] {
  return picks.sort((a, b) => (
    a.date.localeCompare(b.date) ||
    a.sport.localeCompare(b.sport) ||
    a.source.localeCompare(b.source) ||
    a.pick.localeCompare(b.pick)
  ));
}

export function setPickMode(mode: PickMode): void {
  activePickMode = mode;
}

export function getPickMode(): PickMode {
  return activePickMode;
}

export function isPickHistoryLoading(): boolean {
  return pickHistoryStatus === 'loading';
}

export async function loadAllData(options?: {
  includeHistory?: boolean;
  onLatest?: () => void;
  onHistory?: () => void;
}): Promise<Pick[]> {
  resultOverrides = readStorage<Record<string, PickResult>>(RESULT_STORAGE_KEY, {});
  gameTimes = readStorage<Record<string, string>>(GAME_TIME_STORAGE_KEY, {});
  await loadLatestCaches();
  if (options?.includeHistory !== false && !pickHistoryLoaded) pickHistoryStatus = 'loading';
  options?.onLatest?.();
  if (options?.includeHistory === false) return getAllPicks();
  void ensureHistory().then(() => options?.onHistory?.());
  return getAllPicks();
}

export function initHideScrapedPicks(): boolean {
  try {
    hideScrapedPicks = localStorage.getItem(HIDE_SCRAPED_KEY) === 'hidden';
  } catch {
    hideScrapedPicks = false;
  }
  return hideScrapedPicks;
}

export function getHideScrapedPicks(): boolean {
  return hideScrapedPicks;
}

export function setHideScrapedPicks(hidden: boolean): void {
  hideScrapedPicks = hidden;
  try {
    localStorage.setItem(HIDE_SCRAPED_KEY, hidden ? 'hidden' : 'shown');
  } catch {
    // The viewer remains usable when storage is blocked.
  }
}

export function initHideTennisPicks(): boolean {
  try {
    hideTennisPicks = localStorage.getItem(HIDE_TENNIS_KEY) === 'hidden';
  } catch {
    hideTennisPicks = false;
  }
  return hideTennisPicks;
}

export function getHideTennisPicks(): boolean {
  return hideTennisPicks;
}

export function setHideTennisPicks(hidden: boolean): void {
  hideTennisPicks = hidden;
  try {
    localStorage.setItem(HIDE_TENNIS_KEY, hidden ? 'hidden' : 'shown');
  } catch {
    // The viewer remains usable when storage is blocked.
  }
}

function isTennisPick(pick: Pick): boolean {
  return String(pick.sport || '').trim().toUpperCase() === 'TENNIS';
}

export function getTeamPicks(): Pick[] {
  return teamPicks;
}

export function getResearchPicks(date?: string): Pick[] {
  return researchPicks.filter(pick => (!date || pick.date === date)
    && (!hideScrapedPicks || pick.scraped !== true)
    && (!hideTennisPicks || !isTennisPick(pick)));
}

function bucketSport(key: string, bucket: ModelBucket = {}): string {
  if (/(?:^|_)nba(?:_|$)/.test(key)) return 'NBA';
  if (key.includes('fifa')) return 'FIFA WC';
  for (const sport of ['cfb', 'nfl', 'mlb', 'wnba', 'mls', 'tennis', 'ipl']) {
    if (key === sport || key.startsWith(`${sport}_`) || key.endsWith(`_${sport}`)) return sport.toUpperCase();
  }
  const row = Array.isArray(bucket.picks) ? recordValue(bucket.picks[0]) : {};
  return String(bucket.sport || row.sport || 'OTHER').toUpperCase();
}

function sourceErrorText(payload: ModelCachePayload, key: string, bucket: ModelBucket): string {
  const scopedErrors = [payload.errors, payload.external_feed_errors].flatMap(value => (
    Array.isArray(value) ? value.filter(error => String(error).startsWith(`${key}:`)) : []
  ));
  const errors = Array.isArray(bucket.errors) ? bucket.errors : [];
  const meta = recordValue(bucket.meta);
  const sportErrors = recordValue(meta.sportErrors);
  const sport = bucketSport(key).toLowerCase();
  const belongsToSource = (error: unknown): boolean => {
    const prefix = String(error || '').split(':', 1)[0].trim().toLowerCase();
    if (['cfb', 'nfl', 'mlb', 'wnba', 'mls', 'tennis', 'nba', 'nba_summer', 'fifa_world_cup', 'ipl'].includes(prefix)) {
      return prefix === sport;
    }
    if (isScrapedBucket(prefix)) return prefix === key;
    return true;
  };
  return [bucket.error, bucket.lastError, ...errors, ...scopedErrors, sportErrors[bucketSport(key).toLowerCase()]]
    .filter(error => Boolean(error) && belongsToSource(error)).map(String).join(' ');
}

/** Explain empty player slates using the same published diagnostics as the jobs. */
export function getPlayerSourceStatuses(date: string): SourceStatus[] {
  const payload = playerCachePayloads.filter(item => String(item.date || item.slate_date || '') <= date).at(-1);
  return ['mlb_player_props', 'wnba_player_props', 'nba_player_props'].map(key => {
    const bucket = recordValue(payload?.models?.[key]);
    const sport = key.split('_')[0].toUpperCase();
    const label = `${sport} Player Props`;
    const sourceDate = String(bucket.date || payload?.date || payload?.slate_date || '');
    const count = Array.isArray(bucket.picks) ? bucket.picks.length : 0;
    const status: SourceStatus = {
      key, label, sport, filterLabels: [label, String(bucket.model || '')], scraped: false,
      date: sourceDate, updatedAt: String(bucket.updatedAt || payload?.updatedAt || payload?.generatedAt || '') || null,
      pickCount: count, researchCount: 0, state: 'missing', detail: 'No refresh published for this date.',
    };
    const errors = Array.isArray(bucket.errors) ? bucket.errors.filter(Boolean) : [];
    if (!Object.keys(bucket).length) return status;
    if (sourceDate !== date) {
      status.state = 'stale';
      status.detail = 'Awaiting a player-prop refresh for this date.';
    } else if (bucket.ok === false || bucket.error || errors.length) {
      status.state = 'error';
      status.detail = 'Player-prop refresh reported an error; coverage may be incomplete.';
    } else if (bucket.ok === true && count) {
      status.state = 'ready';
      status.detail = `${count} player props published.`;
    } else if (bucket.ok === true) {
      status.state = 'empty';
      const evaluated = Math.max(Number(bucket.candidate_count) || 0, Number(bucket.scored_count) || 0,
        Number(bucket.consensus_rejected_count) || 0);
      const games = Array.isArray(bucket.games) ? bucket.games.length : Number(bucket.games) || 0;
      if (bucket.abstained === true && evaluated > 0) {
        status.detail = 'Refresh completed; evaluated candidates did not clear the publication rules.';
      } else if (games > 0) {
        status.state = 'error';
        status.detail = 'Games are scheduled, but no evaluated props were published. Check the next refresh.';
      } else {
        status.detail = 'No games scheduled for this date.';
      }
    }
    return status;
  });
}

/** Source health is based on published cache evidence, independent of view filters. */
export function getSourceStatuses(date: string): SourceStatus[] {
  const payload = teamCachePayloads.filter(item => String(item.date || '') <= date).at(-1);
  const buckets = payload ? cacheBuckets(payload) : {};
  // Football stays visible even before its first successful publication.
  const keys = new Set(['nfl', 'cfb', ...Object.keys(buckets)]);
  const statuses: SourceStatus[] = [];
  for (const key of keys) {
    const bucket = buckets[key];
    const sport = bucketSport(key, bucket);
    if (isRetiredBucket(key) || ARCHIVED_SPORTS.has(sport)) continue;
    const scraped = isScrapedBucket(key);
    const sourceDate = bucket ? bucketDate(bucket, String(payload?.date || '')) : '';
    const status: SourceStatus = {
      key, label: SOURCE_LABELS[key] || key, sport, scraped, date: sourceDate,
      filterLabels: [...new Set([
        SOURCE_LABELS[key] || key,
        ...Object.values(MARKET_SOURCE_LABELS[key] || {}),
        ...(bucket ? normalizedBucketPicks(key, bucket, String(payload?.date || '')).map(pick => pick.source) : []),
      ])],
      updatedAt: bucket ? bucketUpdatedAt(bucket, sourceDate === payload?.date ? payload : undefined) : null,
      pickCount: 0, researchCount: 0, state: 'missing', detail: 'No refresh published for this date.',
    };
    if (!bucket || typeof bucket !== 'object' || !payload) {
      statuses.push(status);
      continue;
    }
    const meta = recordValue(bucket.meta);
    const errors = sourceErrorText(payload, key, bucket);
    const failed = bucket.ok === false || bucket.refreshStatus === 'error' || Boolean(errors);
    const blocked = (numberOrNull(meta.blockedUrls) || 0) > 0
      || /cloudflare|captcha|forbidden|blocked|\b403\b|\b429\b/i.test(errors);
    if (sourceDate !== date) {
      status.state = 'stale';
      status.detail = failed || blocked
        ? 'Latest refresh failed; no forecasts published for this date.'
        : 'Awaiting a refresh for this date.';
      statuses.push(status);
      continue;
    }
    const scoped: ModelCachePayload = { date, models: { [key]: bucket } };
    const tracked = payload.models?.[key]
      ? picksFromCache({ date, models: { [key]: payload.models[key] } })
        .filter(pick => pick.date === date && !isPlayerScopedPick(pick))
      : [];
    status.pickCount = new Set(tracked.map(pick => pick.id)).size;
    status.researchCount = new Set(researchFromCache(scoped)
      .filter(pick => pick.date === date && !tracked.some(row => row.id === pick.id))
      .map(pick => pick.id)).size;
    const missing = Array.isArray(meta.missingMatchups) ? meta.missingMatchups.length : 0;
    const countBySport = recordValue(meta.officialMatchupCounts);
    const coverage = recordValue(bucket.coverage);
    const official = numberOrNull(meta.officialMatchups ?? countBySport[sport.toLowerCase()]
      ?? coverage.official_games ?? bucket.slate_games);
    const noGames = official === 0
      || (Array.isArray(meta.zeroSlateSports) && meta.zeroSlateSports.includes(sport.toLowerCase()))
      || /no (?:official )?(?:mls |nfl |cfb |wnba |mlb )?(?:games|matchups)(?: on| for| found)/i.test(String(bucket.note || ''))
      || /active slate:\s*0 game/i.test(String(bucket.note || ''));
    if (failed || blocked || missing > 0) {
      status.state = 'error';
      status.detail = blocked ? 'Upstream access blocked; coverage is incomplete.'
        : missing > 0 ? `Incomplete coverage: ${missing} scheduled matchup${missing === 1 ? '' : 's'} missing.`
          : 'Latest refresh failed; awaiting a successful update.';
      if (status.pickCount + status.researchCount > 0) status.detail += ' Available same-day picks remain visible.';
    } else if (status.pickCount + status.researchCount > 0) {
      status.state = 'ready';
      status.detail = status.pickCount > 0
        ? `${status.pickCount} tracked pick${status.pickCount === 1 ? '' : 's'} published.`
        : scraped ? 'Provider forecasts published for research; excluded from tracked bets.'
          : 'Research forecasts published; the model is still in evaluation.';
    } else if (bucket.ok === true) {
      status.state = 'empty';
      status.detail = noGames ? 'No games scheduled for this date.'
        : key === 'cfb' && official != null && official > 0
          && (coverage.forecast_games === 0 || coverage.pregame_games === 0)
          ? (numberOrNull(coverage.incomplete_games) || 0) > 0
            ? 'No eligible pregame FBS matchups; slate details are incomplete.'
            : 'No eligible pregame FBS matchups; started games and unsupported opponents are excluded.'
        : /no fully priced/i.test(String(bucket.note || '')) ? 'No fully priced games; no qualified picks.'
          : scraped ? 'Refresh completed; no provider forecasts published for this date.'
            : 'Refresh completed; no picks met the qualification rules.';
    } else {
      status.detail = 'No completed refresh recorded for this date.';
    }
    statuses.push(status);
  }
  return statuses.sort((left, right) => left.sport.localeCompare(right.sport)
    || Number(left.scraped) - Number(right.scraped) || left.label.localeCompare(right.label));
}

export function getAllPicks(): Pick[] {
  let picks = activePickMode === 'player' ? playerPicks : teamPicks;
  // View filters and nothing more. Applied at the single point every view
  // reads from, so hidden rows disappear consistently — home, search,
  // rankings, trends, counts — without any view needing to know about it.
  // The rows stay loaded, graded and in the cache; flipping a filter back
  // restores them exactly. Default off, so an untouched viewer behaves as before.
  if (hideScrapedPicks) picks = picks.filter(pick => pick.scraped !== true);
  if (hideTennisPicks) picks = picks.filter(pick => !isTennisPick(pick));
  return picks;
}

export function getParlayCardsPayload(date?: string): ParlayCardsPayload | null {
  if (date) {
    return parlayPayloads.find(payload => payload.date === date) || null;
  }
  return latestParlayPayload;
}

export function getParlayCardPayloads(): ParlayCardsPayload[] {
  return parlayPayloads;
}

export function getProfitDeskPayload(date?: string): ProfitDeskPayload | null {
  if (date) {
    return profitDeskPayloads.find(payload => payload.date === date) || null;
  }
  return latestProfitDeskPayload;
}

export function getProfitDeskPayloads(): ProfitDeskPayload[] {
  return profitDeskPayloads;
}

export function getResults(): Record<string, PickResult> {
  return resultOverrides;
}

export function setLocalResult(id: string, result: PickResult): void {
  resultOverrides[id] = result;
  writeStorage(RESULT_STORAGE_KEY, resultOverrides);
  const pick = getAllPicks().find(item => item.id === id);
  if (pick) {
    pick.result = result;
    pick.pl = calculateProfit(pick, result);
  }
}

export function setLocalGameTime(id: string, startTime: string): void {
  gameTimes[id] = startTime;
  writeStorage(GAME_TIME_STORAGE_KEY, gameTimes);
  const pick = getAllPicks().find(item => item.id === id);
  if (pick) {
    pick.start_time = startTime;
    pick.game_start_time = startTime;
  }
}

function latestPayloadTimestamp(value: unknown): number {
  if (!value || typeof value !== 'object') return 0;
  let latest = 0;
  for (const [key, nested] of Object.entries(value as Record<string, unknown>)) {
    if ((key === 'generatedAt' || key === 'updatedAt') && typeof nested === 'string') {
      const timestamp = new Date(nested).getTime();
      if (Number.isFinite(timestamp)) latest = Math.max(latest, timestamp);
    } else if (nested && typeof nested === 'object') {
      latest = Math.max(latest, latestPayloadTimestamp(nested));
    }
  }
  return latest;
}

export function getCacheStatus(): { date: string; runTime: string; updatedAt: string; pickCount: number } {
  const latestCache = activePickMode === 'player' ? latestPlayerCache : latestTeamCache;
  const latestTimestamp = latestPayloadTimestamp(latestCache);
  const parsed = new Date(latestTimestamp);
  return {
    date: String(latestCache?.date || latestCache?.slate_date || ''),
    runTime: !latestTimestamp || Number.isNaN(parsed.getTime())
      ? ''
      : parsed.toLocaleTimeString('en-US', {
        timeZone: 'America/Chicago',
        hour: 'numeric',
        minute: '2-digit',
        timeZoneName: 'short',
      }),
    updatedAt: latestTimestamp ? parsed.toISOString() : '',
    pickCount: getAllPicks().length,
  };
}
