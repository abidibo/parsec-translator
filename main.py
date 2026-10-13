#!/usr/bin/env python3
"""Parsec plugin: translate text with free online services.

  tr buongiorno            detect the source, translate to the default target
  tr >de good morning      detect the source, translate to German
  tr it>en buongiorno      Italian to English
  tr it> buongiorno        Italian to the default target

Only a first word containing ">" is a direction, so "tr is this right"
translates the sentence instead of reading "is" as Icelandic.

Parsec sends a query on every keystroke and waits for one at a time, so
queries never touch the network: they answer at once with a "Translate"
item whose browse action does the request when the user presses Enter.
Results are cached, so typing the same text again shows the translation
directly.

Services: MyMemory (free, no key) by default; DeepL first when a free API
key is set in the config, falling back to MyMemory if DeepL fails.
"""
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict

USER_AGENT = "parsec-translator/0.1.0"
# Parsec gives up on a reply after 3 s; leave room for the rest.
BUDGET = 2.5
CACHE_SIZE = 200
MAX_HINTS = 12

LANGUAGES = {
    "af": "Afrikaans", "ar": "Arabic", "bg": "Bulgarian", "bn": "Bengali",
    "ca": "Catalan", "cs": "Czech", "cy": "Welsh", "da": "Danish",
    "de": "German", "el": "Greek", "en": "English", "es": "Spanish",
    "et": "Estonian", "eu": "Basque", "fa": "Persian", "fi": "Finnish",
    "fr": "French", "ga": "Irish", "gl": "Galician", "he": "Hebrew",
    "hi": "Hindi", "hr": "Croatian", "hu": "Hungarian", "id": "Indonesian",
    "is": "Icelandic", "it": "Italian", "ja": "Japanese", "ko": "Korean",
    "lt": "Lithuanian", "lv": "Latvian", "ms": "Malay", "mt": "Maltese",
    "nl": "Dutch", "no": "Norwegian", "pl": "Polish", "pt": "Portuguese",
    "ro": "Romanian", "ru": "Russian", "sk": "Slovak", "sl": "Slovenian",
    "sq": "Albanian", "sr": "Serbian", "sv": "Swedish", "sw": "Swahili",
    "ta": "Tamil", "th": "Thai", "tl": "Filipino", "tr": "Turkish",
    "uk": "Ukrainian", "ur": "Urdu", "vi": "Vietnamese",
    "zh-CN": "Chinese (Simplified)", "zh-TW": "Chinese (Traditional)",
}
ALIASES = {"zh": "zh-CN", "nb": "no", "chinese": "zh-CN"}
BY_KEY = {k.lower(): k for k in LANGUAGES}
BY_KEY.update({v.lower(): k for k, v in LANGUAGES.items()})
BY_KEY.update(ALIASES)
CODE_SHAPE = re.compile(r"^[a-z]{2,3}(-[a-z]{2,4})?$", re.I)


class TranslateError(Exception):
    pass


class SameLanguage(TranslateError):
    pass


def resolve(word):
    """A language code or English name, as a code. Unknown but code-shaped
    words pass through: the service knows more languages than the table."""
    key = word.strip().lower()
    if key in BY_KEY:
        return BY_KEY[key]
    if CODE_SHAPE.match(key):
        return key
    return None


def name(code):
    return LANGUAGES.get(code, code)


def system_language():
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var, "").split(".")[0]
        if value and value not in ("C", "POSIX"):
            full = resolve(value.replace("_", "-"))
            if full in LANGUAGES:
                return full
            base = resolve(value.split("_")[0])
            if base:
                return base
    return "en"


# --- parsing -----------------------------------------------------------------

def parse(text, target, fallback):
    """What the user asked for, as a dict with a "kind"."""
    words = text.split(None, 1)
    if not words:
        return {"kind": "help"}
    first = words[0]
    if ">" not in first:
        return {"kind": "translate", "src": "auto", "tgt": target,
                "flip": fallback, "text": text.strip()}
    src_word, _, tgt_word = first.partition(">")
    rest = words[1].strip() if len(words) > 1 else ""
    if not rest:
        return {"kind": "hints", "src": src_word, "tgt": tgt_word}
    src = resolve(src_word) if src_word else "auto"
    if src is None:
        return {"kind": "error", "message": f"Unknown language “{src_word}”"}
    tgt = resolve(tgt_word) if tgt_word else target
    if tgt is None:
        return {"kind": "error", "message": f"Unknown language “{tgt_word}”"}
    # Flip only to spare the user from naming a target they didn't choose.
    flip = fallback if not tgt_word else ""
    if src == tgt:
        if not flip or flip == tgt:
            return {"kind": "error", "message": f"Source and target are both {name(tgt)}"}
        tgt, flip = flip, ""
    return {"kind": "translate", "src": src, "tgt": tgt, "flip": flip, "text": rest}


# --- services ----------------------------------------------------------------

def http(req, deadline):
    left = deadline - time.monotonic()
    if left < 0.3:
        raise TranslateError("Timed out, try again")
    try:
        with urllib.request.urlopen(req, timeout=left) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError:
        raise
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        reason = getattr(e, "reason", e)
        raise TranslateError(f"Network error: {reason}") from None
    except ValueError:
        raise TranslateError("The service sent an unreadable answer") from None


def mymemory(text, src, tgt, email, deadline):
    params = {"q": text, "langpair": f"{'autodetect' if src == 'auto' else src}|{tgt}"}
    if email:
        params["de"] = email
    url = "https://api.mymemory.translated.net/get?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        data = http(req, deadline)
    except urllib.error.HTTPError as e:
        raise TranslateError(f"MyMemory answered HTTP {e.code}") from None
    if data.get("quotaFinished"):
        hint = "" if email else "; add your email to the plugin config for more"
        raise TranslateError("MyMemory's free daily quota is used up" + hint)
    if str(data.get("responseStatus")) != "200":
        details = str(data.get("responseDetails") or "unknown error")
        if "DISTINCT LANGUAGES" in details.upper():
            raise SameLanguage(details)
        raise TranslateError("MyMemory: " + details.split(" . ")[0].split(". ")[0].capitalize())
    answer = data.get("responseData") or {}
    matches = data.get("matches") if isinstance(data.get("matches"), list) else []
    # The crowd-sourced memory often outranks the machine translation with
    # an empty, untranslated or plain wrong segment, so trust the machine
    # when it answered, and walk the memory by match otherwise.
    machine = [m.get("translation") for m in matches if m.get("created-by") == "MT!"]
    ranked = sorted(matches, key=lambda m: -float(m.get("match") or 0))
    candidates = machine[:1] or [answer.get("translatedText")] + [m.get("translation") for m in ranked]
    candidates = [c for c in (html.unescape(c or "").strip() for c in candidates) if c]
    if not candidates:
        raise TranslateError("No translation found")
    source = text.strip().casefold()
    for c in candidates:
        if c.casefold() != source:
            return {"text": c, "service": "MyMemory",
                    "detected": answer.get("detectedLanguage") or ""}
    raise SameLanguage(text)


def deepl_lang(code, target):
    code = code.upper()
    if target:
        code = {"EN": "EN-US", "PT": "PT-PT", "ZH-CN": "ZH-HANS",
                "ZH-TW": "ZH-HANT", "NO": "NB"}.get(code, code)
    else:
        code = {"NO": "NB"}.get(code.split("-")[0], code.split("-")[0])
    return code


def deepl(text, src, tgt, key, deadline):
    host = "api-free.deepl.com" if key.endswith(":fx") else "api.deepl.com"
    body = {"text": [text], "target_lang": deepl_lang(tgt, True)}
    if src != "auto":
        body["source_lang"] = deepl_lang(src, False)
    req = urllib.request.Request(
        f"https://{host}/v2/translate",
        data=json.dumps(body).encode("utf-8"),
        headers={"User-Agent": USER_AGENT, "Content-Type": "application/json",
                 "Authorization": f"DeepL-Auth-Key {key}"},
    )
    try:
        data = http(req, deadline)
    except urllib.error.HTTPError as e:
        why = {403: "rejected the API key", 456: "quota is used up"}.get(e.code, f"answered HTTP {e.code}")
        raise TranslateError(f"DeepL {why}") from None
    try:
        out = data["translations"][0]
    except (KeyError, IndexError, TypeError):
        raise TranslateError("DeepL sent an unreadable answer") from None
    detected = str(out.get("detected_source_language", "")).lower()
    if src == "auto" and detected and detected == tgt.split("-")[0].lower():
        raise SameLanguage(detected)
    return {"text": out.get("text", ""), "service": "DeepL", "detected": detected}


def translate_once(text, src, tgt, cfg, deadline):
    if cfg["deepl_key"]:
        try:
            return deepl(text, src, tgt, cfg["deepl_key"], deadline)
        except SameLanguage:
            raise
        except TranslateError as e:
            print(f"translator: {e}, trying MyMemory", file=sys.stderr)
    return mymemory(text, src, tgt, cfg["email"], deadline)


def translate(text, src, tgt, flip, cfg):
    deadline = time.monotonic() + BUDGET
    try:
        result = translate_once(text, src, tgt, cfg, deadline)
    except SameLanguage:
        if not flip or flip == tgt:
            raise TranslateError(f"The text is already {name(tgt)}") from None
        tgt = flip
        try:
            result = translate_once(text, src, tgt, cfg, deadline)
        except SameLanguage:
            raise TranslateError(f"The text reads the same in {name(tgt)}") from None
    result["src"] = result["detected"] or src
    result["tgt"] = tgt
    return result


# --- items -------------------------------------------------------------------

def web_url(text, src, tgt):
    params = {"sl": src, "tl": tgt, "text": text, "op": "translate"}
    return "https://translate.google.com/?" + urllib.parse.urlencode(params)


def short(text, limit=60):
    return text if len(text) <= limit else text[: limit - 1] + "…"


def direction(src, tgt):
    return f"{'Detect' if src == 'auto' else name(src)} → {name(tgt)}"


def result_items(req, result):
    url = web_url(req["text"], req["src"], result["tgt"])
    return [{
        "id": "result",
        "title": result["text"],
        "subtitle": f"{direction(result['src'], result['tgt'])} · {result['service']}",
        "score": 900,
        "actions": [
            {"label": "Copy", "copy": result["text"]},
            {"label": "Paste", "paste": result["text"]},
            {"label": "Open in Google Translate", "open": url},
        ],
    }]


def error_item(message, url=None):
    item = {"id": "error", "title": message, "icon": "dialog-warning-symbolic", "actions": []}
    if url:
        item["subtitle"] = "Enter opens Google Translate instead"
        item["actions"] = [{"label": "Open in Google Translate", "open": url}]
    return item


def hint_items(src_word, tgt_word, cfg):
    """While the direction is being typed: where it points, and languages
    matching the part after ">"."""
    src = resolve(src_word) if src_word else "auto"
    tgt = resolve(tgt_word) if tgt_word else cfg["target"]
    if src is None:
        return [error_item(f"Unknown language “{src_word}”")]
    if src == tgt and not tgt_word and cfg["fallback"]:
        tgt = cfg["fallback"]
    typed = tgt_word.lower()
    matches = [c for c, n in LANGUAGES.items()
               if c.lower().startswith(typed) or n.lower().startswith(typed)]
    items = []
    # "ge" is code-shaped but most likely the start of "German".
    if tgt is not None and (tgt in LANGUAGES or not matches):
        items.append({"id": "direction", "title": direction(src, tgt),
                      "subtitle": "Type the text to translate after a space",
                      "score": 900, "actions": []})
    if tgt_word and matches == [tgt]:
        return items
    for code in matches[:MAX_HINTS]:
        items.append({"id": f"lang:{code}", "title": LANGUAGES[code],
                      "subtitle": f"{src_word}>{code}", "score": 700, "actions": []})
    if not items:
        items.append(error_item(f"Unknown language “{tgt_word}”"))
    return items


class Translator:
    def __init__(self):
        self.cfg = {"target": "en", "fallback": "en", "email": "", "deepl_key": ""}
        self.cache = OrderedDict()

    def init(self, config):
        config = config or {}
        target = resolve(str(config.get("target") or "")) or system_language()
        fallback = resolve(str(config.get("fallback") or "")) or ""
        self.cfg = {
            "target": target,
            "fallback": "" if fallback == target else fallback,
            "email": str(config.get("email") or "").strip(),
            "deepl_key": str(config.get("deepl_key") or "").strip(),
        }

    def query(self, text):
        req = parse(text, self.cfg["target"], self.cfg["fallback"])
        kind = req["kind"]
        if kind == "help":
            return [{"id": "help", "title": "Type something to translate",
                     "subtitle": f"tr hello · tr >de hello · tr it>en ciao · default: {name(self.cfg['target'])}",
                     "actions": []}]
        if kind == "hints":
            return hint_items(req["src"], req["tgt"], self.cfg)
        if kind == "error":
            return [error_item(req["message"])]
        cached = self.cache.get(self.key(req))
        if cached:
            items = result_items(req, cached)
            items[0]["id"] = "translate"
            return items
        data = {k: req[k] for k in ("src", "tgt", "flip", "text")}
        return [{
            "id": "translate",
            "title": f"Translate “{short(req['text'])}”",
            "subtitle": f"{direction(req['src'], req['tgt'])} · press Enter",
            "actions": [
                {"label": "Translation", "browse": data},
                {"label": "Open in Google Translate",
                 "open": web_url(req["text"], req["src"], req["tgt"])},
            ],
        }]

    def browse(self, data):
        if not isinstance(data, dict) or not data.get("text"):
            return []
        req = {k: str(data.get(k) or "") for k in ("src", "tgt", "flip", "text")}
        key = self.key(req)
        result = self.cache.get(key)
        if result is None:
            try:
                result = translate(req["text"], req["src"], req["tgt"], req["flip"], self.cfg)
            except TranslateError as e:
                return [error_item(str(e), web_url(req["text"], req["src"], req["tgt"]))]
            self.cache[key] = result
            if len(self.cache) > CACHE_SIZE:
                self.cache.popitem(last=False)
        self.cache.move_to_end(key)
        return result_items(req, result)

    @staticmethod
    def key(req):
        return (req["src"], req["tgt"], req["flip"], req["text"])


def main():
    plugin = Translator()
    for line in sys.stdin:
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = msg.get("type")
        try:
            if kind == "init":
                plugin.init(msg.get("config"))
                reply = {"type": "ready"}
            elif kind == "query":
                reply = {"type": "results", "id": msg.get("id"),
                         "items": plugin.query(msg.get("text", ""))}
            elif kind == "browse":
                reply = {"type": "results", "items": plugin.browse(msg.get("data"))}
            else:
                reply = {"type": "ok"}
        except Exception as e:  # never leave Parsec without its one reply line
            print(f"translator: {kind} failed: {e!r}", file=sys.stderr)
            if kind == "init":
                reply = {"type": "ready"}
            elif kind == "query":
                reply = {"type": "results", "id": msg.get("id"), "items": []}
            elif kind == "browse":
                reply = {"type": "results", "items": []}
            else:
                reply = {"type": "ok"}
        sys.stdout.write(json.dumps(reply) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
