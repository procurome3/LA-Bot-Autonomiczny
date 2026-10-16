import json
import tempfile
import unittest
from pathlib import Path

from champion_database import ChampionDatabase, canonical_key
from tools.update_champion_database import assign_skill_ids, parse_skill


class ChampionDatabaseTests(unittest.TestCase):
    def test_roster_contains_unique_legendary_mythical_identities(self):
        raw = json.loads(Path('data/champion_roster_legendary_mythical_2026.json').read_text(encoding='utf-8'))
        rows = raw['champions']
        self.assertGreaterEqual(len(rows), 400)
        keys = [canonical_key(x['key']) for x in rows]
        self.assertEqual(len(keys), len(set(keys)))
        counts = raw.get('counts', {})
        self.assertEqual(counts.get('mythical'), sum(r['rarity']=='mythical' for r in rows))
        self.assertEqual(counts.get('legendary'), sum(r['rarity']=='legendary' for r in rows))

    def test_database_policy_explicitly_excludes_rankings(self):
        raw = json.loads(Path('data/champion_database.json').read_text(encoding='utf-8'))
        policy = raw['meta']['policy']
        self.assertTrue(policy['facts_only'])
        self.assertFalse(policy['tier_ranking_imported'])
        self.assertFalse(policy['ratings_imported'])
        self.assertFalse(policy['live_arena_stats_imported'])
        self.assertFalse(policy['win_pick_ban_rates_imported'])

    def test_arbiter_a4_is_revive_not_transform(self):
        db = ChampionDatabase('data/champion_database.json')
        a4 = db.skill('arbiter', 'A4')
        self.assertIsNotNone(a4)
        self.assertEqual(a4.attack_type, 'ally_dead')
        self.assertEqual(a4.cooldown_base, 7)
        self.assertEqual(a4.cooldown_booked, 5)
        profile = db.derive_skill_profile('arbiter', 'A4', 'ally_dead')
        self.assertIn('revive', profile['tags'])
        self.assertNotIn('transform', profile['tags'])

    def test_mythical_form_lookup_keeps_forms_separate(self):
        payload = {
            'meta': {},
            'champions': {
                'demo': {
                    'name': 'Demo', 'key': 'demo', 'rarity': 'mythical',
                    'forms': {
                        'base': {'skills': {'A3': {'name':'Base A3','attack_type':'self'}}},
                        'alternate': {'skills': {'A3': {'name':'Alt A3','attack_type':'single'}}},
                    }
                }
            }
        }
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'db.json'
            path.write_text(json.dumps(payload), encoding='utf-8')
            db = ChampionDatabase(str(path))
            self.assertEqual(db.skill('demo_f1','A3').name, 'Base A3')
            self.assertEqual(db.skill('demo_f2','A3').name, 'Alt A3')

    def test_parser_extracts_cooldown_target_duration_and_tm(self):
        skill = parse_skill(
            'Example',
            '4 Turns Attacks all enemies. Has a 75% chance of placing a [Stun] debuff for 1 turn. '
            'Fills the Turn Meter of all allies by 20%. Level 5: Cooldown -1',
            'A3', 'base'
        )
        self.assertEqual(skill['cooldown_base'], 4)
        self.assertEqual(skill['cooldown_booked'], 3)
        self.assertEqual(skill['attack_type'], 'aoe')
        self.assertIn('control', skill['tags'])
        self.assertIn('turn_meter', skill['tags'])
        stun = next(x for x in skill['effects'] if x.get('name') == 'stun')
        self.assertEqual(stun['duration_turns'], 1)
        self.assertEqual(stun['chance_percent'], 75.0)

    def test_skill_block_assignment_is_sequential_and_form_aware(self):
        blocks = [
            ('base','First','Attacks 1 enemy.'),
            ('base','Second','3 Turns Attacks all enemies.'),
            ('alternate','Alt First','Attacks all enemies.'),
        ]
        forms = assign_skill_ids(blocks)
        self.assertIn('A1', forms['base']['skills'])
        self.assertIn('A2', forms['base']['skills'])
        self.assertIn('A1', forms['alternate']['skills'])


if __name__ == '__main__':
    unittest.main()
