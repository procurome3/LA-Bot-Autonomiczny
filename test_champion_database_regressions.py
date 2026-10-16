import json
import tempfile
import unittest
from pathlib import Path

from champion_database import ChampionDatabase, canonical_key
from tools.champion_skill_facts import parse_skill
from tools.update_champion_database_api import parse_api_forms, parse_api_skill_rows, canonicalize_existing_database
from tools.validate_champion_database import analyze_database


class DatabaseRegressionTests(unittest.TestCase):
    def test_both_api_form_arrays_survive(self):
        forms = parse_api_forms([[{'name': 'First', 'type': 'Basic', 'description': 'Attacks 1 enemy.'}],
                                 [{'name': 'Second', 'type': 'Basic', 'description': 'Attacks all enemies.'}]])
        self.assertEqual(forms['alternate']['skills']['A1']['name'], 'Second')

    def test_duplicate_api_rows_do_not_shift_transform(self):
        rows = [{'name': 'First', 'description': 'Attacks 1 enemy.'},
                {'name': 'Nest Of Vipers', 'description': 'Attacks all enemies.'},
                {'name': 'Nest Of Vipers', 'description': 'Attacks all enemies.'},
                {'name': "The Rift's Gaze", 'description': 'Fills the Turn Meters of all allies by 20%.'},
                {'name': 'Metamorph', 'description': 'Transforms this Champion into their Alternate Form.'}]
        skills = parse_api_skill_rows(rows)
        self.assertEqual(skills['A3']['name'], "The Rift's Gaze")
        self.assertEqual(skills['A4']['attack_type'], 'transform')
        self.assertNotIn('A5', skills)

    def test_mislabeled_trailing_mythical_passive_is_not_clickable(self):
        rows = [{'name': str(i), 'type': 'Active', 'description': 'Attacks 1 enemy.'} for i in range(3)]
        rows += [{'name': 'Metamorph', 'type': 'Active', 'description': 'Transforms this Champion into their Alternate Form.'},
                 {'name': "Blackteeth's Buffet", 'type': 'Active', 'description': 'Whenever an enemy receives a buff, places a [Poison] debuff for 2 turns.'}]
        skills = parse_api_skill_rows(rows)
        self.assertIn('P', skills)
        self.assertFalse(skills['P']['clickable'])
        self.assertNotIn('A5', skills)

    def test_book_dictionary_updates_cooldown_and_chance(self):
        skills = parse_api_skill_rows([{'name': 'Hit', 'type': 'Basic', 'cooldown': 0,
            'description': 'Attacks 1 enemy. Has a 30% chance of placing a [Weaken] debuff for 2 turns.',
            'books': {'1': {'type': 'Buff/Debuff Chance', 'amount': '20'}}},
            {'name': 'Support', 'type': 'Active', 'cooldown': 4,
             'description': 'Places a [Shield] buff on all allies for 2 turns.',
             'books': {'1': {'type': 'Cooldown', 'amount': '1'}}}])
        self.assertEqual(skills['A1']['cooldown_booked'], 0)
        self.assertEqual(skills['A2']['cooldown_booked'], 3)
        self.assertEqual(skills['A1']['effects'][0]['chance_booked_percent'], 50)

    def test_predator_condition_is_not_a_buff_grant(self):
        skill = parse_skill('Smart Disc', "Attacks all enemies 2 times. This attack ignores 15% of each target's DEF if this Champion is under a [Veil] or [Perfect Veil] buff.", 'A2', 'base')
        self.assertFalse(any(e['kind'] == 'buff' for e in skill['effects']))
        self.assertNotIn('protection', skill['tags'])
        ignore = next(e for e in skill['effects'] if e['name'] == 'ignore def')
        self.assertEqual(ignore['value_percent'], 15)
        self.assertEqual(ignore['conditions'][0]['names'], ['veil', 'perfect veil'])
        self.assertEqual(skill['selection_target'], 'enemy')

    def test_tekteon_self_buffs_and_ally_shield_are_separate(self):
        skill = parse_skill('Flaming Bulwark', '6 Turns Places a [Taunt] buff and a [Poison Cloud] buff on this Champion for 3 turns. Places a [Shield] buff on all allies for 2 turns. Grants an Extra Turn.', 'A3', 'base')
        effects = {x['name']: x for x in skill['effects']}
        for name in ('taunt', 'poison cloud'):
            self.assertEqual(effects[name]['kind'], 'buff')
            self.assertEqual(effects[name]['target'], 'self')
            self.assertEqual(effects[name]['duration_turns'], 3)
        self.assertEqual(effects['shield']['target'], 'all_allies')
        self.assertEqual(skill['selection_target'], 'self')

    def test_section_labels_are_not_statuses(self):
        skill = parse_skill('Hit', 'Attacks 1 enemy. [Passive Effect] Counterattacks with this skill.', 'A1', 'base')
        self.assertNotIn('passive effect', [x['name'] for x in skill['effects']])

    def test_heal_keeps_hp_condition_and_basis(self):
        skill = parse_skill('Support', 'Heals all allies by 25% of their MAX HP if they have less than 50% HP.', 'A3', 'base')
        effect = skill['effects'][0]
        self.assertEqual(effect['value_basis'], 'target_max_hp')
        self.assertEqual(effect['conditions'][0]['value'], 50)

    def test_missing_form_never_falls_back_to_base(self):
        payload = {'champions': {'demo': {'name': 'Demo', 'key': 'demo', 'forms': {'base': {'skills': {'A1': {'name': 'Base'}}}}}}}
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'db.json'
            path.write_text(json.dumps(payload))
            self.assertIsNone(ChampionDatabase(str(path)).skill('demo_f2', 'A1'))

    def test_runtime_aliases_resolve_same_identity(self):
        for short, full in [('embrys', 'Embrys the Anomaly'), ('mikage', 'Lady Mikage'), ('ashnar_dragonsoul', "Ash'nar Dragonsoul"), ('khamir_scald_eye', 'Khamir the Scaled Eye')]:
            self.assertEqual(canonical_key(short), canonical_key(full))

    def test_validator_rejects_false_complete_skill_identity(self):
        db = {'champions': {'demo': {'rarity': 'legendary', 'forms': {'base': {'expected_skill_ids': ['1','2'], 'skills': {'A1': {'name':'Hit','source_skill_id':'1'}, 'A5': {'name':'Oops','source_skill_id':'3'}}}}}}}
        audit = analyze_database(db)
        self.assertFalse(audit['structurally_valid'])
        self.assertIn('source_skill_id_set_mismatch', [e['code'] for e in audit['errors']])

    def test_partial_alias_does_not_erase_complete_mythical(self):
        complete = {'name': 'Ashnar', 'key': 'ashnar_dragonsoul', 'status': 'detailed',
                    'forms': {'base': {'skills': {'A1': {'name': 'Base'}}}, 'alternate': {'skills': {'A1': {'name': 'Alt'}}}}}
        partial = {'name': 'Ashnar', 'key': 'ash_nar_dragonsoul', 'status': 'partial',
                   'forms': {'base': {'skills': {'A1': {'name': 'Base'}}}}}
        db = canonicalize_existing_database({'champions': {'ashnar_dragonsoul': complete, 'ash_nar_dragonsoul': partial}})
        self.assertEqual(len(db['champions']), 1)
        self.assertIn('alternate', db['champions']['ashnar_dragonsoul']['forms'])

    def test_source_stub_is_explicitly_flagged(self):
        skill = parse_skill('Thornsphere [P]', '', 'P', 'base')
        self.assertIn('source_description_empty', skill['review_flags'])
        self.assertFalse(skill['clickable'])

    def test_actual_speed_aura_reaches_leader_profile(self):
        db = ChampionDatabase('data/champion_database.json')
        profile = db.derive_champion_profile('arbiter')
        self.assertEqual(profile['speed_aura_percent'], 30)
        self.assertGreater(profile['leader'], 0)

    def test_mina_live_kit_has_passive_base_transformation(self):
        db = ChampionDatabase('data/champion_database.json')
        self.assertEqual(db.skill('blood_marchioness_mina_f1', 'A1').name, 'Hatespine')
        self.assertIsNone(db.skill('blood_marchioness_mina_f1', 'A4'))
        self.assertEqual(db.skill('blood_marchioness_mina_f1', 'P').name, 'Metamorph [P]')
        self.assertFalse(db.skill('blood_marchioness_mina_f1', 'P').clickable)

    def test_all_live_form_skill_ids_match_normalized_database(self):
        raw = json.loads(Path('data/champion_database.json').read_text())
        audit = analyze_database(raw)
        self.assertEqual(audit['errors'], [])
        self.assertEqual(audit['coverage_gaps'], [])
        self.assertTrue(all(c['forms'].get('alternate') for c in raw['champions'].values() if c['rarity']=='mythical'))


if __name__ == '__main__':
    unittest.main()
