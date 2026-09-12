import assert from 'node:assert/strict';
import { afterEach, test } from 'node:test';

import {
  getTeamPicks,
  getResearchPicks,
  getSourceStatuses,
  getParlayCardsPayload,
  getProfitDeskPayload,
  loadAllData,
  loadLatestAndNewestDated,
  setPickMode,
  setHideScrapedPicks,
  setHideTennisPicks,
} from '../src/data.ts';

type CachePayload = Record<string, unknown>;

const realFetch = globalThis.fetch;

function installFetch(responses: Map<string, CachePayload>): string[] {
  const requests: string[] = [];
  globalThis.fetch = async (input: RequestInfo | URL): Promise<Response> => {
    const path = typeof input === 'string' ? input : input.toString();
    requests.push(path);
    const payload = responses.get(path);
    if (!payload) return new Response(null, { status: 404 });
    return new Response(JSON.stringify(payload), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  };
  return requests;
}

afterEach(() => {
  globalThis.fetch = realFetch;
  setHideScrapedPicks(false);
  setHideTennisPicks(false);
});

test('loads a newer dated payload alongside latest.json', { concurrency: false }, async () => {
  const requests = installFetch(new Map([
    ['./data/model_cache/latest.json', { date: '2026-08-26' }],
    ['./data/model_cache/index.json', { files: ['2026-08-25.json', '2026-08-27.json'] }],
    ['./data/model_cache/2026-08-27.json', { date: '2026-08-27' }],
  ]));

  const payloads = await loadLatestAndNewestDated<{ date?: string }>(
    './data/model_cache/latest.json',
    './data/model_cache/index.json',
    './data/model_cache',
    payload => payload.date || '',
  );

  assert.deepEqual(payloads.map(payload => payload.date), ['2026-08-26', '2026-08-27']);
  assert.ok(requests.includes('./data/model_cache/index.json'));
  assert.ok(requests.includes('./data/model_cache/2026-08-27.json'));
});

test('does not refetch a dated payload when latest.json already has that date', { concurrency: false }, async () => {
  const requests = installFetch(new Map([
    ['./data/model_cache/latest.json', { date: '2026-08-27' }],
    ['./data/model_cache/index.json', { files: ['2026-08-26.json', '2026-08-27.json'] }],
  ]));

  const payloads = await loadLatestAndNewestDated<{ date?: string }>(
    './data/model_cache/latest.json',
    './data/model_cache/index.json',
    './data/model_cache',
    payload => payload.date || '',
  );

  assert.deepEqual(payloads.map(payload => payload.date), ['2026-08-27']);
  assert.ok(!requests.includes('./data/model_cache/2026-08-27.json'));
});

test('falls back to the newest dated payload when latest.json is unavailable', { concurrency: false }, async () => {
  const requests = installFetch(new Map([
    ['./data/model_cache/index.json', { files: ['2026-08-27.json'] }],
    ['./data/model_cache/2026-08-27.json', { date: '2026-08-27' }],
  ]));

  const payloads = await loadLatestAndNewestDated<{ date?: string }>(
    './data/model_cache/latest.json',
    './data/model_cache/index.json',
    './data/model_cache',
    payload => payload.date || '',
  );

  assert.deepEqual(payloads.map(payload => payload.date), ['2026-08-27']);
});

test('first paint keeps prior-day models on their original date', { concurrency: false }, async () => {
  const requests = installFetch(new Map([
    ['./data/model_cache/latest.json', {
      date: '2026-08-26',
      models: {
        mlb_new: {
          ok: true,
          picks: [{ sport: 'MLB', pick: 'Yesterday model', decision: 'BET' }],
        },
      },
    }],
    ['./data/model_cache/index.json', { files: ['2026-08-26.json', '2026-08-27.json'] }],
    ['./data/model_cache/2026-08-27.json', {
      date: '2026-08-27',
      models: {
        scores24_mlb: {
          ok: true,
          picks: [{ sport: 'MLB', pick: 'Today Scores24', decision: 'BET' }],
        },
      },
    }],
  ]));

  setPickMode('team');
  await loadAllData({ includeHistory: false });

  const priorDay = getTeamPicks().filter(pick => pick.date === '2026-08-26');
  const today = getTeamPicks().filter(pick => pick.date === '2026-08-27');
  assert.deepEqual(priorDay.map(pick => pick.pick), ['Yesterday model']);
  assert.deepEqual(today.map(pick => pick.pick), ['Today Scores24']);
  assert.ok(requests.includes('./data/model_cache/2026-08-27.json'));
});

test('same-day refresh replaces picks, grades, and summary caches', { concurrency: false }, async () => {
  const date = '2026-09-06';
  const responses = new Map<string, CachePayload>([
    ['./data/model_cache/latest.json', { date, models: {
      nfl: { ok: true, picks: [{ id: 'refresh-pick', sport: 'NFL', pick: 'Original pick', decision: 'BET' }] },
    } }],
    ['./data/parlay_cards/latest.json', { date, cards: [{ id: 'original-card' }] }],
    ['./data/profit_desk/latest.json', { date, candidates: [{ id: 'original-candidate' }] }],
  ]);
  installFetch(responses);
  await loadAllData({ includeHistory: false });
  responses.set('./data/model_cache/latest.json', { date, models: {
    nfl: { ok: true, picks: [{ id: 'refresh-pick', sport: 'NFL', pick: 'Corrected pick', decision: 'BET', result: 'win' }] },
  } });
  responses.set('./data/parlay_cards/latest.json', { date, cards: [{ id: 'refreshed-card' }] });
  responses.set('./data/profit_desk/latest.json', { date, candidates: [{ id: 'refreshed-candidate' }] });
  await loadAllData({ includeHistory: false });
  assert.deepEqual(getTeamPicks().filter(pick => pick.date === date).map(pick => [pick.pick, pick.result]), [
    ['Corrected pick', 'win'],
  ]);
  assert.equal(getParlayCardsPayload(date)?.cards?.[0]?.id, 'refreshed-card');
  assert.equal(getProfitDeskPayload(date)?.candidates?.[0]?.id, 'refreshed-candidate');

  responses.set('./data/model_cache/latest.json', { date, models: { nfl: { ok: true, picks: [] } } });
  await loadAllData({ includeHistory: false });
  assert.deepEqual(getTeamPicks().filter(pick => pick.date === date), []);
});

test('publishes scraped passes and CFB shadow forecasts only as zero-stake research', { concurrency: false }, async () => {
  const date = '2026-09-07';
  const pass = { id: 'research-feed', date, sport: 'CFB', pick: 'Provider forecast', decision: 'PASS', units: 2 };
  installFetch(new Map([
    ['./data/model_cache/latest.json', { date, models: {
      cfb: { ok: true, shadow_mode: true, picks: [
        { id: 'research-cfb', sport: 'CFB', pick: 'Shadow forecast', decision: 'BET', units: 3, result: 'win', odds: -110, price_verified: true },
      ] },
      scores24_cfb: { ok: true, picks: [pass, pass, { ...pass, id: 'wrong-date', date: '2026-09-06' }] },
      sportytrader_cfb: { ok: false, picks: [{ ...pass, id: 'failed-feed' }] },
      forebet_mlb: { date: '2026-09-05', ok: true, picks: [
        { sport: 'MLB', pick: 'Stale carried forecast', decision: 'PASS' },
      ] },
      covers_cfb: { ok: true, picks: [{ ...pass, id: 'retired' }] },
      sportytrader_nba: { ok: true, picks: [{ ...pass, id: 'archived', sport: 'NBA' }] },
      nfl: { ok: true, picks: [{ id: 'tracked-nfl', sport: 'NFL', pick: 'Tracked model', decision: 'BET' }] },
    }, external_feeds: {
      scores24_cfb: { ok: true, picks: [pass] },
      tennistonic_tennis: { date, ok: true, picks: [{ id: 'research-tennis', sport: 'TENNIS', pick: 'Tennis forecast', decision: 'PASS' }] },
    } }],
  ]));
  await loadAllData({ includeHistory: false });
  const research = getResearchPicks(date);
  assert.deepEqual(research.map(pick => pick.id).sort(), ['research-cfb', 'research-feed', 'research-tennis']);
  assert.ok(research.every(pick => pick.research === true && pick.decision === 'PASS' && pick.units === 0 && pick.pl === 0));
  assert.deepEqual(getTeamPicks().filter(pick => pick.date === date).map(pick => pick.id), ['tracked-nfl']);
  assert.equal(getSourceStatuses(date).find(source => source.key === 'cfb')?.researchCount, 1);
  assert.equal(getSourceStatuses(date).find(source => source.key === 'scores24_cfb')?.researchCount, 1);

  setHideTennisPicks(true);
  assert.equal(getResearchPicks(date).length, 2);
  setHideScrapedPicks(true);
  assert.deepEqual(getResearchPicks(date).map(pick => pick.id), ['research-cfb']);
  assert.equal(getSourceStatuses(date).find(source => source.key === 'scores24_cfb')?.researchCount, 1);
});

test('posts in-house model PASS on the team board and keeps scraped PASS as research', { concurrency: false }, async () => {
  const date = '2026-09-13';
  installFetch(new Map([
    ['./data/model_cache/latest.json', { date, models: {
      nfl: { ok: true, shadow_mode: false, picks: [
        { id: 'nfl-pass', sport: 'NFL', pick: 'Seahawks ML (Patriots @ Seahawks)', decision: 'PASS', units: 0, probability: 0.61, matchup: 'Patriots @ Seahawks' },
        { id: 'nfl-bet', sport: 'NFL', pick: 'Seahawks -3 (Patriots @ Seahawks)', decision: 'BET', units: 0.5, matchup: 'Patriots @ Seahawks' },
        { id: 'nfl-low-pass', sport: 'NFL', pick: 'Patriots ML', decision: 'PASS', units: 0, probability: 0.24 },
      ] },
      cfb: { ok: true, shadow_mode: false, picks: [
        { id: 'cfb-pass', sport: 'CFB', pick: 'Home State ML', decision: 'PASS', units: 0, probability: 0.74 },
        { id: 'cfb-low-pass', sport: 'CFB', pick: 'Away Dog ML +500', decision: 'PASS', units: 0, probability: 0.247 },
        { id: 'cfb-lean', sport: 'CFB', pick: 'Home State -3.5', decision: 'LEAN', units: 0.25 },
      ] },
      scores24_nfl: { ok: true, picks: [
        { id: 'scraped-nfl-pass', sport: 'NFL', pick: 'Chiefs -3.5', decision: 'PASS', units: 0 },
      ] },
    } }],
  ]));
  await loadAllData({ includeHistory: false });
  const team = getTeamPicks().filter(pick => pick.date === date).map(pick => pick.id).sort();
  assert.deepEqual(team, ['cfb-lean', 'cfb-pass', 'nfl-bet', 'nfl-pass']);
  assert.deepEqual(getResearchPicks(date).map(pick => pick.id), ['scraped-nfl-pass']);
  assert.ok(getResearchPicks(date).every(pick => pick.research === true && pick.decision === 'PASS' && pick.units === 0));
  const statuses = new Map(getSourceStatuses(date).map(status => [status.key, status]));
  assert.equal(statuses.get('nfl')?.pickCount, 2);
  assert.equal(statuses.get('cfb')?.pickCount, 2);
  assert.equal(statuses.get('cfb')?.researchCount, 0);
  assert.equal(statuses.get('scores24_nfl')?.researchCount, 1);
  assert.equal(statuses.get('scores24_nfl')?.pickCount, 0);
});

test('source health distinguishes blocked, stale, missing, no-games, and unqualified results', { concurrency: false }, async () => {
  const date = '2026-09-08';
  const forecast = { id: 'health-research', sport: 'MLB', pick: 'Research only', decision: 'PASS' };
  installFetch(new Map([
    ['./data/model_cache/latest.json', { date, updatedAt: '2026-09-08T12:00:00Z', models: {
      nfl: { ok: true, picks: [], note: 'NFL active slate: 0 game(s), 0 row(s).' },
      mlb_new: { ok: false, error: '502 upstream URL https://private.example/key', picks: [] },
      mlb_first_five: { ok: true, games: [{ matchup: 'Away @ Home' }], picks: [{ ...forecast, decision: 'PASS' }] },
      sportytrader_wnba: { ok: true, picks: [], meta: { zeroSlateSports: ['wnba'] } },
      sportytrader_mlb: { ok: true, picks: [], errors: ['cfb: blocked upstream'], meta: { sportErrors: { cfb: 'blocked upstream' } } },
      sportytrader_cfb: { ok: true, picks: [], errors: ['cfb: blocked upstream'], meta: { sportErrors: { cfb: 'blocked upstream' } } },
      scores24_mlb: { ok: true, picks: [forecast, forecast, { ...forecast, id: 'stale-row', date: '2026-09-07' }], meta: { officialMatchups: 2, missingMatchups: ['Away @ Home'] } },
      tennistonic_tennis: { ok: true, picks: [], meta: { officialMatchups: 4, expectedMatchups: 0, blockedUrls: 4 } },
      covers_mlb: { ok: true, picks: [] },
      nba: { ok: true, picks: [] },
    }, external_feeds: {
      forebet_mlb: { date: '2026-09-07', updatedAt: '2026-09-07T12:00:00Z', ok: true, picks: [forecast] },
      scores24_fifa_world_cup: { date, ok: true, picks: [] },
    }, external_feed_errors: ['forebet_mlb: Cloudflare blocked https://private.example/token'] }],
  ]));
  await loadAllData({ includeHistory: false });
  const statuses = getSourceStatuses(date);
  const byKey = new Map(statuses.map(status => [status.key, status]));
  assert.equal(byKey.get('cfb')?.state, 'missing');
  assert.ok(byKey.get('cfb')?.filterLabels.includes('CFB ML'));
  assert.ok(byKey.get('mlb_new')?.filterLabels.includes('MLB Total'));
  assert.equal(byKey.get('nfl')?.detail, 'No games scheduled for this date.');
  assert.equal(byKey.get('sportytrader_wnba')?.detail, 'No games scheduled for this date.');
  assert.equal(byKey.get('sportytrader_mlb')?.state, 'empty');
  assert.equal(byKey.get('sportytrader_cfb')?.state, 'error');
  assert.equal(byKey.get('mlb_first_five')?.detail, '1 tracked pick published.');
  assert.equal(byKey.get('mlb_first_five')?.pickCount, 1);
  assert.equal(byKey.get('mlb_new')?.state, 'error');
  assert.equal(byKey.get('tennistonic_tennis')?.state, 'error');
  assert.match(byKey.get('tennistonic_tennis')?.detail || '', /blocked/);
  assert.equal(byKey.get('scores24_mlb')?.state, 'error');
  assert.equal(byKey.get('scores24_mlb')?.researchCount, 1);
  assert.match(byKey.get('scores24_mlb')?.detail || '', /1 scheduled matchup/);
  assert.equal(byKey.get('forebet_mlb')?.state, 'stale');
  assert.equal(byKey.get('forebet_mlb')?.date, '2026-09-07');
  assert.equal(byKey.get('forebet_mlb')?.updatedAt, '2026-09-07T12:00:00Z');
  assert.equal(byKey.get('forebet_mlb')?.researchCount, 0);
  assert.match(byKey.get('forebet_mlb')?.detail || '', /failed/);
  assert.ok(statuses.every(status => !/https?:|private|502/.test(status.detail)));
  assert.ok(!byKey.has('covers_mlb') && !byKey.has('nba') && !byKey.has('scores24_fifa_world_cup'));
});

test('failed refresh preserves same-day forecasts and reports failure honestly', { concurrency: false }, async () => {
  const date = '2026-09-09';
  installFetch(new Map([
    ['./data/model_cache/latest.json', { date, models: {
      cfb: { date, ok: true, shadow_mode: true, picks: [], note: 'No fully priced FBS games on the CFB slate.' },
      nfl: { date, ok: false, preserved_after_refresh_error: true, error: 'Upstream failed', picks: [
        { id: 'preserved-model', date, sport: 'NFL', pick: 'Earlier model pick', decision: 'BET' },
        { id: 'wrong-day-model', date: '2026-09-08', sport: 'NFL', pick: 'Prior-day pick', decision: 'BET' },
      ] },
      scores24_cfb: { date, ok: true, refreshStatus: 'error', lastAttemptDate: date,
        lastAttemptAt: '2026-09-09T15:00:00Z', lastError: 'Cloudflare blocked https://example.test',
        updatedAt: '2026-09-09T12:00:00Z', picks: [
          { id: 'preserved-research', sport: 'CFB', pick: 'Earlier forecast', decision: 'PASS' },
        ] },
    } }],
  ]));
  await loadAllData({ includeHistory: false });
  const byKey = new Map(getSourceStatuses(date).map(status => [status.key, status]));
  assert.equal(byKey.get('cfb')?.state, 'empty');
  assert.equal(byKey.get('cfb')?.detail, 'No fully priced games; no qualified picks.');
  assert.equal(byKey.get('scores24_cfb')?.state, 'error');
  assert.equal(byKey.get('scores24_cfb')?.researchCount, 1);
  assert.equal(byKey.get('scores24_cfb')?.updatedAt, '2026-09-09T12:00:00Z');
  assert.equal(byKey.get('nfl')?.state, 'error');
  assert.equal(byKey.get('nfl')?.pickCount, 1);
  assert.deepEqual(getTeamPicks().filter(pick => pick.date === date).map(pick => pick.id), ['preserved-model']);
  assert.deepEqual(getResearchPicks(date).map(pick => pick.id), ['preserved-research']);
});

test('a delayed history request cannot overwrite a newer latest refresh', { concurrency: false, timeout: 5000 }, async () => {
  const firstDate = '2026-09-10';
  const nextDate = '2026-09-11';
  let latest: CachePayload = { date: firstDate, models: {} };
  let manifestReads = 0;
  let historyStarted!: () => void;
  let releaseHistory!: (payload: CachePayload) => void;
  const started = new Promise<void>(resolve => { historyStarted = resolve; });
  const delayedHistory = new Promise<CachePayload>(resolve => { releaseHistory = resolve; });
  globalThis.fetch = async (input: RequestInfo | URL): Promise<Response> => {
    const path = String(input);
    let payload: CachePayload;
    if (path === './data/model_cache/latest.json') payload = latest;
    else if (path === './data/model_cache/index.json') {
      manifestReads += 1;
      payload = { files: manifestReads === 1 ? [`${firstDate}.json`] : [`${firstDate}.json`, `${nextDate}.json`] };
    } else if (path === `./data/model_cache/${nextDate}.json`) {
      historyStarted();
      payload = await delayedHistory;
    } else return new Response(null, { status: 404 });
    return new Response(JSON.stringify(payload), { status: 200 });
  };
  let historyFinished!: () => void;
  const finished = new Promise<void>(resolve => { historyFinished = resolve; });
  await loadAllData({ onHistory: historyFinished });
  await started;
  latest = { date: nextDate, models: { nfl: { ok: true, picks: [
    { id: 'history-race', sport: 'NFL', pick: 'Fresh latest', decision: 'BET' },
  ] } } };
  await loadAllData({ includeHistory: false });
  releaseHistory({ date: nextDate, models: { nfl: { ok: true, picks: [
    { id: 'history-race', sport: 'NFL', pick: 'Old history response', decision: 'BET' },
  ] } } });
  await finished;
  assert.deepEqual(getTeamPicks().filter(pick => pick.date === nextDate).map(pick => pick.pick), ['Fresh latest']);
});

test('CFB health distinguishes an empty official slate from excluded or incomplete games', { concurrency: false }, async () => {
  const date = '2026-09-12';
  const responses = new Map<string, CachePayload>();
  installFetch(responses);
  const publishCoverage = async (coverage: Record<string, number>) => {
    responses.set('./data/model_cache/latest.json', { date, models: {
      cfb: { date, ok: true, shadow_mode: true, picks: [], games: [], coverage },
    } });
    await loadAllData({ includeHistory: false });
    return getSourceStatuses(date).find(status => status.key === 'cfb');
  };
  assert.equal((await publishCoverage({ official_games: 0, pregame_games: 0 }))?.detail, 'No games scheduled for this date.');
  const excluded = await publishCoverage({ official_games: 3, pregame_games: 1, forecast_games: 0, started_games: 2, excluded_non_fbs_games: 1 });
  assert.equal(excluded?.state, 'empty');
  assert.match(excluded?.detail || '', /No eligible pregame.*started games and unsupported opponents/);
  const incomplete = await publishCoverage({ official_games: 1, pregame_games: 0, incomplete_games: 1 });
  assert.match(incomplete?.detail || '', /slate details are incomplete/);
});

test('all active football scraper sources publish research rows with league labels', { concurrency: false }, async () => {
  const date = '2026-09-10';
  const models = Object.fromEntries(['sportytrader', 'sportsgambler', 'scores24', 'forebet'].flatMap(provider =>
    ['cfb', 'nfl'].map(sport => [`${provider}_${sport}`, { ok: true, date, picks: [
      { id: `${provider}_${sport}`, sport: sport.toUpperCase(), pick: 'Home ML', decision: 'PASS', units: 0 },
    ] }]),
  ));
  installFetch(new Map([['./data/model_cache/latest.json', { date, models }]]));
  await loadAllData({ includeHistory: false });
  assert.equal(getTeamPicks().filter(pick => pick.date === date).length, 0);
  assert.equal(getResearchPicks(date).length, 8);
  const statuses = new Map(getSourceStatuses(date).map(status => [status.key, status]));
  for (const key of Object.keys(models)) {
    assert.equal(statuses.get(key)?.researchCount, 1);
    assert.equal(statuses.get(key)?.pickCount, 0);
  }
  assert.equal(getResearchPicks(date).find(pick => pick.id === 'forebet_cfb')?.source, 'ForebetCFB');
  assert.equal(getResearchPicks(date).find(pick => pick.id === 'forebet_nfl')?.source, 'ForebetNFL');
});

test('failed refresh retains loaded picks while reporting download failure', { concurrency: false }, async () => {
  const { didLatestCacheLoad } = await import('../src/data.ts');
  setPickMode('team');
  installFetch(new Map([['./data/model_cache/latest.json', { date: '2026-09-13', models: {
    nfl: { ok: true, picks: [{ id: 'offline-retain', sport: 'NFL', pick: 'Home ML', decision: 'BET' }] },
  } }]]));
  await loadAllData({ includeHistory: false });
  assert.equal(didLatestCacheLoad(), true);
  installFetch(new Map());
  await loadAllData({ includeHistory: false });
  assert.equal(didLatestCacheLoad(), false);
  assert.ok(getTeamPicks().some(pick => pick.id === 'offline-retain'));
});

test('player source status distinguishes abstention, missing data, failure and stale slates', { concurrency: false }, async () => {
  const { getPlayerSourceStatuses } = await import('../src/data.ts');
  const date = '2026-09-14';
  const responses = new Map<string, CachePayload>();
  installFetch(responses);
  const publish = async (bucket: CachePayload) => {
    responses.set('./data/player_props_cache/latest.json', { date, models: { mlb_player_props: bucket } });
    await loadAllData({ includeHistory: false });
    return getPlayerSourceStatuses(date).find(source => source.key === 'mlb_player_props')!;
  };
  const abstained = await publish({ ok: true, games: 5, picks: [], abstained: true, candidate_count: 1445 });
  assert.equal(abstained.state, 'empty');
  assert.match(abstained.detail, /did not clear/);
  assert.equal((await publish({ ok: true, games: 5, picks: [], abstained: true })).state, 'error');
  assert.equal((await publish({ ok: false, games: 5, picks: [] })).state, 'error');
  assert.equal((await publish({ ok: true, games: 0, picks: [] })).detail, 'No games scheduled for this date.');
  assert.equal(getPlayerSourceStatuses('2026-09-15')[0].state, 'stale');
  assert.equal(getPlayerSourceStatuses(date).find(source => source.key === 'wnba_player_props')?.state, 'missing');
  assert.equal(getPlayerSourceStatuses(date).find(source => source.key === 'nfl_player_props')?.state, 'missing');
  assert.equal(getPlayerSourceStatuses(date).find(source => source.key === 'cfb_player_props')?.state, 'missing');
});
