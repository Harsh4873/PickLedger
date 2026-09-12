from copy import deepcopy
from datetime import datetime, timezone

import player_props.cfb as cfb
from player_props.variants import build_variant_buckets
from scripts.merge_player_props_cache_payload import merge_payload

DAY = '2026-09-12'


def event():
    return {'id': 'espn-game', 'date': DAY + 'T16:00:00Z', 'name': 'Away at Home',
            'status': {'type': {'state': 'pre'}},
            'competitions': [{'competitors': [
                {'homeAway': side, 'team': {'id': tid, 'displayName': name, 'abbreviation': abbr}}
                for side, tid, name, abbr in [('home', '245', 'Texas A&M Aggies', 'TA&M'), ('away', '9', 'Arizona State Sun Devils', 'ASU')]]}]}


def game():
    return {'id': 'an-game', 'start_time': DAY + 'T16:00:00Z', 'status': 'scheduled',
            'home_team_id': '358', 'away_team_id': '349', 'teams': [
                {'id': '358', 'full_name': 'Texas A&M Aggies', 'abbr': 'TA&M'},
                {'id': '349', 'full_name': 'Arizona State Sun Devils', 'abbr': 'ASU'}]}


def prop_payload():
    def entry(stat, value):
        return {'player_id': 'an-player', 'lines': {'49': [
            {'event_id': 'an-game', 'player_id': 'an-player', 'value': value, 'side': side,
             'odds': odds, 'period': 'event', 'is_live': False, 'line_status': 'normal'}
            for side, odds in [('under', -105), ('over', -115)]]}}
    return {'players': {'an-player': {'id': 'an-player', 'full_name': 'Marcel Reed', 'team_id': '358'}},
            'player_props': {key: [entry(key, 230.5 if 'passing' in key else 30.5)] for key in list(cfb.MARKETS)[:2]}}


def gamelog():
    return {'names': ['passingYards', 'passingAttempts', 'rushingYards'],
            'events': {str(i): {'gameDate': f'2025-11-{i + 1:02}T18:00:00Z'} for i in range(6)},
            'seasonTypes': [{'displayName': 'Regular Season', 'categories': [{'type': 'event',
                'events': [{'eventId': str(i), 'stats': [str(220 + i * 10), '30', str(i * 10)]} for i in range(6)]}]}]}


class Client:
    def football_scoreboard(self, *args):
        return {'events': [event()], 'season': {'year': 2026}}

    def football_injuries(self, *args):
        return {'injuries': []}

    def cfb_market_json(self, path, *args):
        if 'scoreboard' in path:
            return {'games': [game()]}
        if path == 'v1/books':
            return {'books': [{'id': '49', 'display_name': 'FanDuel NJ'}]}
        return prop_payload()

    def football_roster(self, league, tid):
        return {'athletes': [{'position': 'offense', 'items': [
            {'id': 'espn-player', 'displayName': 'Marcel Reed'}] if tid == '245' else []}]}

    def football_player_gamelog(self, league, aid, season):
        return gamelog() if season == 2025 else {'names': [], 'events': {}, 'seasonTypes': []}


def freeze(monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 12, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(cfb, 'datetime', Clock)


def test_realistic_nested_roster_prior_season_market_to_publication_and_merge(monkeypatch, tmp_path):
    freeze(monkeypatch)
    base = cfb.generate_cfb_candidate_model(Client(), DAY)
    assert not base['errors']
    assert len(base['picks']) == 2
    for pick in base['picks']:
        assert pick['game_id'] == 'espn-game'
        assert pick['player_id'] == 'espn-player'
        assert pick['provider_player_id'] == 'an-player'
        assert pick['decision'] == 'PASS' and pick['units'] == 0
        assert not pick['ml_model_active'] and not pick['probability_calibrated']
        assert pick['projection_validation']['samples'] == 2
    models = build_variant_buckets(sport='CFB', date_iso=DAY, base_model=base)
    merged = merge_payload({'date': DAY, 'models': models}, tmp_path, tmp_path)
    assert len(merged['models']['cfb_player_props']['picks']) == 2
    assert merged['models']['cfb_player_props']['publication_status'] == 'baseline_projections'


def test_join_rejects_wrong_teams_kickoff_and_ambiguous_games():
    assert cfb._match_game(event(), [game()])
    assert cfb._match_game(event(), [game(), game()]) is None
    wrong = game(); wrong['start_time'] = '2026-09-13T16:00:00Z'
    assert cfb._match_game(event(), [wrong]) is None
    wrong = game(); wrong['home_team_id'], wrong['away_team_id'] = wrong['away_team_id'], wrong['home_team_id']
    assert cfb._match_game(event(), [wrong]) is None


def test_quote_pair_requires_same_player_game_book_line_and_current_market():
    p = prop_payload()
    assert len(cfb._quotes(p, {'49': 'FanDuel NJ'}, 'an-game')) == 2
    for field, value in [('player_id', 'wrong'), ('event_id', 'wrong'), ('value', 231.5),
                         ('is_live', True), ('line_status', 'suspended'), ('period', 'firsthalf')]:
        broken = deepcopy(p)
        for entries in broken['player_props'].values():
            entries[0]['lines']['49'][0][field] = value
        assert not cfb._quotes(broken, {'49': 'FanDuel NJ'}, 'an-game')
    for name in ('Consensus', 'Open'):
        assert not cfb._quotes(p, {'49': name}, 'an-game')


def test_history_strictly_excludes_undated_today_and_future_and_keeps_zero():
    p = gamelog()
    p['events']['0']['gameDate'] = DAY + 'T16:00:00Z'
    p['events']['1']['gameDate'] = '2026-10-01T16:00:00Z'
    p['events']['2'] = {}
    p['seasonTypes'][0]['categories'][0]['events'][-1]['stats'][2] = '0'
    rows = cfb._history([p, p], DAY)
    assert len(rows) == 3
    assert cfb._series(rows, 'rushing_yards')[0] == 0
    assert len(cfb._series(rows, 'passing_yards')) == 3


def test_rolling_validation_uses_older_games_only():
    assert cfb._backtest([100, 10, 10, 10, 10]) == {
        'samples': 1, 'mae': 90.0, 'method': 'rolling origin; each prediction uses only older games'}


def test_ambiguous_roster_name_is_not_resolved(monkeypatch):
    freeze(monkeypatch)
    client = Client()
    roster = client.football_roster('college-football', '245')
    roster['athletes'][0]['items'].append({'id': 'another', 'displayName': 'Marcel Reed'})
    monkeypatch.setattr(client, 'football_roster', lambda *args: roster)
    base = cfb.generate_cfb_candidate_model(client, DAY)
    assert base['picks'] == []
    assert base['diagnostics'][0]['unmatched_players']


def test_started_game_and_market_outage_never_publish(monkeypatch):
    freeze(monkeypatch)
    client = Client()
    original = client.football_scoreboard
    def live(*args):
        result = original(*args)
        result['events'][0]['status']['type']['state'] = 'in'
        return result
    monkeypatch.setattr(client, 'football_scoreboard', live)
    assert cfb.generate_cfb_candidate_model(client, DAY)['picks'] == []
    def boom(*args):
        raise RuntimeError('market feed unavailable')
    monkeypatch.setattr(client, 'cfb_market_json', boom)
    result = cfb.generate_cfb_candidate_model(client, DAY)
    assert result['picks'] == [] and result['errors']
    assert 'unavailable' in result['note']


def test_grading_preserves_negative_yards_and_requires_espn_identity():
    from pickgrader_server import _extract_football_player_stat, grade_player_prop_pick
    summary = {'boxscore': {'players': [{'statistics': [{'name': 'rushing', 'labels': ['CAR', 'YDS'], 'athletes': [
        {'athlete': {'id': 'espn-player', 'displayName': 'Marcel Reed'}, 'stats': ['3', '-8']},
        {'athlete': {'id': 'wrong-player', 'displayName': 'Marcel Reed'}, 'stats': ['4', '100']},
    ]}]}]}}
    assert _extract_football_player_stat(summary, 'Marcel Reed', 'rushing_yards', ('espn-player',)) == -8
    assert _extract_football_player_stat(summary, 'Marcel Reed', 'rushing_yards', ('missing',)) is None
    pick = {'sport': 'CFB', 'scope': 'player', 'player_id': 'espn-player', 'player_name': 'Marcel Reed',
            'stat_key': 'rushing_yards', 'selection': 'Under', 'line': 0.5, 'pick': 'Marcel Reed Under 0.5 Rushing Yards'}
    assert grade_player_prop_pick(pick, {}, summary) == 'win'


def test_training_uses_only_immutable_pregame_quotes_and_final_outcomes(tmp_path):
    import json
    from scripts.build_player_prop_market_history import _cfb_snapshot_rows
    folder = tmp_path / DAY
    folder.mkdir()
    pick = {'date': DAY, 'baseline_only': True, 'game_id': 'game', 'player_id': 'player',
            'stat_key': 'rushing_yards', 'line': 30.5, 'market_over_odds': -110, 'market_under_odds': -110,
            'start_time': DAY + 'T16:00:00Z', 'market_retrieved_at': DAY + 'T14:00:00Z'}
    def write(stamp, row):
        (folder / 'snapshot.json').write_text(json.dumps({'generatedAt': stamp, 'models': {'cfb_player_props': {'picks': [row]}}}))
    class Summary:
        completed = True
        def football_espn_summary(self, *args):
            return {'header': {'competitions': [{'status': {'type': {'completed': self.completed}}}]},
                    'boxscore': {'players': [{'statistics': [{'name': 'rushing', 'labels': ['CAR', 'YDS'],
                        'athletes': [{'athlete': {'id': 'player'}, 'stats': ['5', '40']}]}]}]}}
    client = Summary()
    write(DAY + 'T14:01:00Z', pick)
    rows = _cfb_snapshot_rows(client, DAY, DAY, tmp_path)
    assert len(rows) == 1 and rows[0]['actual'] == 40 and rows[0]['over_outcome'] == 1
    client.completed = False
    assert _cfb_snapshot_rows(client, DAY, DAY, tmp_path) == []
    client.completed = True
    write(DAY + 'T17:01:00Z', pick)
    assert _cfb_snapshot_rows(client, DAY, DAY, tmp_path) == []
    write(DAY + 'T14:01:00Z', {**pick, 'market_retrieved_at': DAY + 'T16:01:00Z'})
    assert _cfb_snapshot_rows(client, DAY, DAY, tmp_path) == []


def test_deployment_exemption_never_allows_an_uncalibrated_stake():
    from scripts.site_upcheck import _documented_cfb_baseline
    row = {'sport': 'CFB', 'baseline_only': True, 'probability_calibrated': False, 'ml_model_active': False,
           'decision': 'PASS', 'units': 0, 'full_kelly': 0, 'quarter_kelly': 0, 'model_version': cfb.VERSION}
    assert _documented_cfb_baseline(row)
    for update in ({'decision': 'BET'}, {'units': 1}, {'full_kelly': .1}, {'sport': 'MLB'}, {'probability_calibrated': True}):
        assert not _documented_cfb_baseline({**row, **update})
