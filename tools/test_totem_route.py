# SPDX-License-Identifier: Apache-2.0
"""Cloud routing stays off without opt-in, public payload scope and spend cap."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from totem_route import load_providers, route, RouteRejected

LOCAL_OK = {"stage_allowed": True, "run_allowed": True, "stage_blockers": [], "run_blockers": []}
LOCAL_SHORT = {"stage_allowed": False, "run_allowed": False,
               "stage_blockers": ["not_enough_available_memory_for_stage"],
               "run_blockers": ["not_enough_available_memory_for_java"]}
ELIGIBLE = [{"id": "modal", "enabled": True, "tasks": ["stage", "server"],
             "memory_mb": 8192, "disk_mb": 16384}]
DISABLED = [{"id": "modal", "enabled": False, "tasks": ["stage", "server"],
             "memory_mb": 8192, "disk_mb": 16384}]


class CloudRouteTests(unittest.TestCase):
    def run_route(self, state, providers=None, **kwargs):
        with patch("totem_route.probe_environment", return_value=state) as probe:
            result = route("server", None, ELIGIBLE if providers is None else providers, **kwargs)
        probe.assert_called_once()
        return result

    def test_local_first_even_when_cloud_opted_in(self):
        got = self.run_route(LOCAL_OK, allow_cloud=True,
                             payload_scope="public-mods", max_cloud_usd=1)
        self.assertEqual(got["status"], "LOCAL")
        self.assertEqual(got["cloud_candidates"], [])

    def test_shortage_without_opt_in_blocks(self):
        got = self.run_route(LOCAL_SHORT)
        self.assertEqual(got["status"], "BLOCK")
        self.assertEqual(got["reason"], "cloud_not_opted_in")

    def test_private_world_never_cloud(self):
        got = self.run_route(LOCAL_SHORT, allow_cloud=True,
                             payload_scope="private-world", max_cloud_usd=1)
        self.assertEqual(got["status"], "BLOCK")
        self.assertEqual(got["reason"], "payload_not_approved_for_cloud")

    def test_unknown_payload_never_cloud(self):
        got = self.run_route(LOCAL_SHORT, allow_cloud=True, max_cloud_usd=1)
        self.assertEqual(got["status"], "BLOCK")

    def test_cloud_without_budget_blocks(self):
        got = self.run_route(LOCAL_SHORT, allow_cloud=True,
                             payload_scope="public-mods")
        self.assertEqual(got["reason"], "cloud_spend_cap_not_configured")

    def test_disabled_provider_never_selected(self):
        got = self.run_route(LOCAL_SHORT, DISABLED, allow_cloud=True,
                             payload_scope="public-mods", max_cloud_usd=1)
        self.assertEqual(got["status"], "BLOCK")
        self.assertEqual(got["reason"], "no_eligible_enabled_provider")

    def test_enabled_is_candidate_not_execution(self):
        got = self.run_route(LOCAL_SHORT, allow_cloud=True,
                             payload_scope="redacted-logs", max_cloud_usd=1)
        self.assertEqual(got["status"], "CLOUD_PREFLIGHT_REQUIRED")
        self.assertEqual(got["cloud_candidates"][0]["status"], "UNVERIFIED")
        self.assertFalse(got["cloud_candidates"][0]["provider_billing_cap_enforced"])
        self.assertFalse(got["cloud_execution_performed"])
        self.assertFalse(got["payload_uploaded"])
        self.assertFalse(got["credentials_sent"])

    def test_cloud_has_minimum_resources(self):
        p = [{"id": "daytona", "enabled": True, "tasks": ["server"],
              "memory_mb": 1024, "disk_mb": 16384}]
        got = self.run_route(LOCAL_SHORT, p, allow_cloud=True,
                             payload_scope="public-mods", max_cloud_usd=1)
        self.assertEqual(got["status"], "BLOCK")

    def test_missing_manifest_default_empty(self):
        self.assertEqual(load_providers(None), [])

    def test_registry_file_and_duplicate_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "providers.json"
            p.write_text(json.dumps({"schema": 1, "providers": ELIGIBLE}))
            self.assertEqual(load_providers(p)[0]["id"], "modal")
            p.write_text(json.dumps({"schema": 1, "providers": ELIGIBLE * 2}))
            with self.assertRaisesRegex(RouteRejected, "duplicate"):
                load_providers(p)

    def test_false_free_claim_cannot_enable_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "providers.json"
            p.write_text(json.dumps({"schema": 1, "providers": DISABLED}))
            manifest = load_providers(p)
        got = self.run_route(LOCAL_SHORT, manifest, allow_cloud=True,
                             payload_scope="public-mods", max_cloud_usd=1)
        self.assertEqual(got["status"], "BLOCK")


if __name__ == "__main__":
    unittest.main()
