import tempfile
import unittest
from pathlib import Path

from livearena_autonomy import AutonomyController
from combat_tree import CombatDecisionTree


class AutonomyTests(unittest.TestCase):
    def controller(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        base = Path(td.name)
        # Knowledge remains the real branch knowledge; telemetry/learning are isolated.
        return AutonomyController(
            enabled=True,
            knowledge_path="./livearena_autonomy_knowledge.json",
            telemetry_path=str(base / "telemetry.jsonl"),
            learning_path=str(base / "learning.json"),
        )

    def test_arbiter_revive_outweighs_boost_when_dead_ally(self):
        c = self.controller()
        skills = {
            "A3": {"skill_id":"A3","attack_type":"self","availability":"available","eligibility":"eligible","score":.8,"combined_score":.8},
            "A4": {"skill_id":"A4","attack_type":"ally_dead","availability":"available","eligibility":"eligible","score":.8,"combined_score":.8},
            "A2": {"skill_id":"A2","attack_type":"aoe","availability":"available","eligibility":"eligible","score":.8,"combined_score":.8},
            "A1": {"skill_id":"A1","attack_type":"single","availability":"available","eligibility":"eligible","score":.8,"combined_score":.8},
        }
        priority, scores = c.rank_skill_ids(
            "arbiter", skills, ["A3","A4","A2","A1"],
            enemy_states=[{"alive": True, "hp": .8}],
            ally_tracker={1:{"seen_alive":True,"dead":True}, 2:{"seen_alive":True,"dead":False}},
            ally_ratios={1:0.0, 2:.08},
            min_score=.34,
        )
        self.assertEqual(priority[0], "A4")
        self.assertGreater(scores["A4"].score, scores["A3"].score)

    def test_unknown_higher_skill_remains_barrier(self):
        c = self.controller()
        skills = {
            "A3": {"skill_id":"A3","attack_type":"aoe","availability":"unknown","eligibility":"eligible","score":.8},
            "A2": {"skill_id":"A2","attack_type":"single","availability":"available","eligibility":"eligible","score":.9,"combined_score":.9},
            "A1": {"skill_id":"A1","attack_type":"single","availability":"available","eligibility":"eligible","score":.9,"combined_score":.9},
        }
        priority, _ = c.rank_skill_ids("fabian", skills, ["A3","A2","A1"], min_score=.34)
        self.assertEqual(priority[0], "A3")
        tree = CombatDecisionTree()
        result = tree.decide(
            family="fabian", skills=skills, declared_skill_ids=skills.keys(),
            dead_ally_available=False, min_score=.34, priority_override=priority,
        )
        self.assertEqual(result.state, "wait")
        self.assertIsNone(result.skill)

    def test_ban_ranks_known_high_threat_enemy(self):
        c = self.controller()
        ranked = c.rank_ban_candidates(
            ["marius", "krixia", "shu_zhen"],
            ["marius", "krixia", "shu_zhen"],
            ["arbiter", "fabian"],
        )
        self.assertIn(ranked[0], {"krixia", "marius", "shu_zhen"})
        self.assertNotEqual(ranked[-1], ranked[0])

    def test_target_scoring_prefers_finish_without_breaking_legality(self):
        c = self.controller()
        pool = [
            {"slot":1,"alive":True,"hp":.82,"affinity":"neutral","stoneskin":False,"damage_immune":False,"counterattack":False},
            {"slot":2,"alive":True,"hp":.18,"affinity":"neutral","stoneskin":False,"damage_immune":False,"counterattack":False},
        ]
        target, reason, trace = c.choose_target(
            pool, attack_type="single", lowest_hp=False,
            affinity_aware=True, policy={},
        )
        self.assertEqual(target["slot"], 2)
        self.assertTrue(reason.startswith("autonomy-target="))
        self.assertEqual(len(trace), 2)


    def test_timeout_fallback_uses_best_verified_dynamic_action(self):
        skills = {
            "A3": {"skill_id":"A3","attack_type":"aoe","availability":"unknown","eligibility":"eligible","score":.8},
            "A2": {"skill_id":"A2","attack_type":"single","availability":"available","eligibility":"eligible","score":.9},
            "A1": {"skill_id":"A1","attack_type":"single","availability":"available","eligibility":"eligible","score":.9},
        }
        tree = CombatDecisionTree()
        result = tree.decide(
            family="fabian", skills=skills, declared_skill_ids=skills.keys(),
            dead_ally_available=False, min_score=.34, prefer_fallback=True,
            priority_override=("A3","A2","A1"),
        )
        self.assertEqual(result.state, "selected")
        self.assertEqual(result.skill["skill_id"], "A2")
        self.assertTrue(result.skill.get("fallback"))

    def test_skill_scoring_changes_with_battle_state(self):
        c = self.controller()
        skills = {
            "A3": {"skill_id":"A3","attack_type":"aoe","availability":"available","eligibility":"eligible","score":.8,"combined_score":.8},
            "A2": {"skill_id":"A2","attack_type":"single","availability":"available","eligibility":"eligible","score":.8,"combined_score":.8},
            "A1": {"skill_id":"A1","attack_type":"single","availability":"available","eligibility":"eligible","score":.8,"combined_score":.8},
        }
        healthy = [
            {"alive":True,"hp":.9,"stoneskin":False,"damage_immune":False,"counterattack":False}
            for _ in range(4)
        ]
        late = [{"alive":True,"hp":.10,"stoneskin":False,"damage_immune":False,"counterattack":False}]
        p1, _ = c.rank_skill_ids("fabian", skills, ["A3","A2","A1"], enemy_states=healthy, min_score=.34, reorder_margin=.5)
        p2, _ = c.rank_skill_ids("fabian", skills, ["A3","A2","A1"], enemy_states=late, min_score=.34, reorder_margin=.5)
        self.assertEqual(p1[0], "A3")
        self.assertEqual(p2[0], "A1")

    def test_learning_changes_future_prior_slowly(self):
        c = self.controller()
        before = c.learning.champion_bonus("fabian")
        for _ in range(12):
            c.learning.record_outcome(["fabian"], ["marius"], True, weight=1.0)
        after = c.learning.champion_bonus("fabian")
        self.assertGreater(after, before)
        self.assertLess(after, 10.1)


if __name__ == "__main__":
    unittest.main()
