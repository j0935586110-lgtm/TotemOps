# SPDX-License-Identifier: Apache-2.0
"""Prove that passing server-side checks never authorizes a claim that users can play."""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CASE = ROOT / "evidence" / "waystones-playability-20261015.json"
PLAY_GATES = (
    "compatible_neoforge_client_join_test_server",
    "waystones_ui_and_teleport",
    "human_player_end_to_end",
)


def complete_playable(gates: dict) -> bool:
    """No guesswork: only all three independently proven PASS results count."""
    return all(gates.get(key) == "PASS" for key in PLAY_GATES)


class PlayableAcceptanceContractTests(unittest.TestCase):
    def test_receipt_is_bound_to_real_version_and_replay_evidence(self):
        d = json.loads(CASE.read_text(encoding="utf-8"))
        self.assertEqual(d["versions"]["minecraft"], "1.21.1")
        self.assertEqual(d["versions"]["neoforge"], "21.1.259")
        self.assertEqual(d["evidence"]["server_world_block_id"], "waystones:waystone")
        self.assertTrue(d["evidence"]["block_entity_persisted_across_restart"])
        self.assertTrue(d["environment"]["docker_internal_network"])
        self.assertEqual(d["environment"]["published_server_ports"], 0)
        self.assertFalse(d["environment"]["production_world_modified"])

    def test_no_gameplay_overclaim_despite_successful_server_tests(self):
        d = json.loads(CASE.read_text(encoding="utf-8"))
        gates = d["gates"]
        self.assertEqual(gates["server_boot"], "PASS")
        self.assertEqual(gates["world_persistence_restart"], "PASS")
        self.assertFalse(complete_playable(gates))
        self.assertEqual(d["fully_playable_verified"], complete_playable(gates))

    def test_incomplete_evidence_must_fail_closed(self):
        examples = [
            {},
            {"compatible_neoforge_client_join_test_server": "PASS"},
            {k: "PASS" for k in PLAY_GATES[:-1]},
            {**{k: "PASS" for k in PLAY_GATES}, "human_player_end_to_end": "NOT_VERIFIED"},
        ]
        for row in examples:
            with self.subTest(row=row):
                self.assertFalse(complete_playable(row))

    def test_zero_discovered_game_tests_never_count_as_gameplay_pass(self):
        d = json.loads(CASE.read_text(encoding="utf-8"))
        self.assertEqual(d["client_ci_verified_run"], 38627418271)
        self.assertEqual(d["client_ci_game_tests_discovered"], 0)
        self.assertEqual(d["gates"]["waystones_gametest"], "BLOCKED_ZERO_TESTS_DISCOVERED")
        self.assertEqual(d["gates"]["compatible_neoforge_client_singleplayer"],
                         "PASS_CLIENT_WORLD_SMOKE_ONLY")
        self.assertFalse(d["fully_playable_verified"])

    def test_only_full_independent_proof_allows_playable_claim(self):
        self.assertTrue(complete_playable({k: "PASS" for k in PLAY_GATES}))


if __name__ == "__main__":
    unittest.main()
