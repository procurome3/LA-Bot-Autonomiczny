import unittest

from tools.update_champion_database_api import (
    HH_IDENTITY_FIELDS,
    _identity_only,
    parse_api_skill_rows,
    parse_gacha_skill_page,
)


class ChampionDatabaseApiTests(unittest.TestCase):
    def test_identity_allowlist_drops_rankings(self):
        row = {
            'id': 123, 'heroId': 456, 'champion': 'Demo', 'rarity': 'Legendary',
            'faction_index': 'high-elves', 'affinity_index': 'Void', 'role': 'Supp',
            'url': 'https://example.invalid/demo/',
            'overall_user': 5, 'arena_rating': 5, 'win_rate': 99, 'pick_rate': 88,
            'book_value': 10,
        }
        clean = _identity_only(row)
        self.assertEqual(set(clean), set(row).intersection(HH_IDENTITY_FIELDS))
        for banned in ('overall_user', 'arena_rating', 'win_rate', 'pick_rate', 'book_value'):
            self.assertNotIn(banned, clean)

    def test_api_rows_assign_arbiter_style_skills_and_books(self):
        rows = [
            {'type':'Active', 'name':'Gaze of Justice', 'cooldown':'',
             'description':'Attacks 1 enemy 2 times. Each hit has a 30% chance of placing a [Weaken] debuff for 2 turns.'},
            {'type':'Active', 'name':'Enforced Humility', 'cooldown':4,
             'description':'Attacks all enemies. Has a 75% chance of decreasing the duration of all enemy buffs by 1 turn.'},
            {'type':'Active', 'name':'Mentor of Heroes', 'cooldown':4,
             'description':'Fills the Turn Meters of all allies by 30%. Places a 50% [Increase ATK] buff on all allies for 2 turns. Level 2: Cooldown -1'},
            {'type':'Active', 'name':"Destiny's Call", 'cooldown':7,
             'description':'Revives all dead allies with 35% HP, then fills the Turn Meters of all allies by 20%. Grants an Extra Turn. Level 2: Cooldown -1 Level 3: Cooldown -1'},
            {'type':'Aura', 'name':'Aura', 'cooldown':'', 'description':'Increases Ally SPD in the Arena by 30%.'},
        ]
        skills = parse_api_skill_rows(rows)
        self.assertIn('A1', skills)
        self.assertIn('A4', skills)
        self.assertIn('AURA', skills)
        self.assertEqual(skills['A3']['cooldown_booked'], 3)
        self.assertEqual(skills['A4']['cooldown_booked'], 5)
        self.assertEqual(skills['A4']['attack_type'], 'ally_dead')
        self.assertIn('revive', skills['A4']['tags'])
        self.assertNotIn('transform', skills['A4']['tags'])

    def test_api_rows_assign_mythical_transform_as_a4(self):
        rows = [
            {'type':'Active','name':'One','description':'Attacks 1 enemy.'},
            {'type':'Active','name':'Two','cooldown':3,'description':'Attacks all enemies.'},
            {'type':'Active','name':'Three','cooldown':4,'description':'Attacks 1 enemy.'},
            {'type':'Active','name':'Metamorph','cooldown':4,'description':'Transforms this Champion into their Alternate Form. Then grants an Extra Turn.'},
            {'type':'Passive','name':'Dramatis Miserae [P]','description':'Whenever this Champion loses HP, places a [Shield] buff on them for 2 turns.'},
        ]
        skills = parse_api_skill_rows(rows)
        self.assertEqual(skills['A4']['attack_type'], 'transform')
        self.assertIn('transform', skills['A4']['tags'])
        self.assertIn('P', skills)

    def test_gacha_parser_keeps_mythical_forms_separate(self):
        html = '''
        <html><body>
        <h2>Skills</h2>
        <h3>Pride's Bite</h3><p>Ability 1 (Form 1)</p><p>Attacks 1 enemy. Places a 60% Increase DEF buff on all allies for 1 turn.</p>
        <h3>Metamorph</h3><p>Ability 4 (Form 1) · Cooldown 4 turns</p><p>Transforms this Champion into their Alternate Form. Then grants an Extra Turn.</p>
        <h3>Knights Of The Wild</h3><p>Passive (Form 1)</p><p>Increases this Champion's RES.</p>
        <h3>Gildthron Assault</h3><p>Ability 1 (Form 2)</p><p>Attacks 1 enemy.</p>
        <h3>Palisade Breaker</h3><p>Ability 2 (Form 2) · Cooldown 4 turns</p><p>Attacks all enemies. Places a 50% Decrease RES debuff for 2 turns.</p>
        <h3>Metamorph</h3><p>Ability 4 (Form 2) · Cooldown 4 turns</p><p>Transforms this Champion into their Base Form. Then grants an Extra Turn.</p>
        <h3>Lionheart</h3><p>Ability 5 (Form 2)</p><p>Increases this Champion's ACC.</p>
        <h2>Art</h2>
        </body></html>
        '''
        forms = parse_gacha_skill_page(html)
        self.assertIn('base', forms)
        self.assertIn('alternate', forms)
        self.assertIn('A4', forms['base']['skills'])
        self.assertIn('A4', forms['alternate']['skills'])
        self.assertEqual(forms['base']['skills']['A4']['attack_type'], 'transform')
        self.assertEqual(forms['alternate']['skills']['A4']['attack_type'], 'transform')
        self.assertIn('P', forms['alternate']['skills'])


if __name__ == '__main__':
    unittest.main()
