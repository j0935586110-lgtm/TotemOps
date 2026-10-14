# SPDX-License-Identifier: Apache-2.0
"""Signed release gate RED/GREEN tests: no live network or Minecraft changes."""
from __future__ import annotations

import base64
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from totem_release_gate import ReleaseBlocked, decide, evaluate, main


def profile(**kwargs):
    d = {
        "schema": 1, "profile": "demo-server", "sequence": 1,
        "minecraft": "1.20.1", "loader": "forge", "loader_version": "47.4.10",
        "java_major": 17, "updater_contract": "existing-modsync-api-v1",
        "sync_feed": "https://updates.example.org/mods/manifest.json"
    }
    d.update(kwargs)
    return d


class GateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.signer = Ed25519PrivateKey.generate()
        pub = self.signer.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        self.pub = self.root / "trusted.pub"
        self.pub.write_bytes(pub)
        self.installed, self.installed_sig = self.sign(profile(), "installed")

    def sign(self, data, stem):
        raw = json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode()
        a, b = self.root / (stem + ".json"), self.root / (stem + ".sig")
        a.write_bytes(raw)
        b.write_bytes(base64.b64encode(self.signer.sign(raw)))
        return a, b

    def check(self, incoming, installed=True):
        a, b = self.sign(incoming, "latest")
        return evaluate(a, b, self.pub,
                        self.installed if installed else None,
                        self.installed_sig if installed else None,
                        "demo-server", "updates.example.org")

    def test_unchanged_must_still_poll_existing_updater(self):
        result = self.check(profile())
        self.assertEqual((result["status"], result["action"]), ("READY", "RUN_EXISTING_UPDATER"))
        self.assertFalse(result["download_performed"])

    def test_content_update_same_runtime_runs_existing_updater(self):
        result = self.check(profile(sequence=2))
        self.assertEqual(result["status"], "READY")

    def test_new_profile_requires_manual_initial_install(self):
        result = self.check(profile(), installed=False)
        self.assertEqual(result["action"], "MANUAL_FIRST_INSTALL")
        self.assertEqual(result["status"], "REVIEW_REQUIRED")

    def test_forge_minor_upgrade_requires_migration_review(self):
        result = self.check(profile(sequence=2, loader_version="47.4.11"))
        self.assertEqual(result["action"], "MIGRATION_TEST_REQUIRED")

    def test_change_to_neoforge_requires_migration_review(self):
        result = self.check(profile(sequence=2, minecraft="1.21.1",
                                    loader="neoforge", loader_version="21.1.250",
                                    java_major=21))
        self.assertEqual(result["action"], "MIGRATION_TEST_REQUIRED")

    def test_java_upgrade_requires_migration_review(self):
        result = self.check(profile(sequence=2, java_major=21))
        self.assertEqual(result["action"], "MIGRATION_TEST_REQUIRED")

    def test_updater_contract_change_requires_installer_review(self):
        result = self.check(profile(sequence=2, updater_contract="existing-modsync-api-v2"))
        self.assertEqual(result["action"], "INSTALLER_RECONFIG_REQUIRED")

    def test_endpoint_change_requires_installer_review(self):
        result = self.check(profile(sequence=2,
                                    sync_feed="https://updates.example.org/v2/manifest.json"))
        self.assertEqual(result["action"], "INSTALLER_RECONFIG_REQUIRED")

    def test_downgrade_is_blocked(self):
        _, previous_sig = self.sign(profile(sequence=5), "higher")
        self.installed, self.installed_sig = self.root / "higher.json", previous_sig
        result = self.check(profile(sequence=4))
        self.assertEqual((result["status"], result["action"]), ("BLOCK", "DO_NOT_RUN"))

    def test_conflicting_same_sequence_is_blocked(self):
        result = self.check(profile(loader_version="47.4.12"))
        self.assertEqual(result["reason"], "same_sequence_conflicting_manifest")

    def test_tampered_signed_content_rejected(self):
        a, b = self.sign(profile(), "tamper")
        a.write_bytes(a.read_bytes() + b" ")
        with self.assertRaisesRegex(ReleaseBlocked, "invalid_owner_signature"):
            evaluate(a, b, self.pub, self.installed, self.installed_sig,
                     "demo-server", "updates.example.org")

    def test_wrong_public_key_rejected(self):
        a, b = self.sign(profile(), "wrongkey")
        another = Ed25519PrivateKey.generate()
        other = self.root / "other.pub"
        other.write_bytes(another.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
        with self.assertRaisesRegex(ReleaseBlocked, "invalid_owner_signature"):
            evaluate(a, b, other, None, None, "demo-server", "updates.example.org")

    def test_minecraft_121_with_java_17_is_blocked(self):
        with self.assertRaisesRegex(ReleaseBlocked, "java_too_old_for_minecraft"):
            self.check(profile(sequence=2, minecraft="1.21.1",
                               loader="neoforge", loader_version="21.1.250",
                               java_major=17))

    def test_minecraft_1205_with_java_17_is_blocked(self):
        with self.assertRaisesRegex(ReleaseBlocked, "java_too_old_for_minecraft"):
            self.check(profile(sequence=2, minecraft="1.20.5",
                               java_major=17))

    def test_minecraft_1201_with_java_16_is_blocked(self):
        with self.assertRaisesRegex(ReleaseBlocked, "java_too_old_for_minecraft"):
            self.check(profile(sequence=2, java_major=16))

    def test_untrusted_http_feed_rejected_even_if_signed(self):
        with self.assertRaisesRegex(ReleaseBlocked, "untrusted_sync_feed"):
            self.check(profile(sync_feed="http://modapi.barian.moe/"))

    def test_unapproved_external_https_feed_rejected_even_if_signed(self):
        with self.assertRaisesRegex(ReleaseBlocked, "untrusted_sync_feed"):
            self.check(profile(sync_feed="https://evil.example.net/jars.json"))

    def test_path_traversal_feed_rejected(self):
        with self.assertRaisesRegex(ReleaseBlocked, "untrusted_sync_feed"):
            self.check(profile(sync_feed="https://updates.example.org/../file"))

    def test_invalid_schema_extra_field_rejected(self):
        with self.assertRaisesRegex(ReleaseBlocked, "release_schema_mismatch"):
            self.check(profile(extra="some-new-executable.exe"))

    def test_duplicate_json_keys_rejected_even_if_signed(self):
        raw = json.dumps(profile()).encode()
        raw = raw[:-1] + b',"sequence":100}'
        f = self.root / "duplicate.json"
        g = self.root / "duplicate.sig"
        f.write_bytes(raw)
        g.write_bytes(base64.b64encode(self.signer.sign(raw)))
        with self.assertRaisesRegex(ReleaseBlocked, "duplicate_json_key"):
            evaluate(f, g, self.pub, None, None, "demo-server", "updates.example.org")

    def test_profile_identity_swapping_blocked(self):
        with self.assertRaisesRegex(ReleaseBlocked, "unexpected_profile"):
            self.check(profile(profile="other-server"))

    def test_local_installed_manifest_must_also_be_signed(self):
        self.installed.write_bytes(self.installed.read_bytes() + b" ")
        with self.assertRaisesRegex(ReleaseBlocked, "invalid_owner_signature"):
            self.check(profile(sequence=2))

    def test_no_install_files_or_world_are_touched(self):
        world = self.root / "myworld"
        world.mkdir()
        marker = world / "level.dat"
        marker.write_bytes(b"world-content-do-not-change")
        result = self.check(profile(sequence=2))
        self.assertFalse(result["write_performed"])
        self.assertEqual(marker.read_bytes(), b"world-content-do-not-change")

    def test_cli_returns_zero_only_if_compatible_verified_release(self):
        a, b = self.sign(profile(sequence=2), "ok")
        args = ["--incoming", str(a), "--signature", str(b), "--public-key", str(self.pub),
                "--installed", str(self.installed),
                "--installed-signature", str(self.installed_sig),
                "--profile", "demo-server", "--allowed-host", "updates.example.org"]
        self.assertEqual(main(args), 0)
        self.assertEqual(main(args[:-1] + ["wrong.example.net"]), 2)
        c, d = self.sign(profile(sequence=2, java_major=21), "upgrade")
        args[1], args[3] = str(c), str(d)
        self.assertEqual(main(args), 3)


if __name__ == "__main__":
    unittest.main()
