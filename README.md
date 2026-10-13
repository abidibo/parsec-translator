# Parsec Translator

A [Parsec](https://github.com/abidibo/parsec) plugin that translates text
with free online services. No account, no key, nothing to host.

```
tr buongiorno            detect the language, translate to yours
tr >de good morning      translate to German
tr it>en buongiorno      Italian to English
tr it> buongiorno        Italian to your language
```

Type `tr`, the text, Enter: the translation appears, Enter again copies it,
Tab offers Paste (into the window you came from) and Open in Google Translate.
Translations are remembered, so the same text again shows the result at once.

## Install

```sh
parsec plugin install https://github.com/abidibo/parsec-translator
```

or Settings › Plugins › install from the git URL, a `.zip` or a folder.
Needs Python 3.8+ and nothing else.

## Choosing languages

Only a first word containing `>` sets the direction, so `tr is this right`
translates the sentence instead of reading "is" as Icelandic.

- `src>tgt`: both sides; either can be left empty (`>de`, `it>`).
- Languages are ISO codes (`de`, `pt`, `zh-CN`, `zh-TW`) or English names
  (`german`, `chinese`). Codes outside the built-in list pass straight to the
  service.
- While you type the direction, the results list matching languages:
  `tr >ge` shows German.
- With no target, the text goes to your default language. If it is already
  in that language, it goes to the fallback (English) instead, so plain `tr`
  works both ways.

## Configuration

`~/.local/share/parsec/plugins/translator/plugin.toml`:

```toml
[config]
target = ""         # default target language; empty = your system language ($LANG)
fallback = "en"     # used when the text is already in the target language
email = ""          # optional: raises MyMemory's free quota
deepl_key = ""      # optional free DeepL API key; tried first when set
```

If your system language is English, set `fallback` to the language you
translate from most (say `"it"`), so plain `tr` works both ways.

## Services

- **[MyMemory](https://mymemory.translated.net/doc/spec.php)**, the default.
  Free, no key. About 5,000 characters a day per IP address; 50,000 with an
  `email` set. At most 500 characters per translation. The plugin prefers
  its machine translation over its crowd-sourced memory, which is often wrong
  for short phrases.
- **[DeepL](https://www.deepl.com/pro-api)**, optional, better quality. A free
  account gives a key and 500,000 characters a month. When DeepL fails
  (quota, unsupported language) the plugin falls back to MyMemory.

The text you translate is sent to these services.

## How it works

Parsec sends a query on every keystroke and gives each reply three seconds.
Queries never touch the network: they answer at once with a "Translate"
item, and the request happens only when you press Enter on it (a `browse`
action). Errors show in the list with a link to Google Translate instead.

## Development

```sh
python3 -m unittest          # offline tests
parsec plugin install .      # try it in Parsec
```

## License

MIT
