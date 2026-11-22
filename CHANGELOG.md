# Changelog

All notable changes to this project are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [0.1.1] - 2026-11-23

### Changed
- README: how to remove an `unexpected_id` before re-checking, and why the Codex CLI row is not verified.
- CI: line-ending policy in `.gitattributes` (byte-exact CRLF/BOM fixtures are `-text`), pytest-only dev dependencies, tests that pass under a non-UTF-8 locale and forced colour on Python 3.10–3.14.

## [0.1.0] - 2026-11-22

### Added
- `extract`, `check`, `assemble` and `retime` commands in `scripts/cue_guard.py` (standard library only).
- Byte-preserving SRT/WebVTT parser: BOM, CRLF, duplicate or missing numbers, `NOTE`/`STYLE`/`REGION` blocks, cue ids and settings survive untouched.
- Deterministic checks with a retry list: missing, unexpected, empty, untranslated, tag and number mismatches, shifted and merged cues (also without number anchors), reading speed, line count, CJK-aware line width.
- Language profiles for `ko` and `en` with sources; `ja`, `zh` and other languages check only the script or identity unless limits are given.
- English and Korean screen language (`--lang`, `SUBTITLE_CUE_GUARD_LANG`, `LC_ALL`/`LC_MESSAGES`/`LANG`).
- Claude Code plugin manifests, evaluation set and practice translations.
- SKILL.md section for building a file from translations the user already supplied (pass the JSON as given, never edit the output afterwards).
