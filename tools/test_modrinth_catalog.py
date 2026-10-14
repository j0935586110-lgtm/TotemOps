# SPDX-License-Identifier: Apache-2.0
"""Deterministic tests of tiny on-demand Modrinth catalog plugin (no network)."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
import urllib.error

path = Path(__file__).resolve().parent.parent / "plugins/modrinth-catalog/plugin.py"
spec = importlib.util.spec_from_file_location("totem_modrinth_catalog", path)
catalog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(catalog)


class ModrinthCatalogTests(unittest.TestCase):
    def test_finds_version_matching_target_and_lists_deps(self):
        hits = {"hits": [{"project_id": "9eGKb6K1", "title": "Simple Voice Chat",
                           "environment": "client_and_server"}]}
        versions = [
            {"id": "wrong", "version_number": "fabric",
             "game_versions": ["1.21.1"], "loaders": ["fabric"],
             "date_published": "2026-10-01T00:00:00Z"},
            {"id": "correct", "version_number": "neoforge-2.6.0",
             "game_versions": ["1.21.1"], "loaders": ["neoforge"],
             "date_published": "2026-09-01T00:00:00Z",
             "dependencies": [{"project_id": "libA0000", "dependency_type": "required"}]}
        ]
        with patch.object(catalog, "_fetch", side_effect=[hits, versions]) as fetch:
            out = catalog.search({"query": "voice chat", "game_version": "1.21.1",
                                  "loader": "neoforge", "limit": 1})
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(out["status"], "CANDIDATES_ONLY")
        self.assertEqual(out["candidates"][0]["version_id"], "correct")
        self.assertEqual(out["candidates"][0]["dependencies"][0]["type"], "required")
        self.assertFalse(out["verified_compatible_together"])
        self.assertFalse(out["downloaded"])

    def test_invalid_loader_blocked_no_network(self):
        with patch.object(catalog, "_fetch") as f:
            out = catalog.search({"query": "voice chat", "game_version": "1.21.1",
                                  "loader": "madeup"})
        self.assertEqual(out["status"], "BLOCK")
        f.assert_not_called()

    def test_invalid_version_blocked_no_network(self):
        with patch.object(catalog, "_fetch") as f:
            out = catalog.search({"query": "economy", "game_version": "1.21.1/../",
                                  "loader": "forge"})
        self.assertEqual(out["status"], "BLOCK")
        f.assert_not_called()

    def test_no_compatible_release_is_not_recommended(self):
        with patch.object(catalog, "_fetch", side_effect=[
            {"hits": [{"project_id": "9eGKb6K1", "title": "Voice Chat"}]},
            [{"id": "incompatible", "game_versions": ["1.20.1"], "loaders": ["neoforge"]}]]):
            out = catalog.search({"query": "voice chat", "game_version": "1.21.1",
                                  "loader": "neoforge"})
        self.assertEqual(out["candidates"], [])

    def test_api_failure_does_not_fabricate_results(self):
        with patch.object(catalog, "_fetch", side_effect=urllib.error.URLError("offline")):
            out = catalog.search({"query": "voice chat", "game_version": "1.21.1",
                                  "loader": "neoforge"})
        self.assertEqual(out["status"], "BLOCK")
        self.assertTrue(out["no_results_fabricated"])

    def test_version_lookup_failure_means_partial(self):
        with patch.object(catalog, "_fetch", side_effect=[
            {"hits": [{"project_id": "9eGKb6K1", "title": "Voice Chat"}]},
            urllib.error.URLError("offline"),
        ]):
            out = catalog.search({"query": "voice chat", "game_version": "1.21.1",
                                  "loader": "neoforge"})
        self.assertEqual(out["status"], "PARTIAL_CANDIDATES")
        self.assertEqual(out["candidates"], [])
        self.assertTrue(out["warnings"])

    def test_limit_bounded(self):
        with patch.object(catalog, "_fetch") as f:
            out = catalog.search({"query": "voice chat", "game_version": "1.21.1",
                                  "loader": "neoforge", "limit": 100})
        self.assertEqual(out["status"], "BLOCK")
        f.assert_not_called()


if __name__ == "__main__":
    unittest.main()
