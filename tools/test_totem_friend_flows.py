#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Tests with local fixtures only; no network and no friend server access."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import totem_friend_flows as f
from totem_maintainer import MaintainerBlock


class FriendFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.base=Path(self.temp.name)
        for name in ("barian","api","yuan"):
            (self.base/name).mkdir()
        self.paths={"Barian0517/modsync-v2":self.base/"barian",
                    "chyuaner/php-minecraft-server-info":self.base/"api",
                    "chyuaner/python-minecraft-mods-sync":self.base/"yuan"}
        def save(root, name, content):
            p=root/name
            p.parent.mkdir(parents=True,exist_ok=True)
            p.write_text(content,encoding="utf-8")
        save(self.base/"barian","main.py",
             'auto_mode = "--auto" in args\n'
             'dir_path = "--dir"\n'
             'window.worker.finished.connect(close_when_done)\n'
             'app.quit()\nserverUrl = "http://modapi.barian.moe/"\n')
        save(self.base/"barian","MainWindow.py","from tkinter import QWidget\n")
        save(self.base/"barian","WorkerThread.py",
             'def collect_download_tasks():\n    pass\n'
             'def download_and_verify():\n    if download_file():\n        pass\n    return True\n'
             'other = "/config_names?json=1"\n'
             'target = "/{folder}/?json=1"\n')
        save(self.base/"api","public/mods.php",
             "<?php $routerConfigMap=['mods' => 'common']; "
             "$app->group('test', function($group) { "
             "$group->get('', function () {}); "
             "$group->get('/zip', function () {}); });\n"
             "$out=['mods' => []];\n")
        save(self.base/"api","src/McModUtils/Mod.php",
             '<?php $out = ["sha1"=> $sha1, "downloadUrl"=> $url];\n')
        save(self.base/"yuan","src/mcmods_sync/server.py",
             'url = "mods/?type=json"\n'
             'm = data.get("mods")\n'
             'sha = mod.get("sha1", "")\n'
             'link = mod.get("downloadUrl")\n')
        save(self.base/"yuan","src/mcmods_sync/config.py",
             'url = "https://api-minecraft.yuaner.tw/"\n')
        self.patcher=patch.object(f,"provenance",side_effect=self.fake_provenance)
        self.patcher.start()
    def fake_provenance(self, path, profile, expected):
        if expected not in self.paths:
            raise MaintainerBlock("not_pinned")
        if Path(path).resolve()!=self.paths[expected].resolve():
            raise MaintainerBlock("wrong_checkout")
        return self.paths[expected], {"github":expected, "head":"a"*40}
    def tearDown(self):
        self.patcher.stop()
        self.temp.cleanup()
    def barian(self):
        return f.barian_player_flow(str(self.base/"barian"))
    def yuan(self, *paths):
        return f.yuan_api_impact(str(self.base/"api"),str(self.base/"yuan"),
                                 str(self.base/"barian"),list(paths))
    def test_barian_existing_updater_stays_reusable(self):
        r=self.barian()
        self.assertTrue(r["existing"]["auto_sync_flag"])
        self.assertTrue(r["existing"]["target_directory_flag"])
        self.assertEqual(r["status"],"ACTIONABLE")
        self.assertEqual(r["verification"],"STATIC_ONLY")
        self.assertFalse(r["installation_performed"])
        self.assertFalse(r["remote_write"])
    def test_auto_finished_without_success_is_a_release_gap(self):
        r=self.barian()
        self.assertEqual(next(x for x in r["gaps"] if x["id"]=="SYNC_COMPLETION")["status"],
                         "STATIC_RISK")
    def test_download_false_success_is_release_gap(self):
        r=self.barian()
        self.assertEqual(next(x for x in r["gaps"] if x["id"]=="DOWNLOAD_RESULT")["status"],
                         "STATIC_RISK")
    def test_improved_updater_does_not_still_claim_the_same_risk(self):
        p=self.base/"barian"/"main.py"
        p.write_text(p.read_text()+"\nif worker.success: print('success')\n")
        self.assertEqual(next(x for x in self.barian()["gaps"] if x["id"]=="SYNC_COMPLETION")["status"],
                         "NOT_VERIFIED")
    def test_backend_api_affects_yuan_updater_not_automatically_barian(self):
        r=self.yuan("public/mods.php")
        self.assertEqual(r["status"],"ACTIONABLE")
        self.assertEqual(r["relationships"][0]["status"],"SOURCE_CONTRACT_MATCH")
        self.assertIs(r["relationships"][0]["affected"],True)
        self.assertEqual(r["relationships"][1]["affected"],"UNKNOWN")
        self.assertEqual(r["relationships"][1]["status"],"DIFFERENT_DEFAULT_API")
        self.assertFalse(r["real_api_called"])
    def test_unrelated_backend_change_is_not_a_client_alarm(self):
        r=self.yuan("docs/use/overview.md")
        self.assertEqual(r["status"],"NO_KNOWN_SYNC_CONTRACT_CHANGE")
        self.assertIs(r["relationships"][0]["affected"],False)
    def test_multiple_change_paths_deduplicated(self):
        r=self.yuan("public/mods.php","public/mods.php","docs/README.md")
        self.assertEqual(r["changed_paths"],["public/mods.php","docs/README.md"])
    def test_missing_field_triggers_needs_review(self):
        p=self.base/"yuan"/"src/mcmods_sync/server.py"
        p.write_text(p.read_text().replace('mod.get("sha1"', 'mod.get("md5"'))
        r=self.yuan("public/mods.php")
        self.assertEqual(r["relationships"][0]["status"],"NEEDS_REVIEW")
    def test_symlink_input_blocked(self):
        p=self.base/"barian"/"main.py"
        p.unlink()
        p.symlink_to(self.base/"yuan"/"src/mcmods_sync/server.py")
        with self.assertRaisesRegex(MaintainerBlock,"required_source_not_regular"):
            self.barian()
    def test_path_traversal_never_allowed(self):
        for candidate in ("../secrets.txt", "/private/path", "a\\b", "abc;echo x"):
            with self.subTest(path=candidate):
                with self.assertRaisesRegex(MaintainerBlock,"invalid_changed_path"):
                    self.yuan(candidate)
    def test_wrong_checkout_blocks(self):
        with self.assertRaisesRegex(MaintainerBlock,"wrong_checkout"):
            f.barian_player_flow(str(self.base/"api"))
    def test_cli_error_is_machine_readable(self):
        output=io.StringIO()
        with contextlib.redirect_stdout(output):
            rc=f.main(["barian-player","--repo-dir",str(self.base/"api")])
        self.assertEqual(rc,2)
        body=json.loads(output.getvalue())
        self.assertEqual(body["status"],"BLOCK")
        self.assertFalse(body["remote_write"])


if __name__=="__main__":
    unittest.main()
