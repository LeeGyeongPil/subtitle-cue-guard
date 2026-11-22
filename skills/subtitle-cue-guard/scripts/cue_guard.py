#!/usr/bin/env python3
"""subtitle-cue-guard: deterministic helpers around LLM subtitle translation.

Subcommands: extract (numbered cue text for the model), check (verify a translation
against the source), assemble (put translated text back onto the original blocks),
retime (frame-rate conversion, shifting, minimum duration/gap).

Standard library only. Exit codes: 0 ok, 1 integrity problems, 2 input or usage error.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import statistics
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable, Optional

TOOL = "subtitle-cue-guard"
SCHEMA = 1
ENV_LANG = "SUBTITLE_CUE_GUARD_LANG"

# --------------------------------------------------------------------------- messages

MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "prefix.error": "error:",
        "prefix.hint": "  hint:",
        "err.timing": "{prefix} {file}:{line}: invalid timing line",
        "err.timing.hint": "write cue times as HH:MM:SS,mmm --> HH:MM:SS,mmm (WebVTT: HH:MM:SS.mmm); fix that line and run again",
        "err.json": "{prefix} {file}: not valid JSON ({detail})",
        "err.json.hint": "save the model reply as a JSON object like {\"1\": \"text\"} without extra prose",
        "err.nocues": "{prefix} {file}: no cues found",
        "err.nocues.hint": "pass an .srt or .vtt file that contains at least one timing line",
        "err.target": "{prefix} unknown target language '{lang}' (use --profile or --cps/--line-width/--max-lines)",
        "err.fps": "{prefix} --fps expects SRC:DST like 23.976:25",
        "err.read": "{prefix} {file}: cannot read file ({detail})",
        "err.read.hint": "check the path and permissions",
        "err.encoding": "{prefix} {file}: not valid UTF-8",
        "err.encoding.hint": "convert the file to UTF-8 first (for example with iconv -f CP949 -t UTF-8)",
        "err.write": "{prefix} {file}: cannot write file ({detail})",
        "err.tr_shape": "{prefix} {file}: translations must be an object {{\"id\": \"text\"}} or an array of {{\"id\", \"text\"}} objects",
        "err.tr_value": "{prefix} {file}: translation for id '{id}' is not a string",
        "err.unknown_id": "{prefix} unknown cue id '{id}' (the source has ids 1..{n})",
        "err.ids": "{prefix} --only expects ids like 3,4,7-9",
        "err.retry_report": "{prefix} {file}: no 'retry' list found",
        "err.retry_report.hint": "pass the JSON report written by the check command",
        "err.profile": "{prefix} {file}: invalid profile ({detail})",
        "err.profile.hint": "allowed keys: cps, line_width, max_lines, width_mode (eaw|count), cps_spaces, script",
        "err.same_path": "{prefix} output path {file} is also an input file",
        "err.same_path.hint": "choose a new output file so the original is never overwritten",
        "err.value": "{prefix} invalid value for {opt}: {detail}",
        "err.shift": "{prefix} --shift expects a value like +1.5s, -2s or 300ms",
        "err.shift.hint": "write it as --shift=-2s when the value is negative",
        "err.nothing": "{prefix} retime needs at least one of --fps, --shift, --min-duration, --min-gap",
        "err.no_translation": "{prefix} no translation file given",
        "wrote": "wrote {file}",
        "check.header": "check: target {target}, {source} source cues, {translated} translated",
        "check.cols": "id  severity  code              detail",
        "check.ok": "no problems found",
        "check.retry": "retry: {ids}",
        "check.noretry": "retry: (none)",
        "check.source": "source notes:",
        "check.readability_skipped": "readability limits skipped for this language (pass --cps/--line-width/--max-lines to check them)",
        "extract.summary": "{cues} cues in {batches} batch(es), target {target}",
        "assemble.written": "assembled {cues} cues into {file}",
        "assemble.fallback": "kept the source text for cues: {ids}",
        "assemble.refused": "nothing written: fix or retranslate cues {ids} (or use --fallback source)",
        "assemble.refused_other": "nothing written: the translation does not match the source structure",
        "retime.summary": "retimed {changed} of {cues} cues into {file}",
        "retime.clamped": "Cue {id}: start time went below zero and was set to 0.",
        "issue.missing": "Cue {id} is missing from the translation.",
        "issue.unexpected_id": "The translation has id {id} but the source has no such cue.",
        "issue.empty": "The translation of cue {id} has no visible text.",
        "issue.untranslated.same": "Cue {id} is identical to the source text.",
        "issue.untranslated.script": "Cue {id} contains no characters of the target language script.",
        "issue.kept_as_is": "Cue {id} was kept as is (a single word or no letters).",
        "issue.tag_mismatch": "Formatting tags differ: source {source}, translation {translation}.",
        "issue.number_mismatch": "Numbers of the source are missing in the translation: {missing}.",
        "issue.shift_suspect": "Cue {id} contains {numbers}, which belongs to neighbouring cue {neighbors}; the content may have shifted.",
        "issue.merge_suspect.sentences": "Cue {id} may contain the next cue: sentences {source_sentences} -> {translation_sentences}, length ratio {ratio} against a median of {median}.",
        "issue.merge_suspect.next_empty": "Cue {id} may have swallowed the next cue (which is empty): length ratio {ratio} against a median of {median}.",
        "issue.cps": "Reading speed {value} characters per second exceeds {limit}.",
        "issue.too_many_lines": "{value} lines exceed the maximum of {limit}.",
        "issue.line_width": "Line width {value} exceeds {limit}.",
        "issue.overlap": "Source cue {id} overlaps the next cue.",
        "issue.out_of_order": "Source cue {id} starts before the previous cue.",
        "issue.nonpositive_duration": "Source cue {id} has zero or negative duration.",
        "issue.stray_block": "Source line {line} starts a block without a timing line; it is kept as is.",
        "help.description": "Deterministic helpers for translating SRT/WebVTT subtitles with an LLM: the model only sees numbered text, scripts keep timing and structure.",
        "help.lang": "screen language: en or ko (default: SUBTITLE_CUE_GUARD_LANG, then LC_ALL/LC_MESSAGES/LANG)",
        "help.format": "output format: json (default) or text",
        "help.output": "write the result to this file instead of standard output",
        "help.extract": "write numbered cue text and budgets for the model to translate",
        "help.check": "verify translations against the source and list the cue ids to retranslate",
        "help.assemble": "put the translated text onto the original cue blocks",
        "help.retime": "change frame rate, shift times, enforce minimum duration or gap",
        "help.src": "source subtitle file (.srt or .vtt)",
        "help.tr": "translation: JSON object, JSON array, or a translated .srt/.vtt; later files overwrite earlier ones",
        "help.target": "target language code, for example ko or en",
        "help.batch": "maximum cues per batch (default 40)",
        "help.gap": "close a batch early at a pause of at least this many seconds (0 disables; default 3.0)",
        "help.keep_tags": "send formatting tags as they are instead of numbered placeholders",
        "help.only": "only these cue ids, for example 3,4,7-9",
        "help.retry_from": "only the cue ids in the retry list of this check report",
        "help.context": "read-only neighbour cues to add around each retry batch (default 0)",
        "help.profile": "JSON file that defines or overrides the language profile",
        "help.cps": "maximum characters per second (overrides the profile)",
        "help.line_width": "maximum line width (overrides the profile)",
        "help.max_lines": "maximum lines per cue (overrides the profile)",
        "help.no_retry_readability": "report reading speed and line limits but do not add them to the retry list",
        "help.merge_ratio": "length ratio factor that marks a merge when sentences increased (default 1.8)",
        "help.merge_ratio_next": "length ratio factor that marks a merge when the next cue is empty (default 1.5)",
        "help.assemble_out": "output subtitle file (required)",
        "help.fallback": "keep the source text for cues that fail instead of refusing (value: source)",
        "help.bilingual": "write the source text first and the translation below it",
        "help.renumber": "renumber SRT cues 1..n",
        "help.report": "also write the check report (with the fallback list) to this file",
        "help.assemble_target": "target language code, enables the script check (optional)",
        "help.fps": "frame rate conversion SRC:DST, for example 23.976:25",
        "help.shift": "shift all times, for example +1.5s, -2s, 300ms (use --shift=-2s for negatives)",
        "help.min_duration": "minimum cue duration in seconds",
        "help.min_gap": "minimum gap between cues in seconds",
        "help.retime_out": "output subtitle file (required)",
    },
    "ko": {
        "prefix.error": "오류:",
        "prefix.hint": "  힌트:",
        "err.timing": "{prefix} {file}:{line}: 시간 코드 줄을 읽을 수 없습니다",
        "err.timing.hint": "큐 시간은 HH:MM:SS,mmm --> HH:MM:SS,mmm 형식으로 쓰세요(WebVTT 는 HH:MM:SS.mmm). 그 줄을 고치고 다시 실행하세요",
        "err.json": "{prefix} {file}: JSON 형식이 아닙니다 ({detail})",
        "err.json.hint": "모델 응답을 {\"1\": \"번역문\"} 같은 JSON 객체만 남겨 저장하세요(설명 문장 제외)",
        "err.nocues": "{prefix} {file}: 자막 큐가 없습니다",
        "err.nocues.hint": "시간 코드 줄이 하나 이상 있는 .srt 또는 .vtt 파일을 넘기세요",
        "err.target": "{prefix} 알 수 없는 목표 언어 '{lang}' (--profile 이나 --cps/--line-width/--max-lines 를 지정하세요)",
        "err.fps": "{prefix} --fps 는 23.976:25 같은 SRC:DST 형식이어야 합니다",
        "err.read": "{prefix} {file}: 파일을 읽을 수 없습니다 ({detail})",
        "err.read.hint": "경로와 권한을 확인하세요",
        "err.encoding": "{prefix} {file}: UTF-8 이 아닙니다",
        "err.encoding.hint": "먼저 UTF-8 로 변환하세요(예: iconv -f CP949 -t UTF-8)",
        "err.write": "{prefix} {file}: 파일을 쓸 수 없습니다 ({detail})",
        "err.tr_shape": "{prefix} {file}: 번역은 {{\"id\": \"번역문\"}} 객체이거나 {{\"id\", \"text\"}} 객체의 배열이어야 합니다",
        "err.tr_value": "{prefix} {file}: id '{id}' 의 번역이 문자열이 아닙니다",
        "err.unknown_id": "{prefix} 알 수 없는 큐 id '{id}' (원본의 id 는 1..{n})",
        "err.ids": "{prefix} --only 는 3,4,7-9 같은 id 목록이어야 합니다",
        "err.retry_report": "{prefix} {file}: 'retry' 목록이 없습니다",
        "err.retry_report.hint": "check 명령이 쓴 JSON 보고서를 넘기세요",
        "err.profile": "{prefix} {file}: 프로필이 올바르지 않습니다 ({detail})",
        "err.profile.hint": "허용 키: cps, line_width, max_lines, width_mode (eaw|count), cps_spaces, script",
        "err.same_path": "{prefix} 출력 경로 {file} 이(가) 입력 파일과 같습니다",
        "err.same_path.hint": "원본을 덮어쓰지 않도록 새 출력 파일을 지정하세요",
        "err.value": "{prefix} {opt} 값이 올바르지 않습니다: {detail}",
        "err.shift": "{prefix} --shift 는 +1.5s, -2s, 300ms 같은 값이어야 합니다",
        "err.shift.hint": "음수는 --shift=-2s 처럼 등호로 붙여 쓰세요",
        "err.nothing": "{prefix} retime 은 --fps, --shift, --min-duration, --min-gap 중 하나 이상이 필요합니다",
        "err.no_translation": "{prefix} 번역 파일이 없습니다",
        "wrote": "{file} 에 저장했습니다",
        "check.header": "검사: 목표 {target}, 원본 {source}개 큐, 번역 {translated}개",
        "check.cols": "id  등급      코드              내용",
        "check.ok": "문제가 없습니다",
        "check.retry": "다시 번역: {ids}",
        "check.noretry": "다시 번역: (없음)",
        "check.source": "원본 참고 사항:",
        "check.readability_skipped": "이 언어는 가독성 한도를 건너뜁니다(--cps/--line-width/--max-lines 를 주면 검사합니다)",
        "extract.summary": "큐 {cues}개, 배치 {batches}개, 목표 {target}",
        "assemble.written": "큐 {cues}개를 {file} 로 조립했습니다",
        "assemble.fallback": "원문을 유지한 큐: {ids}",
        "assemble.refused": "저장하지 않았습니다: 큐 {ids} 을(를) 고치거나 다시 번역하세요(또는 --fallback source)",
        "assemble.refused_other": "저장하지 않았습니다: 번역이 원본 구조와 맞지 않습니다",
        "retime.summary": "큐 {cues}개 중 {changed}개의 시간을 바꿔 {file} 에 저장했습니다",
        "retime.clamped": "큐 {id}: 시작 시각이 0 아래로 내려가 0 으로 맞췄습니다.",
        "issue.missing": "큐 {id} 이(가) 번역에 없습니다.",
        "issue.unexpected_id": "번역에 id {id} 이(가) 있지만 원본에는 그런 큐가 없습니다.",
        "issue.empty": "큐 {id} 의 번역에 보이는 글자가 없습니다.",
        "issue.untranslated.same": "큐 {id} 이(가) 원문과 같습니다.",
        "issue.untranslated.script": "큐 {id} 에 목표 언어 문자가 없습니다.",
        "issue.kept_as_is": "큐 {id} 은(는) 그대로 두었습니다(한 단어이거나 글자가 없음).",
        "issue.tag_mismatch": "서식 태그가 다릅니다: 원본 {source}, 번역 {translation}.",
        "issue.number_mismatch": "원본의 숫자가 번역에 없습니다: {missing}.",
        "issue.shift_suspect": "큐 {id} 에 이웃 큐 {neighbors} 의 숫자 {numbers} 이(가) 들어 있습니다. 내용이 밀렸을 수 있습니다.",
        "issue.merge_suspect.sentences": "큐 {id} 에 다음 큐 내용이 합쳐졌을 수 있습니다: 문장 수 {source_sentences} -> {translation_sentences}, 길이 비율 {ratio} (중앙값 {median}).",
        "issue.merge_suspect.next_empty": "큐 {id} 이(가) 비어 있는 다음 큐를 삼켰을 수 있습니다: 길이 비율 {ratio} (중앙값 {median}).",
        "issue.cps": "초당 {value}자로 한도 {limit} 을(를) 넘습니다.",
        "issue.too_many_lines": "{value}줄로 최대 {limit}줄을 넘습니다.",
        "issue.line_width": "줄 폭 {value} 이(가) 한도 {limit} 을(를) 넘습니다.",
        "issue.overlap": "원본 큐 {id} 이(가) 다음 큐와 겹칩니다.",
        "issue.out_of_order": "원본 큐 {id} 이(가) 이전 큐보다 먼저 시작합니다.",
        "issue.nonpositive_duration": "원본 큐 {id} 의 표시 시간이 0 이하입니다.",
        "issue.stray_block": "원본 {line}번째 줄은 시간 코드 줄이 없는 블록이라 그대로 둡니다.",
        "help.description": "LLM 으로 SRT/WebVTT 자막을 번역할 때 쓰는 결정적 도우미: 모델은 번호 붙은 텍스트만 보고, 시간과 구조는 스크립트가 지킵니다.",
        "help.lang": "화면 언어: en 또는 ko (기본: SUBTITLE_CUE_GUARD_LANG, 그다음 LC_ALL/LC_MESSAGES/LANG)",
        "help.format": "출력 형식: json(기본) 또는 text",
        "help.output": "표준 출력 대신 이 파일에 결과를 저장",
        "help.extract": "모델이 번역할 번호 붙은 큐 텍스트와 글자 예산을 만든다",
        "help.check": "번역을 원본과 대조하고 다시 번역할 큐 id 를 알려 준다",
        "help.assemble": "번역문을 원본 큐 블록에 끼워 넣는다",
        "help.retime": "프레임레이트 변환, 시간 이동, 최소 표시 시간·간격 보정",
        "help.src": "원본 자막 파일(.srt 또는 .vtt)",
        "help.tr": "번역: JSON 객체, JSON 배열, 또는 번역된 .srt/.vtt (뒤 파일이 앞 파일을 덮어씀)",
        "help.target": "목표 언어 코드(예: ko, en)",
        "help.batch": "배치당 최대 큐 수(기본 40)",
        "help.gap": "이 초 이상 쉬는 곳에서 배치를 일찍 끊음(0 이면 끔, 기본 3.0)",
        "help.keep_tags": "서식 태그를 자리표시자 없이 그대로 보냄",
        "help.only": "이 큐 id 만(예: 3,4,7-9)",
        "help.retry_from": "이 check 보고서의 retry 목록에 있는 큐만",
        "help.context": "재시도 배치 주변에 읽기 전용으로 덧붙일 이웃 큐 수(기본 0)",
        "help.profile": "언어 프로필을 정의하거나 덮어쓰는 JSON 파일",
        "help.cps": "초당 최대 글자 수(프로필보다 우선)",
        "help.line_width": "최대 줄 폭(프로필보다 우선)",
        "help.max_lines": "큐당 최대 줄 수(프로필보다 우선)",
        "help.no_retry_readability": "읽기 속도·줄 한도는 보고하되 재시도 목록에는 넣지 않음",
        "help.merge_ratio": "문장 수가 늘었을 때 병합으로 보는 길이 비율 배수(기본 1.8)",
        "help.merge_ratio_next": "다음 큐가 비었을 때 병합으로 보는 길이 비율 배수(기본 1.5)",
        "help.assemble_out": "출력 자막 파일(필수)",
        "help.fallback": "실패한 큐는 거부하는 대신 원문을 유지(값: source)",
        "help.bilingual": "원문을 먼저, 번역을 그 아래에 쓴다",
        "help.renumber": "SRT 큐 번호를 1..n 으로 다시 매긴다",
        "help.report": "check 보고서(fallback 목록 포함)를 이 파일에도 저장",
        "help.assemble_target": "목표 언어 코드, 문자 체계 검사를 켠다(선택)",
        "help.fps": "프레임레이트 변환 SRC:DST (예: 23.976:25)",
        "help.shift": "모든 시간을 이동(예: +1.5s, -2s, 300ms, 음수는 --shift=-2s)",
        "help.min_duration": "큐 최소 표시 시간(초)",
        "help.min_gap": "큐 사이 최소 간격(초)",
        "help.retime_out": "출력 자막 파일(필수)",
    },
}


def resolve_lang(cli_value: Optional[str], environ: "os._Environ[str] | dict[str, str]") -> str:
    """Screen language: --lang > SUBTITLE_CUE_GUARD_LANG > LC_ALL > LC_MESSAGES > LANG."""
    candidates = [cli_value, environ.get(ENV_LANG), environ.get("LC_ALL"),
                  environ.get("LC_MESSAGES"), environ.get("LANG")]
    for value in candidates:
        if value:
            return "ko" if value.lower().startswith("ko") else "en"
    return "en"


class GuardError(Exception):
    """Input or usage problem (exit code 2). Carries a message key and parameters."""

    def __init__(self, key: str, **params: Any) -> None:
        super().__init__(key)
        self.key = key
        self.params = params

    def text(self, lang: str) -> str:
        table = MESSAGES[lang]
        out = table[self.key].format(prefix=table["prefix.error"], **self.params)
        hint = table.get(self.key + ".hint")
        if hint:
            out += "\n" + table["prefix.hint"] + " " + hint
        return out


def tr_msg(lang: str, key: str, **params: Any) -> str:
    return MESSAGES[lang][key].format(**params)


# --------------------------------------------------------------------------- parsing

LINE_RE = re.compile(r"[^\r\n]*(?:\r\n|\n|\r)|[^\r\n]+")
_T = r"(?:(\d+):)?(\d{1,2}):(\d{2})([,.])(\d{1,3})"
TIMING_RE = re.compile(rf"^\s*{_T}\s*-->\s*{_T}(.*)$")
TIMING_LIKE_RE = re.compile(r"^\s*(?:\d+:)?\d{1,2}:\d{2}[,.]\d")
BLOCK_KIND_RE = re.compile(r"^(NOTE|STYLE|REGION)(\s|$)")
TAG_RE = re.compile(r"</?[A-Za-z][^<>]*>|<\d{1,2}:\d{2}[\d:.]*>|\{\\[^}]*\}")
PH_RE = re.compile(r"⟦\s*(\d+)\s*⟧")


@dataclass
class Cue:
    id: str
    timing_idx: int
    ident_idx: Optional[int]
    text_start: int
    text_end: int
    start: int
    end: int
    start_sep: str
    end_sep: str
    rest: str
    text: str


@dataclass
class Subtitle:
    fmt: str
    bom: bool
    lines: list[tuple[str, str]]
    cues: list[Cue]
    stray: list[int] = field(default_factory=list)
    name: str = ""

    def render(self, edits: list[tuple[int, int, list[tuple[str, str]]]]) -> str:
        out: list[tuple[str, str]] = []
        pos = 0
        for s, e, new in sorted(edits, key=lambda x: (x[0], x[1])):
            out.extend(self.lines[pos:s])
            out.extend(new)
            pos = e
        out.extend(self.lines[pos:])
        eol = next((e for _, e in self.lines if e), "\n")
        text = "".join(c + (e if e or i == len(out) - 1 else eol) for i, (c, e) in enumerate(out))
        return ("﻿" if self.bom else "") + text


def to_ms(h: Optional[str], m: str, s: str, frac: str) -> int:
    return ((int(h or 0) * 60 + int(m)) * 60 + int(s)) * 1000 + int(frac.ljust(3, "0"))


def fmt_time(ms: int, sep: str, with_hours: bool = True) -> str:
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, milli = divmod(rem, 1000)
    if with_hours or h:
        return f"{h:02d}:{m:02d}:{s:02d}{sep}{milli:03d}"
    return f"{m:02d}:{s:02d}{sep}{milli:03d}"


def parse_subtitle(text: str, name: str) -> Subtitle:
    bom = text.startswith("﻿")
    if bom:
        text = text[1:]
    lines: list[tuple[str, str]] = []
    for raw in LINE_RE.findall(text):
        if raw.endswith("\r\n"):
            lines.append((raw[:-2], "\r\n"))
        elif raw.endswith(("\n", "\r")):
            lines.append((raw[:-1], raw[-1]))
        else:
            lines.append((raw, ""))
    fmt = "vtt" if lines and lines[0][0].strip().startswith("WEBVTT") else "srt"
    sub = Subtitle(fmt, bom, lines, [], [], name)
    i, n = 0, len(lines)
    first_block = True
    while i < n:
        if not lines[i][0].strip():
            i += 1
            continue
        j = i
        while j < n and lines[j][0].strip():
            j += 1
        block_start, block_end = i, j
        i = j
        is_first, first_block = first_block, False
        if fmt == "vtt":
            if is_first and lines[block_start][0].strip().startswith("WEBVTT"):
                continue
            if BLOCK_KIND_RE.match(lines[block_start][0]):
                continue
        k = next((k for k in (0, 1) if block_start + k < block_end
                  and ("-->" in lines[block_start + k][0] or TIMING_LIKE_RE.match(lines[block_start + k][0]))), None)
        if k is None:
            sub.stray.append(block_start + 1)
            continue
        t_idx = block_start + k
        m = TIMING_RE.match(lines[t_idx][0])
        if not m:
            raise GuardError("err.timing", file=name, line=t_idx + 1)
        g = m.groups()
        cue = Cue(
            id=str(len(sub.cues) + 1), timing_idx=t_idx, ident_idx=block_start if k == 1 else None,
            text_start=t_idx + 1, text_end=block_end,
            start=to_ms(g[0], g[1], g[2], g[4]), end=to_ms(g[5], g[6], g[7], g[9]),
            start_sep=g[3], end_sep=g[8], rest=g[10],
            text="\n".join(c for c, _ in lines[t_idx + 1:block_end]),
        )
        sub.cues.append(cue)
    return sub


def read_text(path: str) -> str:
    try:
        data = Path(path).read_bytes()
    except OSError as e:
        raise GuardError("err.read", file=path, detail=e.strerror or str(e)) from None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise GuardError("err.encoding", file=path) from None


def load_subtitle(path: str) -> Subtitle:
    sub = parse_subtitle(read_text(path), path)
    if not sub.cues:
        raise GuardError("err.nocues", file=path)
    return sub


# --------------------------------------------------------------------------- text helpers

def tags_of(text: str) -> list[str]:
    return TAG_RE.findall(text)


def to_placeholders(text: str) -> str:
    counter = iter(range(1, 10_000))
    return TAG_RE.sub(lambda _m: f"⟦{next(counter)}⟧", text)


def restore_placeholders(text: str, tags: list[str]) -> tuple[str, list[str]]:
    unknown: list[str] = []

    def sub(m: "re.Match[str]") -> str:
        n = int(m.group(1))
        if 1 <= n <= len(tags):
            return tags[n - 1]
        unknown.append(m.group(0))
        return m.group(0)

    return PH_RE.sub(sub, text), unknown


def visible(text: str) -> str:
    return PH_RE.sub("", TAG_RE.sub("", text))


def normalize_translation(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("-->", "->")
    return "\n".join(ln.strip() for ln in text.split("\n") if ln.strip())


def numbers_of(text: str) -> Counter:
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"(?<=\d),(?=\d)", "", text)
    return Counter(re.findall(r"\d+(?:\.\d+)?", text))


def sentence_count(text: str) -> int:
    return len(re.findall(r"[.?!。？！…]+(?!\d)", text))


def size_of(text: str) -> int:
    return len(re.sub(r"\s+", "", text))


def display_width(line: str, mode: str) -> float:
    if mode == "count":
        return float(len(line))
    total = 0.0
    for ch in line:
        if unicodedata.combining(ch):
            continue
        total += 1.0 if unicodedata.east_asian_width(ch) in "WF" else 0.5
    return total


def has_script(text: str, script: str) -> bool:
    for ch in text:
        o = ord(ch)
        if script == "hangul" and (0xAC00 <= o <= 0xD7A3 or 0x1100 <= o <= 0x11FF or 0x3130 <= o <= 0x318F):
            return True
        if script in ("kana_han", "han") and (0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF or 0xF900 <= o <= 0xFAFF):
            return True
        if script == "kana_han" and (0x3040 <= o <= 0x30FF or 0xFF66 <= o <= 0xFF9F):
            return True
    return False


# --------------------------------------------------------------------------- profiles

DEFAULT_PROFILE: dict[str, Any] = {"cps": None, "line_width": None, "max_lines": None,
                                   "width_mode": "count", "cps_spaces": True, "script": "none"}
BUILTIN_PROFILES: dict[str, dict[str, Any]] = {
    "ko": {"cps": 12, "line_width": 16, "max_lines": 2, "width_mode": "eaw", "cps_spaces": False, "script": "hangul"},
    "en": {"cps": 20, "line_width": 42, "max_lines": 2, "width_mode": "count", "cps_spaces": True, "script": "none"},
    "ja": {**DEFAULT_PROFILE, "width_mode": "eaw", "cps_spaces": False, "script": "kana_han"},
    "zh": {**DEFAULT_PROFILE, "width_mode": "eaw", "cps_spaces": False, "script": "han"},
}
# Languages accepted without limits: only "identical to the source" is checked.
OTHER_LANGS = set("es fr de it pt nl sv da no nb fi pl cs sk sl hu ro bg el tr id ms vi tl ru uk sr hr he ar fa hi bn ta th".split())
PROFILE_KEYS = {"cps", "line_width", "max_lines", "width_mode", "cps_spaces", "script"}


def lang_code(target: str) -> str:
    return target.lower().replace("_", "-").split("-")[0]


def load_profile_file(path: str) -> dict[str, Any]:
    try:
        data = json.loads(read_text(path).lstrip("﻿"))
    except json.JSONDecodeError as e:
        raise GuardError("err.profile", file=path, detail=str(e)) from None
    if not isinstance(data, dict) or set(data) - PROFILE_KEYS:
        raise GuardError("err.profile", file=path, detail="unknown or missing keys")
    for key in ("cps", "line_width"):
        v = data.get(key)
        if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0):
            raise GuardError("err.profile", file=path, detail=f"{key} must be a positive number")
    v = data.get("max_lines")
    if v is not None and (isinstance(v, bool) or not isinstance(v, int) or v < 1):
        raise GuardError("err.profile", file=path, detail="max_lines must be a positive integer")
    if data.get("width_mode", "count") not in ("eaw", "count"):
        raise GuardError("err.profile", file=path, detail="width_mode must be eaw or count")
    if data.get("script", "none") not in ("hangul", "kana_han", "han", "none"):
        raise GuardError("err.profile", file=path, detail="script must be hangul, kana_han, han or none")
    if "cps_spaces" in data and not isinstance(data["cps_spaces"], bool):
        raise GuardError("err.profile", file=path, detail="cps_spaces must be true or false")
    return data


def resolve_profile(target: Optional[str], profile_file: Optional[str] = None, cps: Optional[float] = None,
                    line_width: Optional[float] = None, max_lines: Optional[int] = None,
                    allow_unknown: bool = False) -> dict[str, Any]:
    code = lang_code(target or "")
    base: Optional[dict[str, Any]] = None
    if code in BUILTIN_PROFILES:
        base = dict(BUILTIN_PROFILES[code])
    elif code in OTHER_LANGS:
        base = dict(DEFAULT_PROFILE)
    if profile_file:
        base = {**(base or DEFAULT_PROFILE), **load_profile_file(profile_file)}
    flags = {"cps": cps, "line_width": line_width, "max_lines": max_lines}
    if base is None:
        if all(v is not None for v in flags.values()) or allow_unknown:
            base = dict(DEFAULT_PROFILE)
        else:
            raise GuardError("err.target", lang=target)
    for key, v in flags.items():
        if v is not None:
            base[key] = v
    return base


# --------------------------------------------------------------------------- translations

def load_translations(paths: list[str]) -> dict[str, str]:
    merged: dict[str, str] = {}
    for path in paths:
        if path.lower().endswith((".srt", ".vtt")):
            sub = load_subtitle(path)
            for cue in sub.cues:
                merged[cue.id] = normalize_translation(cue.text)
            continue
        try:
            data = json.loads(read_text(path).lstrip("﻿"))
        except json.JSONDecodeError as e:
            raise GuardError("err.json", file=path, detail=e.msg + f" at line {e.lineno}") from None
        pairs: list[tuple[Any, Any]]
        if isinstance(data, dict):
            pairs = list(data.items())
        elif isinstance(data, list) and all(isinstance(x, dict) and "id" in x for x in data):
            pairs = []
            for x in data:
                value = x.get("text", x.get("translation"))
                pairs.append((x["id"], value))
        else:
            raise GuardError("err.tr_shape", file=path)
        for key, value in pairs:
            if not isinstance(value, str):
                raise GuardError("err.tr_value", file=path, id=key)
            merged[str(key)] = normalize_translation(value)
    return merged


# --------------------------------------------------------------------------- check

SEVERITY_ORDER = ["missing", "unexpected_id", "empty", "untranslated", "kept_as_is", "tag_mismatch",
                  "number_mismatch", "shift_suspect", "merge_suspect", "cps", "too_many_lines", "line_width"]
ERROR_CODES = {"missing", "unexpected_id", "empty", "untranslated", "tag_mismatch", "number_mismatch"}
READABILITY_CODES = {"cps", "too_many_lines", "line_width"}


def _id_key(cid: str) -> int:
    return int(cid) if cid.isdigit() else 10**9


def run_check(sub: Subtitle, tr: dict[str, str], target: str, profile: dict[str, Any], lang: str,
              retry_readability: bool = True, merge_ratio: float = 1.8, merge_ratio_next: float = 1.5) -> dict[str, Any]:
    cues = sub.cues
    order = [c.id for c in cues]
    by_id = {c.id: c for c in cues}
    issues: list[dict[str, Any]] = []
    retry: set[str] = set()

    def add(cid: str, code: str, severity: str, params: Optional[dict[str, Any]] = None,
            extra: Optional[dict[str, Any]] = None, key: Optional[str] = None, retryable: bool = True) -> None:
        params = {"id": cid, **(params or {})}
        issue: dict[str, Any] = {"id": cid, "code": code, "severity": severity}
        issue.update(extra or {})
        issue["message"] = tr_msg(lang, key or f"issue.{code}", **params)
        issues.append(issue)
        if retryable and severity != "info":
            retry.add(cid)

    src_tags = {cid: tags_of(by_id[cid].text) for cid in order}
    src_vis = {cid: visible(by_id[cid].text) for cid in order}
    src_nums = {cid: numbers_of(src_vis[cid]) for cid in order}

    for cid in sorted(set(tr) - set(order), key=_id_key):
        add(cid, "unexpected_id", "error", retryable=False)

    tr_vis: dict[str, str] = {}
    untranslated: set[str] = set()
    for cid in order:
        if cid not in tr:
            add(cid, "missing", "error")
            continue
        restored, unknown = restore_placeholders(tr[cid], src_tags[cid])
        vis = visible(restored)
        tr_vis[cid] = vis
        s_vis = src_vis[cid]
        if not vis.strip():
            if s_vis.strip():
                add(cid, "empty", "error")
            continue
        words = s_vis.split()
        has_letters = any(ch.isalpha() for ch in s_vis)
        same = " ".join(vis.split()).casefold() == " ".join(s_vis.split()).casefold()
        if len(words) <= 1 or not has_letters:
            if same:
                add(cid, "kept_as_is", "info")
        elif same:
            add(cid, "untranslated", "error", extra={"reason": "same_as_source"}, key="issue.untranslated.same")
            untranslated.add(cid)
        elif profile["script"] != "none" and not has_script(vis, profile["script"]):
            add(cid, "untranslated", "error", extra={"reason": "wrong_script"}, key="issue.untranslated.script")
            untranslated.add(cid)
        want = Counter(src_tags[cid])
        got = Counter(TAG_RE.findall(restored)) + Counter(unknown)
        if want != got:
            add(cid, "tag_mismatch", "error",
                {"source": " ".join(sorted(want.elements())) or "-", "translation": " ".join(sorted(got.elements())) or "-"},
                {"source": sorted(want.elements()), "translation": sorted(got.elements())})
        missing_nums = src_nums[cid] - numbers_of(vis)
        if missing_nums:
            add(cid, "number_mismatch", "error", {"missing": ", ".join(sorted(missing_nums.elements()))},
                {"missing": sorted(missing_nums.elements())})

    # shift: numbers that belong to a neighbouring source cue
    for idx, cid in enumerate(order):
        if cid not in tr_vis or not tr_vis[cid].strip():
            continue
        extra_nums = numbers_of(tr_vis[cid]) - src_nums[cid]
        neighbors: list[str] = []
        nums: list[str] = []
        for number in sorted(extra_nums):
            for nid in (order[idx - 1] if idx > 0 else None, order[idx + 1] if idx + 1 < len(order) else None):
                if nid and number in src_nums[nid]:
                    if nid not in neighbors:
                        neighbors.append(nid)
                    if number not in nums:
                        nums.append(number)
        if neighbors:
            add(cid, "shift_suspect", "suspect", {"numbers": ", ".join(nums), "neighbors": ", ".join(neighbors)},
                {"numbers": nums, "neighbors": neighbors})
            retry.update(neighbors)

    # merge: sentence count grew and the text is much longer than usual
    ratios: dict[str, float] = {}
    for cid in order:
        if cid in tr_vis and tr_vis[cid].strip() and cid not in untranslated and size_of(src_vis[cid]) >= 2:
            ratios[cid] = size_of(tr_vis[cid]) / size_of(src_vis[cid])
    if ratios:
        median = statistics.median(ratios.values())
        for idx, cid in enumerate(order):
            if cid not in ratios:
                continue
            ratio = ratios[cid]
            nxt = order[idx + 1] if idx + 1 < len(order) else None
            s_n, t_n = sentence_count(src_vis[cid]), sentence_count(tr_vis[cid])
            info = {"ratio": round(ratio, 2), "median": round(median, 2)}
            if t_n > s_n and ratio >= merge_ratio * median:
                add(cid, "merge_suspect", "suspect", {**info, "source_sentences": s_n, "translation_sentences": t_n},
                    {"reason": "sentences", **info}, key="issue.merge_suspect.sentences")
                if nxt:
                    retry.add(nxt)
            elif nxt and (nxt not in tr_vis or not tr_vis[nxt].strip()) and ratio >= merge_ratio_next * median:
                add(cid, "merge_suspect", "suspect", info, {"reason": "next_empty", **info},
                    key="issue.merge_suspect.next_empty")
                retry.add(nxt)

    # readability
    limits_active = any(profile[k] is not None for k in ("cps", "line_width", "max_lines"))
    for cid in order:
        vis = tr_vis.get(cid, "")
        if not vis.strip():
            continue
        cue = by_id[cid]
        lines = [ln for ln in vis.split("\n") if ln]
        dur = (cue.end - cue.start) / 1000
        if profile["cps"] is not None and dur > 0:
            chars = size_of(vis) if not profile["cps_spaces"] else len("".join(lines))
            value = round(chars / dur, 2)
            if value > profile["cps"]:
                add(cid, "cps", "warn", {"value": value, "limit": profile["cps"]},
                    {"value": value, "limit": profile["cps"]}, retryable=retry_readability)
        if profile["max_lines"] is not None and len(lines) > profile["max_lines"]:
            add(cid, "too_many_lines", "warn", {"value": len(lines), "limit": profile["max_lines"]},
                {"value": len(lines), "limit": profile["max_lines"]}, retryable=retry_readability)
        if profile["line_width"] is not None and lines:
            value = round(max(display_width(ln, profile["width_mode"]) for ln in lines), 2)
            if value > profile["line_width"]:
                add(cid, "line_width", "warn", {"value": value, "limit": profile["line_width"]},
                    {"value": value, "limit": profile["line_width"]}, retryable=retry_readability)

    rank = {code: i for i, code in enumerate(SEVERITY_ORDER)}
    issues.sort(key=lambda x: (_id_key(x["id"]), rank.get(x["code"], 99)))

    source_issues: list[dict[str, Any]] = []
    for i, cue in enumerate(cues):
        if cue.end <= cue.start:
            source_issues.append({"id": cue.id, "code": "nonpositive_duration", "severity": "source",
                                  "message": tr_msg(lang, "issue.nonpositive_duration", id=cue.id)})
        if i + 1 < len(cues):
            nxt = cues[i + 1]
            if nxt.start < cue.start:
                source_issues.append({"id": nxt.id, "code": "out_of_order", "severity": "source",
                                      "message": tr_msg(lang, "issue.out_of_order", id=nxt.id)})
            elif cue.end > nxt.start:
                source_issues.append({"id": cue.id, "code": "overlap", "severity": "source",
                                      "message": tr_msg(lang, "issue.overlap", id=cue.id)})
    for line in sub.stray:
        source_issues.append({"code": "stray_block", "severity": "source", "line": line,
                              "message": tr_msg(lang, "issue.stray_block", line=line)})

    def blocks_ok(x: dict[str, Any]) -> bool:
        if x["severity"] == "info":
            return False
        if x["severity"] == "warn" and x["code"] in READABILITY_CODES and not retry_readability:
            return False
        return True

    ok = not any(blocks_ok(x) for x in issues)
    return {
        "tool": TOOL, "schema": SCHEMA, "ok": ok, "target": target,
        "counts": {"source": len(order), "translated": len(tr)},
        "limits": {k: profile[k] for k in ("cps", "line_width", "max_lines", "width_mode")},
        "issues": issues, "retry": sorted(retry, key=_id_key),
        "readability": "checked" if limits_active else "skipped",
        "source_issues": source_issues,
    }


# --------------------------------------------------------------------------- output helpers

def _inline(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False)


def dumps(obj: Any, inline_at: int = 2, depth: int = 0) -> str:
    """JSON with one entry per line for the outer levels and inline leaves."""
    pad = "  " * (depth + 1)
    end = "  " * depth
    if depth >= inline_at:
        return _inline(obj)
    if isinstance(obj, dict) and obj:
        body = ",\n".join(f"{pad}{_inline(k)}: {dumps(v, inline_at, depth + 1)}" for k, v in obj.items())
        return "{\n" + body + "\n" + end + "}"
    if isinstance(obj, list) and obj and any(isinstance(x, (dict, list)) for x in obj):
        body = ",\n".join(pad + dumps(x, inline_at, depth + 1) for x in obj)
        return "[\n" + body + "\n" + end + "]"
    return _inline(obj)


def emit(text: str, output: Optional[str]) -> None:
    if output is None:
        sys.stdout.write(text if text.endswith("\n") else text + "\n")
        return
    write_file(output, text if text.endswith("\n") else text + "\n")


def write_file(path: str, text: str) -> None:
    try:
        Path(path).write_bytes(text.encode("utf-8"))
    except OSError as e:
        raise GuardError("err.write", file=path, detail=e.strerror or str(e)) from None


def guard_output(out: str, inputs: Iterable[str]) -> None:
    resolved = Path(out).resolve()
    for p in inputs:
        if Path(p).resolve() == resolved:
            raise GuardError("err.same_path", file=out)


def check_text(report: dict[str, Any], lang: str) -> str:
    lines = [tr_msg(lang, "check.header", target=report["target"], source=report["counts"]["source"],
                    translated=report["counts"]["translated"]), MESSAGES[lang]["check.cols"]]
    for x in report["issues"]:
        lines.append(f"{x['id']:<3} {x['severity']:<9} {x['code']:<17} {x['message']}")
    if not report["issues"]:
        lines.append(MESSAGES[lang]["check.ok"])
    if report["readability"] == "skipped":
        lines.append(MESSAGES[lang]["check.readability_skipped"])
    if report["source_issues"]:
        lines.append(MESSAGES[lang]["check.source"])
        lines.extend("  " + x["message"] for x in report["source_issues"])
    lines.append(tr_msg(lang, "check.retry", ids=", ".join(report["retry"])) if report["retry"]
                 else MESSAGES[lang]["check.noretry"])
    return "\n".join(lines)


# --------------------------------------------------------------------------- extract

REPLY_FORMAT = ("Return one JSON object {\"<id>\": \"<translation>\"} per batch. Keep every ⟦n⟧ placeholder. "
                "Use \\n for line breaks. Do not merge, split or skip ids.")
REPLY_FORMAT_KEEP = ("Return one JSON object {\"<id>\": \"<translation>\"} per batch. Keep every formatting tag exactly. "
                     "Use \\n for line breaks. Do not merge, split or skip ids.")


def parse_ids(spec: str, n: int) -> set[str]:
    ids: set[str] = set()
    for part in spec.split(","):
        part = part.strip()
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", part)
        if not m:
            raise GuardError("err.ids")
        a, b = int(m.group(1)), int(m.group(2) or m.group(1))
        if b < a:
            raise GuardError("err.ids")
        for i in range(a, b + 1):
            if not 1 <= i <= n:
                raise GuardError("err.unknown_id", id=i, n=n)
            ids.add(str(i))
    return ids


def make_batches(cues: list[Cue], size: int, gap_s: float) -> list[list[Cue]]:
    batches: list[list[Cue]] = []
    cur: list[Cue] = []
    for cue in cues:
        if cur:
            full = len(cur) >= size
            scene = gap_s > 0 and cue.start - cur[-1].end >= gap_s * 1000 and len(cur) >= math.ceil(size / 2)
            if full or scene:
                batches.append(cur)
                cur = []
        cur.append(cue)
    if cur:
        batches.append(cur)
    return batches


def build_extract(sub: Subtitle, target: str, profile: dict[str, Any], batch: int, gap: float, keep_tags: bool,
                  selected: Optional[set[str]], context: int, source_name: str) -> dict[str, Any]:
    cues = [c for c in sub.cues if selected is None or c.id in selected]
    ids_all = [c.id for c in sub.cues]

    def shown(cue: Cue) -> str:
        return cue.text if keep_tags else to_placeholders(cue.text)

    out_batches = []
    for n, group in enumerate(make_batches(cues, batch, gap), 1):
        entries = []
        for cue in group:
            seconds = round((cue.end - cue.start) / 1000, 3)
            entry: dict[str, Any] = {"id": cue.id, "text": shown(cue), "seconds": seconds,
                                     "max_chars": None, "max_width": None}
            if profile["cps"] is not None:
                entry["max_chars"] = int(Fraction(str(profile["cps"])) * (cue.end - cue.start) / 1000)
            if profile["line_width"] is not None and profile["max_lines"] is not None:
                entry["max_width"] = float(profile["line_width"] * profile["max_lines"])
            entries.append(entry)
        in_batch = {c.id for c in group}
        ctx_ids = sorted({j for c in group for j in range(int(c.id) - context, int(c.id) + context + 1)
                          if 1 <= j <= len(ids_all)} - {int(x) for x in in_batch})
        by_id = {c.id: c for c in sub.cues}
        out_batches.append({"n": n, "cues": entries,
                            "context": [{"id": str(j), "text": shown(by_id[str(j)])} for j in ctx_ids]})
    return {
        "tool": TOOL, "schema": SCHEMA, "source": source_name, "format": sub.fmt, "target": target,
        "limits": {"cps": profile["cps"], "line_width": profile["line_width"], "max_lines": profile["max_lines"],
                   "width_mode": profile["width_mode"]},
        "reply_format": REPLY_FORMAT_KEEP if keep_tags else REPLY_FORMAT,
        "batches": out_batches,
    }


# --------------------------------------------------------------------------- assemble

def text_edit(sub: Subtitle, cue: Cue, new_lines: list[str], bilingual: bool) -> tuple[int, int, list[tuple[str, str]]]:
    orig = sub.lines[cue.text_start:cue.text_end]
    timing_eol = sub.lines[cue.timing_idx][1] or "\n"
    contents = ([c for c, _ in orig] if bilingual else []) + new_lines
    last_eol = orig[-1][1] if orig else sub.lines[cue.timing_idx][1]
    new = [(c, timing_eol) for c in contents[:-1]] + [(contents[-1], last_eol)]
    return cue.text_start, cue.text_end, new


def build_assembly(sub: Subtitle, tr: dict[str, str], use_source: set[str], bilingual: bool, renumber: bool) -> str:
    edits: list[tuple[int, int, list[tuple[str, str]]]] = []
    for n, cue in enumerate(sub.cues, 1):
        if cue.id in tr and cue.id not in use_source:
            restored, _ = restore_placeholders(tr[cue.id], tags_of(cue.text))
            edits.append(text_edit(sub, cue, restored.split("\n"), bilingual))
        if renumber and sub.fmt == "srt":
            eol = sub.lines[cue.timing_idx][1] or "\n"
            if cue.ident_idx is not None:
                edits.append((cue.ident_idx, cue.ident_idx + 1, [(str(n), sub.lines[cue.ident_idx][1])]))
            else:
                edits.append((cue.timing_idx, cue.timing_idx, [(str(n), eol)]))
    return sub.render(edits)


# --------------------------------------------------------------------------- retime

def parse_fps(spec: str) -> tuple[Fraction, Fraction]:
    try:
        a, b = spec.split(":")
        fa, fb = Fraction(a.strip()), Fraction(b.strip())
    except (ValueError, ZeroDivisionError):
        raise GuardError("err.fps") from None
    if fa <= 0 or fb <= 0:
        raise GuardError("err.fps")
    return fa, fb


def parse_shift(spec: str) -> Fraction:
    m = re.fullmatch(r"([+-]?)(\d+(?:\.\d+)?)\s*(ms|s)?", spec.strip())
    if not m:
        raise GuardError("err.shift")
    value = Fraction(m.group(2)) * (1 if m.group(3) == "ms" else 1000)
    return -value if m.group(1) == "-" else value


def parse_seconds(opt: str, value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    try:
        f = Fraction(value)
    except (ValueError, ZeroDivisionError):
        raise GuardError("err.value", opt=opt, detail=f"'{value}' is not a number") from None
    if f < 0:
        raise GuardError("err.value", opt=opt, detail="must not be negative")
    return int(f * 1000)


def round_half_up(x: Fraction) -> int:
    return math.floor(x + Fraction(1, 2))


def retime_cues(sub: Subtitle, fps: Optional[tuple[Fraction, Fraction]], shift: Optional[Fraction],
                min_duration: Optional[int], min_gap: Optional[int]) -> tuple[list[tuple[int, int]], list[str]]:
    times: list[list[int]] = []
    clamped: list[str] = []
    for cue in sub.cues:
        s, e = Fraction(cue.start), Fraction(cue.end)
        if fps:
            s, e = s * fps[0] / fps[1], e * fps[0] / fps[1]
        if shift:
            s, e = s + shift, e + shift
        si, ei = round_half_up(s), round_half_up(e)
        if si < 0:
            clamped.append(cue.id)
            si = 0
        ei = max(ei, 0)
        times.append([si, ei])
    for i, t in enumerate(times):
        limit = times[i + 1][0] - (min_gap or 0) if i + 1 < len(times) else None
        if min_gap and limit is not None and t[1] > limit > t[0]:
            t[1] = limit
        if min_duration and t[1] - t[0] < min_duration:
            wanted = t[0] + min_duration
            t[1] = max(t[1], min(wanted, limit) if limit is not None else wanted)
    return [(a, b) for a, b in times], clamped


# --------------------------------------------------------------------------- commands

def _lang_of(args: argparse.Namespace) -> str:
    return args._lang


def cmd_extract(args: argparse.Namespace) -> int:
    lang = _lang_of(args)
    profile = resolve_profile(args.target, args.profile, args.cps, args.line_width, args.max_lines)
    selected: Optional[set[str]] = None
    sub = load_subtitle(args.src)
    n = len(sub.cues)
    if args.only is not None or args.retry_from is not None:
        selected = set()
        if args.only is not None:
            selected |= parse_ids(args.only, n)
        if args.retry_from is not None:
            try:
                report = json.loads(read_text(args.retry_from).lstrip("﻿"))
            except json.JSONDecodeError as e:
                raise GuardError("err.json", file=args.retry_from, detail=e.msg) from None
            if not isinstance(report, dict) or not isinstance(report.get("retry"), list):
                raise GuardError("err.retry_report", file=args.retry_from)
            for x in report["retry"]:
                selected |= parse_ids(str(x), n)
    for opt, val in (("--batch", args.batch), ("--gap", args.gap), ("--context", args.context)):
        if val < (1 if opt == "--batch" else 0):
            raise GuardError("err.value", opt=opt, detail="out of range")
    data = build_extract(sub, args.target, profile, args.batch, args.gap, args.keep_tags, selected, args.context, args.src)
    if args.format == "text":
        lines = [tr_msg(lang, "extract.summary", cues=sum(len(b["cues"]) for b in data["batches"]),
                        batches=len(data["batches"]), target=args.target)]
        for b in data["batches"]:
            lines.append(f"[batch {b['n']}]")
            lines.extend(f"{c['id']}: {c['text']}" for c in b["cues"])
        text = "\n".join(lines)
    else:
        text = dumps(data, inline_at=4)
    emit(text, args.output)
    if args.output:
        print(tr_msg(lang, "wrote", file=args.output))
    return 0


def _run_check(args: argparse.Namespace, lang: str) -> dict[str, Any]:
    profile = resolve_profile(args.target, args.profile, args.cps, args.line_width, args.max_lines)
    sub = load_subtitle(args.src)
    tr = load_translations(args.translations)
    return run_check(sub, tr, args.target, profile, lang, not args.no_retry_readability,
                     args.merge_ratio, args.merge_ratio_next)


def cmd_check(args: argparse.Namespace) -> int:
    lang = _lang_of(args)
    report = _run_check(args, lang)
    text = check_text(report, lang) if args.format == "text" else dumps(report, inline_at=2)
    emit(text, args.output)
    if args.output:
        print(tr_msg(lang, "wrote", file=args.output))
        if args.format != "text":
            print(tr_msg(lang, "check.retry", ids=", ".join(report["retry"])) if report["retry"]
                  else MESSAGES[lang]["check.ok"] if report["ok"] else MESSAGES[lang]["check.noretry"])
    return 0 if report["ok"] else 1


def cmd_assemble(args: argparse.Namespace) -> int:
    lang = _lang_of(args)
    guard_output(args.output, [args.src, *args.translations])
    guard_output(args.output, [])
    if args.report:
        guard_output(args.report, [args.src, *args.translations])
    profile = resolve_profile(args.target, None, None, None, None, allow_unknown=True)
    sub = load_subtitle(args.src)
    tr = load_translations(args.translations)
    report = run_check(sub, tr, args.target or "", profile, lang)
    structural = [x for x in report["issues"] if x["severity"] in ("error", "suspect") and x["code"] != "unexpected_id"]
    unexpected = [x for x in report["issues"] if x["code"] == "unexpected_id"]
    # cues that fall back to the source: everything that needs a retry except pure readability warnings
    strict = run_check(sub, tr, args.target or "", profile, lang, retry_readability=False)
    fallback_ids = list(strict["retry"])
    result: dict[str, Any] = {"tool": TOOL, "schema": SCHEMA, "ok": True, "written": False, "output": None,
                              "cues": len(sub.cues), "fallback": [], "retry": report["retry"]}
    refuse_ids = fallback_ids
    if args.fallback != "source" and (structural or unexpected):
        refuse_ids = fallback_ids or [x["id"] for x in unexpected]
        result["ok"] = False
        result["message"] = (tr_msg(lang, "assemble.refused", ids=", ".join(refuse_ids)) if refuse_ids
                             else MESSAGES[lang]["assemble.refused_other"])
    else:
        text = build_assembly(sub, tr, set(fallback_ids), args.bilingual, args.renumber)
        write_file(args.output, text)
        result.update(written=True, output=args.output, fallback=fallback_ids)
        result["message"] = tr_msg(lang, "assemble.written", cues=len(sub.cues), file=args.output)
        if fallback_ids:
            result["message"] += "; " + tr_msg(lang, "assemble.fallback", ids=", ".join(fallback_ids))
    if args.report:
        write_file(args.report, dumps({**report, "fallback": result["fallback"], "written": result["written"]}, 2))
    if args.format == "text":
        emit(result["message"], None)
    else:
        emit(dumps(result, 1), None)
    return 0 if result["ok"] else 1


def cmd_retime(args: argparse.Namespace) -> int:
    lang = _lang_of(args)
    fps = parse_fps(args.fps) if args.fps else None
    shift = parse_shift(args.shift) if args.shift else None
    min_duration = parse_seconds("--min-duration", args.min_duration)
    min_gap = parse_seconds("--min-gap", args.min_gap)
    if fps is None and shift is None and min_duration is None and min_gap is None:
        raise GuardError("err.nothing")
    guard_output(args.output, [args.src])
    sub = load_subtitle(args.src)
    times, clamped = retime_cues(sub, fps, shift, min_duration, min_gap)
    edits: list[tuple[int, int, list[tuple[str, str]]]] = []
    changed = 0
    for cue, (s, e) in zip(sub.cues, times):
        if (s, e) == (cue.start, cue.end):
            continue
        changed += 1
        has_hours = bool(re.match(r"^\s*\d+:\d{1,2}:\d{2}[,.]", sub.lines[cue.timing_idx][0])) or sub.fmt == "srt"
        line = f"{fmt_time(s, cue.start_sep, has_hours)} --> {fmt_time(e, cue.end_sep, has_hours)}{cue.rest}"
        edits.append((cue.timing_idx, cue.timing_idx + 1, [(line, sub.lines[cue.timing_idx][1])]))
    write_file(args.output, sub.render(edits))
    warnings = [{"id": cid, "code": "clamped_to_zero", "message": tr_msg(lang, "retime.clamped", id=cid)} for cid in clamped]
    summary = tr_msg(lang, "retime.summary", changed=changed, cues=len(sub.cues), file=args.output)
    if args.format == "text":
        print(summary)
        for w in warnings:
            print(w["message"])
    else:
        emit(dumps({"tool": TOOL, "schema": SCHEMA, "ok": True, "output": args.output, "cues": len(sub.cues),
                    "changed": changed, "warnings": warnings, "message": summary}, 1), None)
    return 0


# --------------------------------------------------------------------------- CLI

_KO_ARGPARSE = (
    (re.compile(r"the following arguments are required: (.+)"), r"다음 인자가 필요합니다: \1"),
    (re.compile(r"unrecognized arguments: (.+)"), r"알 수 없는 인자: \1"),
    (re.compile(r"argument (.+?): invalid choice: (.+?) \(choose from (.+)\)"), r"인자 \1: 올바르지 않은 선택 \2 (가능한 값: \3)"),
    (re.compile(r"argument (.+?): expected one argument"), r"인자 \1: 값이 하나 필요합니다"),
    (re.compile(r"argument (.+?): invalid .+? value: (.+)"), r"인자 \1: 올바르지 않은 값 \2"),
)


def _ko_argparse_message(message: str) -> str:
    """Translate the common argparse error sentences; unknown ones stay as-is."""
    for pattern, repl in _KO_ARGPARSE:
        if pattern.fullmatch(message):
            return pattern.sub(repl, message)
    return message


class LocalizedParser(argparse.ArgumentParser):
    error_prefix = "error:"

    def error(self, message: str) -> "Any":  # pragma: no cover - exercised through subprocess tests
        self.print_usage(sys.stderr)
        if self.error_prefix == MESSAGES["ko"]["prefix.error"]:
            message = _ko_argparse_message(message)
        self.exit(2, f"{self.error_prefix} {message}\n")


def build_parser(lang: str) -> argparse.ArgumentParser:
    h = MESSAGES[lang]
    LocalizedParser.error_prefix = h["prefix.error"]
    parser = LocalizedParser(prog="cue_guard.py", description=h["help.description"])
    parser.add_argument("--lang", choices=["en", "ko"], default=None, help=h["help.lang"])
    sp = parser.add_subparsers(dest="command", required=True, parser_class=LocalizedParser)

    def common(p: argparse.ArgumentParser, output_help: str = "help.output", required: bool = False) -> None:
        p.add_argument("--lang", choices=["en", "ko"], default=argparse.SUPPRESS, help=h["help.lang"])
        p.add_argument("--format", choices=["json", "text"], default="json", help=h["help.format"])
        p.add_argument("-o", "--output", required=required, default=None, help=h[output_help])

    def limits(p: argparse.ArgumentParser) -> None:
        p.add_argument("--profile", help=h["help.profile"])
        p.add_argument("--cps", type=float, help=h["help.cps"])
        p.add_argument("--line-width", type=float, help=h["help.line_width"])
        p.add_argument("--max-lines", type=int, help=h["help.max_lines"])

    p = sp.add_parser("extract", help=h["help.extract"], description=h["help.extract"])
    p.add_argument("src", help=h["help.src"])
    p.add_argument("--target", required=True, help=h["help.target"])
    p.add_argument("--batch", type=int, default=40, help=h["help.batch"])
    p.add_argument("--gap", type=float, default=3.0, help=h["help.gap"])
    p.add_argument("--keep-tags", action="store_true", help=h["help.keep_tags"])
    p.add_argument("--only", help=h["help.only"])
    p.add_argument("--retry-from", help=h["help.retry_from"])
    p.add_argument("--context", type=int, default=0, help=h["help.context"])
    limits(p)
    common(p)
    p.set_defaults(func=cmd_extract)

    p = sp.add_parser("check", help=h["help.check"], description=h["help.check"])
    p.add_argument("src", help=h["help.src"])
    p.add_argument("translations", nargs="+", metavar="tr", help=h["help.tr"])
    p.add_argument("--target", required=True, help=h["help.target"])
    limits(p)
    p.add_argument("--no-retry-readability", action="store_true", help=h["help.no_retry_readability"])
    p.add_argument("--merge-ratio", type=float, default=1.8, help=h["help.merge_ratio"])
    p.add_argument("--merge-ratio-next", type=float, default=1.5, help=h["help.merge_ratio_next"])
    common(p)
    p.set_defaults(func=cmd_check)

    p = sp.add_parser("assemble", help=h["help.assemble"], description=h["help.assemble"])
    p.add_argument("src", help=h["help.src"])
    p.add_argument("translations", nargs="+", metavar="tr", help=h["help.tr"])
    p.add_argument("--target", help=h["help.assemble_target"])
    p.add_argument("--fallback", choices=["source"], help=h["help.fallback"])
    p.add_argument("--bilingual", action="store_true", help=h["help.bilingual"])
    p.add_argument("--renumber", action="store_true", help=h["help.renumber"])
    p.add_argument("--report", help=h["help.report"])
    common(p, "help.assemble_out", required=True)
    p.set_defaults(func=cmd_assemble)

    p = sp.add_parser("retime", help=h["help.retime"], description=h["help.retime"])
    p.add_argument("src", help=h["help.src"])
    p.add_argument("--fps", help=h["help.fps"])
    p.add_argument("--shift", help=h["help.shift"])
    p.add_argument("--min-duration", help=h["help.min_duration"])
    p.add_argument("--min-gap", help=h["help.min_gap"])
    common(p, "help.retime_out", required=True)
    p.set_defaults(func=cmd_retime)
    return parser


def _preparse_lang(argv: list[str]) -> Optional[str]:
    for i, tok in enumerate(argv):
        if tok == "--lang" and i + 1 < len(argv):
            return argv[i + 1] if argv[i + 1] in ("en", "ko") else None
        if tok.startswith("--lang="):
            v = tok.split("=", 1)[1]
            return v if v in ("en", "ko") else None
    return None


def _glue_shift(argv: list[str]) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(argv):
        if argv[i] == "--shift" and i + 1 < len(argv) and argv[i + 1][:1] in "+-":
            out.append("--shift=" + argv[i + 1])
            i += 2
        else:
            out.append(argv[i])
            i += 1
    return out


def main(argv: Optional[list[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    args_list = _glue_shift(list(sys.argv[1:] if argv is None else argv))
    lang = resolve_lang(_preparse_lang(args_list), os.environ)
    parser = build_parser(lang)
    args = parser.parse_args(args_list)
    args._lang = args.lang or lang
    if args._lang != lang:
        lang = args._lang
    try:
        return args.func(args)
    except GuardError as e:
        print(e.text(lang), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
