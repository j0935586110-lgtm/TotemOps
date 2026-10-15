# SPDX-License-Identifier: Apache-2.0
"""Public website and documented Agent workflow regression tests."""
import subprocess
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs=[]
    def handle_starttag(self,tag,attrs):
        if tag == "a":
            a=dict(attrs)
            if a.get("href"):
                self.hrefs.append(a["href"])


class SiteAndOnboardingTests(unittest.TestCase):
    def test_site_home_and_quickstart_local_links_resolve(self):
        for page in ("index.html","start.html"):
            source=(DOCS/page).read_text(encoding="utf-8")
            parser=LinkParser()
            parser.feed(source)
            self.assertGreater(len(parser.hrefs), 3)
            for href in parser.hrefs:
                if href.startswith(("https://","http://","mailto:","#")):
                    continue
                target=DOCS/href.split("#")[0].split("?")[0]
                self.assertTrue(target.is_file(),(page,href))

    def test_home_has_local_quickstart_link_and_translation(self):
        html=(DOCS/"index.html").read_text(encoding="utf-8")
        self.assertIn('href="start.html"',html)
        self.assertIn('footerDev:"開發者文件"',html)
        self.assertIn('footerDev:"Developer docs"',html)
        self.assertNotIn('data-i18n="navSkill"',html)
        self.assertNotIn('data-i18n="btnSkill"',html)
        self.assertEqual(html.count('href="start.html"'),1)

    def test_home_keeps_beginner_focus_and_footer_only_technical_entry(self):
        html=(DOCS/"index.html").read_text(encoding="utf-8")
        self.assertEqual(html.count('href="start.html"'),1)
        footer=html.split("<footer>",1)[1]
        self.assertIn('href="start.html"',footer)
        header=html.split("<footer>",1)[0]
        self.assertNotIn('data-i18n="btnSkill"',header)
        self.assertNotIn('data-i18n="navSkill"',header)
        self.assertIn('data-i18n="btnTry"',header)

    def test_readmes_show_beginner_problem_before_developer_docs(self):
        for name, start in (("README.md","## 你是不是遇過這些事？"),
                            ("README.en.md","## Does any of this sound familiar?")):
            readme=(ROOT/name).read_text(encoding="utf-8")
            self.assertLess(readme.index(start),readme.index("start.html"))
            self.assertNotIn("agy plugin install",readme)

    def test_quickstart_explains_all_three_with_limitations(self):
        page=(DOCS/"start.html").read_text(encoding="utf-8")
        for command in ("totem-ops manifest","totem-ops crash","totem-ops smoke"):
            self.assertIn(command,page)
        self.assertIn("REVIEW_REQUIRED",page)
        self.assertIn("release_allowed",page)
        self.assertIn("Clone",page)
        self.assertIn('aria-pressed="false"',page)
        self.assertNotIn("mcpServers",page)

    def test_readme_links_match_site_and_real_skill_locations(self):
        for name in ("README.md","README.en.md"):
            s=(ROOT/name).read_text(encoding="utf-8")
            self.assertIn("start.html",s)
            self.assertIn("docs/ADVANCED_GUIDE.",s)
            self.assertIn("start.html",s)
            self.assertNotIn("agy plugin install",s)
            self.assertNotIn("manifest ./mods",s)
        for path in ("SKILL.md",
                     ".agents/skills/totem-ops/SKILL.md",
                     ".claude/skills/totem-ops/SKILL.md",
                     "skills/totem-ops/SKILL.md"):
            self.assertTrue((ROOT/path).is_file(),path)

    def test_cli_still_lists_legacy_and_three_core_commands(self):
        p=subprocess.run([sys.executable,str(ROOT/"tools"/"totem_operator.py"),"--help"],
                         cwd=ROOT,capture_output=True,text=True,timeout=9)
        self.assertEqual(p.returncode,0)
        for command in ("manifest","crash","smoke","plugins","maintainer","solve-and-verify"):
            self.assertIn(command,p.stdout)

if __name__ == "__main__":
    unittest.main()
