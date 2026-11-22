# Readability profiles

Built-in defaults, confirmed 2026-11-21. Every value can be overridden with `--cps`, `--line-width`, `--max-lines` or a profile file.

| Language | Characters per second | Characters per line | Lines | Width mode | Source |
|---|---|---|---|---|---|
| `ko` | 12 (spaces not counted) | 16 | 2 | `eaw` | Netflix Korean Timed Text Style Guide, https://partnerhelp.netflixstudios.com/hc/en-us/articles/216001127 |
| `en` | 20 (spaces counted) | 42 | 2 | `count` | Netflix English (USA) Timed Text Style Guide, https://partnerhelp.netflixstudios.com/hc/en-us/articles/217350977-English-USA-Timed-Text-Style-Guide |

Whether spaces count towards the reading speed (`cps_spaces`) is this tool's default for each language, not a quotation from the guides. Other published numbers differ (Netflix automated checks have been reported with higher Korean limits), so treat the defaults as a strict starting point and override them when the client or platform says otherwise.

`ja` and `zh` only get a script check (kana or Han for Japanese, Han for Chinese) and no limits, because no confirmed source was available. Other language codes (`es`, `fr`, `de`, `pt`, `ru`, `ar`, `hi`, `th`, ...) check only that a cue is not identical to the source. Give limits with flags to get readability checks for them. A language code that is not known at all needs `--profile` or all of `--cps`, `--line-width` and `--max-lines`.

## Width modes

- `eaw`: East Asian wide and fullwidth characters (Hangul, kana, Han, fullwidth forms) count 1, every other character (Latin, digits, spaces, punctuation) counts 0.5, combining marks 0.
- `count`: one per character.

## Profile file

```json
{"cps": 17, "line_width": 20, "max_lines": 2, "width_mode": "eaw", "cps_spaces": false, "script": "kana_han"}
```

All keys are optional; `script` is one of `hangul`, `kana_han`, `han`, `none`. Flags win over the file, the file wins over the built-in profile. Pass the file with `--profile file.json` to `extract` and `check`.
