"""Offline tests: parsing, hints, config. Run with `python3 -m unittest`."""
import os
import unittest
from unittest import mock

import main


class Parse(unittest.TestCase):
    def p(self, text, target="it", fallback="en"):
        return main.parse(text, target, fallback)

    def test_empty_is_help(self):
        self.assertEqual(self.p("  ")["kind"], "help")

    def test_plain_text_detects_and_may_flip(self):
        r = self.p("good morning")
        self.assertEqual((r["src"], r["tgt"], r["flip"], r["text"]), ("auto", "it", "en", "good morning"))

    def test_language_word_without_arrow_is_text(self):
        self.assertEqual(self.p("is this right")["text"], "is this right")

    def test_target_only_never_flips(self):
        r = self.p(">de good morning")
        self.assertEqual((r["src"], r["tgt"], r["flip"]), ("auto", "de", ""))

    def test_both_sides(self):
        r = self.p("it>en buongiorno")
        self.assertEqual((r["src"], r["tgt"], r["text"]), ("it", "en", "buongiorno"))

    def test_source_only_uses_default_target(self):
        r = self.p("de> guten Morgen")
        self.assertEqual((r["src"], r["tgt"]), ("de", "it"))

    def test_source_equal_to_default_target_flips_up_front(self):
        r = self.p("it> buongiorno")
        self.assertEqual((r["src"], r["tgt"], r["flip"]), ("it", "en", ""))

    def test_same_explicit_languages_is_an_error(self):
        self.assertEqual(self.p("it>it ciao")["kind"], "error")

    def test_names_and_aliases(self):
        r = self.p("german>chinese hallo")
        self.assertEqual((r["src"], r["tgt"]), ("de", "zh-CN"))

    def test_unknown_language(self):
        self.assertEqual(self.p("klingon>en hi")["kind"], "error")

    def test_direction_alone_is_hints(self):
        self.assertEqual(self.p(">de")["kind"], "hints")


class Hints(unittest.TestCase):
    cfg = {"target": "it", "fallback": "en", "email": "", "deepl_key": ""}

    def titles(self, src, tgt):
        return [i["title"] for i in main.hint_items(src, tgt, self.cfg)]

    def test_partial_name(self):
        self.assertEqual(self.titles("", "ge"), ["German"])

    def test_complete_code_shows_direction_only(self):
        self.assertEqual(self.titles("", "de"), ["Detect → German"])

    def test_default_target_shows_flip(self):
        self.assertEqual(self.titles("it", "")[0], "Italian → English")


class Config(unittest.TestCase):
    def test_system_language(self):
        for lang, want in [("it_IT.UTF-8", "it"), ("zh_TW.UTF-8", "zh-TW"), ("C", "en"), ("", "en")]:
            with mock.patch.dict(os.environ, {"LANG": lang}, clear=True):
                self.assertEqual(main.system_language(), want, lang)

    def test_fallback_equal_to_target_is_dropped(self):
        t = main.Translator()
        t.init({"target": "en", "fallback": "en"})
        self.assertEqual(t.cfg["fallback"], "")


class MyMemoryAnswers(unittest.TestCase):
    def answer(self, data, text="good morning"):
        with mock.patch.object(main, "http", return_value=data):
            return main.mymemory(text, "en", "de", "", 0)

    def test_machine_translation_beats_memory(self):
        data = {"responseStatus": 200, "responseData": {"translatedText": "Vuoi bere un caffè?"},
                "matches": [{"translation": "Vuoi bere un caffè?", "match": 0.9, "created-by": "x"},
                            {"translation": "Vorrei un caffè", "match": 0.85, "created-by": "MT!"}]}
        self.assertEqual(self.answer(data)["text"], "Vorrei un caffè")

    def test_empty_and_untranslated_memory_is_skipped(self):
        data = {"responseStatus": 200, "responseData": {"translatedText": ""},
                "matches": [{"translation": "", "match": 1},
                            {"translation": "good morning", "match": 1},
                            {"translation": "guten Morgen", "match": 0.99}]}
        self.assertEqual(self.answer(data)["text"], "guten Morgen")

    def test_untranslated_is_same_language(self):
        data = {"responseStatus": 200, "responseData": {"translatedText": "good morning"},
                "matches": [{"translation": "good morning", "match": 0.85, "created-by": "MT!"}]}
        with self.assertRaises(main.SameLanguage):
            self.answer(data)


if __name__ == "__main__":
    unittest.main()
