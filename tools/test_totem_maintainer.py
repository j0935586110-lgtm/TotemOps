#!/usr/bin/env python3
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import totem_maintainer as m

class MaintainerTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory()
        self.root=Path(self.t.name)
        def git(*args):
            subprocess.run(["git",*args],cwd=self.root,check=True,capture_output=True)
        git("init","-b","main")
        git("config","user.email","test@example.invalid")
        git("config","user.name","Test")
        git("remote","add","origin","https://github.com/Barian0517/Multiverse-Forge-V2.git")
        (self.root/"README.md").write_text("Mock public repo\n")
        git("add","README.md")
        git("commit","-m","seed")
        self.sha=m.command("rev-parse","HEAD",cwd=self.root)
        self.manifest={
            "schema":1,"id":"barian0517",
            "repositories":[{"github":"Barian0517/Multiverse-Forge-V2","ref":"main",
                "sha":self.sha,"loader":"forge","minecraft":"1.20.1",
                "build":["./gradlew","build"],"focus":["CI"]}]
        }
    def tearDown(self):self.t.cleanup()
    def inspect(self):
        with patch.object(m,"profile",return_value=self.manifest):
            return m.inspect(self.root,"barian0517")
    def test_approved_project_read_only(self):
        a=m.command("status","--porcelain",cwd=self.root)
        v=self.inspect()
        self.assertEqual(v["status"],"PASS")
        self.assertTrue(v["head_matches_profile"])
        self.assertFalse(v["build_executed"])
        self.assertFalse(v["changes_made"])
        self.assertFalse(v["remote_write"])
        self.assertEqual(a,m.command("status","--porcelain",cwd=self.root))
    def test_ci_candidates_have_evidence_lines(self):
        folder=self.root/".github"/"workflows"
        folder.mkdir(parents=True)
        (self.root/"settings.gradle").write_text("rootProject.name = 'multiverse'\n")
        (folder/"ci.yml").write_text(
            'on:\n  pull_request:\n    branches: [ "master" ]\n'
            'jobs:\n  build:\n    steps:\n'
            '      - run: ./gradlew :Multiworld-Fabric-1.21.11:build\n')
        a=self.inspect()["ci_findings"]
        self.assertEqual(len(a),2)
        self.assertEqual({x["kind"] for x in a},
                         {"workflow_branch_mismatch_candidate","gradle_unknown_project_candidate"})
        self.assertEqual({x["line"] for x in a},{3,7})
    def test_custom_gradle_project_respected(self):
        folder=self.root/".github"/"workflows"
        folder.mkdir(parents=True)
        (self.root/"settings.gradle").write_text('include ":Multiworld-Fabric-1.21.11"\n')
        (folder/"ci.yml").write_text('      - run: ./gradlew :Multiworld-Fabric-1.21.11:build\n')
        self.assertEqual(self.inspect()["ci_findings"],[])
    def test_untrusted_origin_rejected(self):
        subprocess.run(["git","remote","set-url","origin",
                        "https://user:token@github.com/Barian0517/Multiverse-Forge-V2.git"],
                        cwd=self.root,check=True,capture_output=True)
        with self.assertRaisesRegex(m.MaintainerBlock,"untrusted_git_origin"):self.inspect()
    def test_cross_owner_repo_rejected(self):
        subprocess.run(["git","remote","set-url","origin",
                        "https://github.com/chyuaner/Minecraft-NeoAuthReloaded.git"],
                        cwd=self.root,check=True,capture_output=True)
        with self.assertRaisesRegex(m.MaintainerBlock,"repository_not_in_selected_profile"):self.inspect()
    def test_not_repo_root_rejected(self):
        (self.root/"nested").mkdir()
        with patch.object(m,"profile",return_value=self.manifest):
            with self.assertRaisesRegex(m.MaintainerBlock,"must_supply_git_root"):
                m.inspect(self.root/"nested","barian0517")
    def test_pin_change_is_reported_not_hidden(self):
        self.manifest["repositories"][0]["sha"]="0"*40
        r=self.inspect()
        self.assertFalse(r["head_matches_profile"])
        self.assertEqual(r["status"],"STALE_PROFILE")
    def test_unknown_profile_blocks(self):
        with self.assertRaisesRegex(m.MaintainerBlock,"unknown_profile"):
            m.profile("../../../etc/passwd")
    def test_live_profiles_load_and_ids_are_fixed(self):
        for n in ("barian0517","chyuaner"):
            d=m.profile(n)
            self.assertGreaterEqual(len(d["repositories"]),2)
            self.assertEqual(d["id"],n)
    def test_workflow_symlink_skipped(self):
        folder=self.root/".github"/"workflows"
        folder.mkdir(parents=True)
        (folder/"ci.yml").symlink_to(self.root/"README.md")
        self.assertEqual(self.inspect()["ci_findings"],[])
    def test_exploit_from_workflow_never_executed(self):
        folder=self.root/".github"/"workflows"
        folder.mkdir(parents=True)
        (folder/"ci.yml").write_text("run: echo pwned > /tmp/totemops-not-executed\n")
        v=self.inspect()
        self.assertFalse(v["build_executed"])
        self.assertFalse(v["changes_made"])

if __name__=="__main__":unittest.main()
