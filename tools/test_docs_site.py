# SPDX-License-Identifier: Apache-2.0
"""Static release checks for bilingual public-facing TotemOps documentation.

Offline only: never launches Minecraft, fetches the web, or changes user files.
"""
from html.parser import HTMLParser
from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "docs/index.html"
ASSETS = ROOT / "docs/assets"


class SiteParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.images = []
        self.language_buttons = []
        self.translation_keys = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "img":
            self.images.append(attrs)
        if tag == "button" and attrs.get("data-select-language"):
            self.language_buttons.append(attrs["data-select-language"])
        if "data-i18n" in attrs:
            self.translation_keys.append(attrs["data-i18n"])
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])


class BilingualReleaseDocsTests(unittest.TestCase):
    def setUp(self):
        self.html = SITE.read_text(encoding="utf-8")
        self.parser = SiteParser()
        self.parser.feed(self.html)

    def test_site_has_real_one_click_language_controls(self):
        self.assertEqual(set(self.parser.language_buttons), {"zh", "en"})
        self.assertIn('addEventListener("click"', self.html)
        self.assertIn("setLanguage(", self.html)
        self.assertIn("totemops-language", self.html)

    def test_translations_cover_all_visible_label_keys(self):
        keys = set(self.parser.translation_keys)
        self.assertGreaterEqual(len(keys), 45)
        js = self.html.split("<script>", 1)[1].split("</script>", 1)[0]
        zh = js.split("        zh:{", 1)[1].split("        en:{", 1)[0]
        en = js.split("        en:{", 1)[1].split("      };", 1)[0]
        for name, block in (("zh", zh), ("en", en)):
            definitions = set(re.findall(r"([a-zA-Z]\w*):\"", block))
            self.assertEqual(keys - definitions, set(), f"{name} missing translations")

    def test_all_public_images_are_valid_xml_and_exist(self):
        self.assertGreaterEqual(len(self.parser.images), 2)
        for image in self.parser.images:
            src = image["src"]
            self.assertFalse(src.startswith(("https://", "http://")))
            path = SITE.parent / src
            self.assertTrue(path.is_file(), src)
            self.assertTrue(image.get("alt"), "images need accessibility alt text")
        for name in ("totemops-hero.svg", "totemops-steps-zh.svg", "totemops-steps-en.svg", "favicon.svg"):
            ET.parse(ASSETS / name)

    def test_readmes_have_prominent_language_links_and_images(self):
        for file, other, steps in (
            ("README.md", "README.en.md", "totemops-steps-zh.svg"),
            ("README.en.md", "README.md", "totemops-steps-en.svg"),
        ):
            md = (ROOT / file).read_text(encoding="utf-8")
            self.assertIn(f"]({other})", "\n".join(md.splitlines()[:22]))
            self.assertIn("totemops-hero.svg", md)
            self.assertIn(steps, md)
            self.assertIn("docs/ADVANCED_GUIDE.", md)
            self.assertLess(len(md.splitlines()), 175)

    def test_advanced_guides_stay_accessible(self):
        for name in ("ADVANCED_GUIDE.zh-TW.md", "ADVANCED_GUIDE.en.md"):
            path = ROOT / "docs" / name
            self.assertTrue(path.is_file())
            self.assertIn("../README.", path.read_text(encoding="utf-8").splitlines()[2])


if __name__ == "__main__":
    unittest.main()
