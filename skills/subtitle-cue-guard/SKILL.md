---
name: subtitle-cue-guard
description: Translates or repairs SRT and WebVTT subtitle files with an LLM without breaking cue alignment, using a bundled script so timestamps never pass through the model - it extracts numbered cue text, checks translations deterministically (missing, merged, shifted, empty or untranslated cues, lost tags, reading speed, CJK-aware line width), returns the exact cue IDs to retranslate, and reassembles onto the original timings byte for byte; it also converts frame rates and shifts timings. Use when someone asks to translate, localize or fix translated .srt or .vtt subtitles or captions, to find why translated subtitles drifted out of sync, to check subtitle line length or reading speed, or to retime a subtitle file (for example "translate this .srt into Korean", "번역한 자막이 밀렸어", "convert 23.976 to 25 fps"). Not for speech-to-text transcription, burning subtitles into video, or translating documents that are not subtitles.
license: MIT
compatibility: Python 3.10+ (standard library only). No network access.
---

# Translate subtitles without breaking the cues

Models translating a subtitle file by hand merge or skip cues, push text into the neighbouring cue, retype time codes and drop tags, and nobody notices until the sync is off. The script keeps structure, timing and tags; the model only translates numbered text.

First rule: never edit a subtitle file directly and never write time codes yourself. Always produce the result with `assemble`. Run commands as `python3 scripts/cue_guard.py ...` (the path is relative to this skill's folder; use `python` or `uv run` if `python3` is missing). Pass `--lang ko` when the user writes Korean, otherwise `--lang en`.

## Translate a file

1. `python3 scripts/cue_guard.py extract SRC --target LANG -o batch.json` (LANG is a code like `ko`, `en`, `ja`, `es`). Each cue has `id`, `text`, `max_chars` and `max_width`; formatting tags appear as `⟦n⟧` placeholders.
2. Translate each batch yourself. Write one JSON object `{"<id>": "<translation>"}` per batch and merge all batches into `tr.json`. Keep every `⟦n⟧`, use `\n` for line breaks, give one translation per id, never merge, split or skip ids, and stay within `max_chars` and `max_width`.
3. `python3 scripts/cue_guard.py check SRC tr.json --target LANG -o report.json`. Exit code 0 means no problem. Exit code 1 means the `retry` list names cue ids to redo; read `issues` for the reason of each.
4. Retranslate only those cues: `python3 scripts/cue_guard.py extract SRC --target LANG --retry-from report.json --context 1 -o retry1.json`. Context cues are read-only. Save the new translations as `tr.retry1.json`, then check again with `check SRC tr.json tr.retry1.json --target LANG` (later files overwrite earlier ones).
5. Retry at most 2 rounds. Then `python3 scripts/cue_guard.py assemble SRC tr.json tr.retry1.json --target LANG -o OUT.srt`. Add `--fallback source` only after the second round: failing cues keep their original text and the output lists them under `fallback`. Tell the user which cue ids kept the source text and need a human look.
6. Report the output path, the number of retry rounds and any fallback ids. A `suspect` issue is a guess (a merge or shift looks likely), not proof.

## Translations already supplied (build a file from them)

When the user gives the translations (a JSON file keyed by cue number, or an already translated .srt/.vtt) and wants the final file, skip `extract`. Do not open, clean up or retype anything:

1. `python3 scripts/cue_guard.py assemble SRC tr.json --target LANG -o OUT` where OUT keeps the source extension (`ko.vtt` for a `.vtt`) and the name the user asked for. Pass the JSON exactly as given, including every `⟦n⟧` marker: the script turns them back into the original tags (`<v Anna>`, `<c.yellow>`, `<i>`), so never delete, "fix" or convert them yourself.
2. Read the JSON it prints. `"written": true` means OUT was created. If it says `"written": false`, run `check` as in step 3 above and handle the listed ids. In your reply, quote the result as printed (for example `"written": true`, `"fallback": []`) next to the output path.
3. Do not edit, re-save, reformat or re-encode OUT afterwards (no editor, `sed`, or rewrite through Python). The script already keeps the BOM, CRLF line endings, `NOTE`/`STYLE`/`REGION` blocks, cue identifiers and cue settings (`align:`, `line:`, `region:`) of the source byte for byte; any later edit can only damage them. To confirm, run `check SRC OUT --target LANG`. If the user asks for a checksum, hash the file's bytes (`shasum -a 256 OUT`, `sha256sum OUT`, or Python `hashlib.sha256(Path(OUT).read_bytes())`); reading it as text first turns CRLF into LF and gives the wrong hash.

## Other jobs

- Diagnose an already translated file: `check SRC TRANSLATED.srt --target LANG` (the second file can itself be an .srt or .vtt; cues are matched by order), then fix only the listed ids as above.
- Frame rate, shift, minimum duration: `python3 scripts/cue_guard.py retime SRC --fps 23.976:25 -o OUT.srt` (use the source's extension), `--shift=+1.5s` (write negatives with an equals sign: `--shift=-2s`), `--min-duration 0.83 --min-gap 0.083`. Report any warning it prints.
- Reading speed and line length: `check` applies Netflix-based limits for `ko` and `en`; for other languages pass `--cps N --line-width N --max-lines N`, or `--profile file.json`. Add `--no-retry-readability` when the user only wants the numbers and not a retranslation.
- Add the original text above the translation with `assemble --bilingual`; renumber with `--renumber`.

If a script exits with code 2, show its error line as is; it says how to fix the input. Do not guess a different file or language.

For what each issue code means and what to do about it, read `references/issue-codes.md`. For the limits behind `ko` and `en` and how to override them, read `references/readability-profiles.md`. For the SRT and WebVTT pitfalls the parser handles, read `references/formats.md`.
