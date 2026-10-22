# SPDX-License-Identifier: Apache-2.0
"""Static release checks for the bilingual public TotemOps site.

Every public page must share one header, one language controller and one
dictionary. Offline only: never launches Minecraft, fetches the web, or
changes user files.
"""
from html.parser import HTMLParser
from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
SITE = DOCS / "index.html"
ASSETS = DOCS / "assets"
I18N = ASSETS / "site-i18n.js"
HEADER_JS = ASSETS / "site-header.js"
HEADER_CSS = ASSETS / "site-header.css"
PAGES = {
    "home": DOCS / "index.html",
    "diag": DOCS / "diagnose.html",
    "start": DOCS / "start.html",
}
NAV_KEYS = ["home", "navTry", "navPain", "navHow", "navStatus", "navStart"]
TRANSLATED_ATTRIBUTES = (
    "data-i18n",
    "data-i18n-html",
    "data-i18n-label",
    "data-i18n-placeholder",
    "data-i18n-alt",
)
PAIR = re.compile(r'"([\w.]+)":\s*"((?:[^"\\]|\\.)*)"')


def load_dictionary():
    text = I18N.read_text(encoding="utf-8")
    zh_block = text.split("  zh: {", 1)[1].split("  en: {", 1)[0]
    en_block = text.split("  en: {", 1)[1].split("  titles:", 1)[0]
    zh = {m.group(1): m.group(2) for m in PAIR.finditer(zh_block)}
    en = {m.group(1): m.group(2) for m in PAIR.finditer(en_block)}
    return zh, en


class SiteParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.images = []
        self.language_buttons = []
        self.translation_keys = []
        self.links = []
        self.css = []
        self.scripts = []
        self.page = None
        self.nav_keys = []
        self.classes = []
        self.meta = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "body":
            self.page = attrs.get("data-page")
        if tag == "img":
            self.images.append(attrs)
        if tag == "button" and attrs.get("data-select-language"):
            self.language_buttons.append(attrs["data-select-language"])
        for attribute in TRANSLATED_ATTRIBUTES:
            if attribute in attrs:
                self.translation_keys.append(attrs[attribute])
        if attrs.get("class"):
            self.classes.append(attrs["class"])
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])
            if "aria-current" in attrs and attrs.get("data-i18n"):
                self.nav_keys.append(attrs["data-i18n"])
        if tag == "link" and attrs.get("rel") == "stylesheet":
            self.css.append(attrs.get("href"))
        if tag == "script" and attrs.get("src"):
            self.scripts.append(attrs["src"])
        if tag == "meta" and attrs.get("name"):
            self.meta[attrs["name"]] = attrs.get("content", "")



class SharedHeaderTests(unittest.TestCase):
    def setUp(self):
        self.zh, self.en = load_dictionary()
        self.parsed = {}
        for name, path in PAGES.items():
            self.parsed[name] = SiteParser()
            self.parsed[name].feed(path.read_text(encoding="utf-8"))

    def test_every_page_uses_the_same_header_and_language_control(self):
        for name, parser in self.parsed.items():
            html = PAGES[name].read_text(encoding="utf-8")
            self.assertEqual(parser.page, name, f"{name}: body[data-page]")
            self.assertEqual(set(parser.language_buttons), {"zh", "en"}, f"{name}: language buttons")
            self.assertIn("assets/site-header.css", parser.css, f"{name}: shared stylesheet")
            self.assertIn("assets/site-i18n.js", parser.scripts, f"{name}: shared dictionary")
            self.assertIn("assets/site-header.js", parser.scripts, f"{name}: shared controller")
            self.assertIn("totem-header", html, f"{name}: shared header markup")
            self.assertEqual(html.count('class="totem-header"'), 1, f"{name}: exactly one shared header")
            # legacy per-page implementations must be gone
            self.assertNotIn('class="topbar"', html, f"{name}: legacy topbar")
            self.assertNotIn('class="header"', html, f"{name}: duplicate header class")
            self.assertNotIn('class="lang"', html, f"{name}: duplicate language widget")
            self.assertNotIn("setLanguage(", html, f"{name}: inline language script")

    def test_navigation_is_identical_on_every_page(self):
        sequences = []
        for name, path in PAGES.items():
            html = path.read_text(encoding="utf-8")
            nav = html.split('class="totem-nav"', 1)[1].split("</nav>", 1)[0]
            keys = [k[len("common."):] if k.startswith("common.") else k
                    for k in re.findall(r'data-i18n="([^"]+)"', nav)]
            sequences.append(keys)
        self.assertEqual(sequences[0], NAV_KEYS)
        for name, sequence in zip(PAGES, sequences):
            self.assertEqual(sequence, NAV_KEYS, f"{name}: nav label order")
        self.assertTrue(HEADER_CSS.is_file())

    def test_controller_is_the_only_language_implementation(self):
        script = HEADER_JS.read_text(encoding="utf-8")
        for token in (
            "totemops-language",
            "localStorage.setItem",
            "data-select-language",
            "addEventListener(\"click\"",
            "setLanguage",
            "data-i18n-label",
            "data-i18n-placeholder",
            "TOTEM_TRANSLATE",
        ):
            self.assertIn(token, script)

    def test_dictionary_is_complete_for_every_page_and_language(self):
        self.assertEqual(set(self.zh), set(self.en), "zh/en key mismatch")
        for name, parser in self.parsed.items():
            for key in parser.translation_keys:
                candidates = [key] if key.startswith("common.") else [f"{name}.{key}", f"common.{key}"]
                for lang, table in (("zh", self.zh), ("en", self.en)):
                    self.assertTrue(
                        any(candidate in table for candidate in candidates),
                        f"{name}: missing {lang} translation for {key} (tried {' / '.join(candidates)})",
                    )
        self.assertGreaterEqual(len(self.parsed["home"].translation_keys), 45)

    def test_english_copy_contains_no_leftover_chinese(self):
        for key, value in self.en.items():
            self.assertIsNone(
                re.search(r"[\u4e00-\u9fff]", value),
                f"untranslated English value for {key}",
            )

    def test_titles_and_descriptions_switch_language(self):
        titles = I18N.read_text(encoding="utf-8").split("  titles: {", 1)[1]
        for page in PAGES:
            self.assertEqual(titles.count(f'"{page}":'), 2, f"{page}: zh/en title")
        for name, parser in self.parsed.items():
            self.assertIn(f"{name}.metaDescription", self.zh, f"{name}: zh meta description")
            self.assertIn(f"{name}.metaDescription", self.en, f"{name}: en meta description")

    def test_diagnose_csp_still_allows_its_own_assets_only(self):
        html = PAGES["diag"].read_text(encoding="utf-8")
        match = re.search(r'Content-Security-Policy" content="([^"]+)"', html)
        self.assertIsNotNone(match)
        csp = match.group(1)
        self.assertIn("style-src 'self' 'unsafe-inline'", csp)
        self.assertIn("script-src 'self'", csp)
        self.assertIn("connect-src 'none'", csp)
        self.assertIn("default-src 'none'", csp)

    def test_all_public_images_are_valid_xml_and_exist(self):
        parser = self.parsed["home"]
        self.assertGreaterEqual(len(parser.images), 2)
        for image in parser.images:
            src = image["src"]
            self.assertFalse(src.startswith(("https://", "http://")))
            self.assertTrue((SITE.parent / src).is_file(), src)
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
