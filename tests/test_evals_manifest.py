"""The evaluation set: composition, leak checks, and graders that really match the script's output."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

import pytest

from conftest import ROOT, cg

EVALS = ROOT / "evals"
NAME = "subtitle-cue-guard"


def cases(prefix: str):
    return sorted(d for d in EVALS.iterdir() if d.is_dir() and d.name.startswith(prefix))


def body(case: Path) -> str:
    return (case / "prompt.md").read_text(encoding="utf-8").split("---", 2)[2].strip()


def grader(path: Path) -> dict:
    text = path.read_text(encoding="utf-8").split("---", 2)[1]
    out = {}
    for line in text.strip().splitlines():
        key, _, value = line.partition(": ")
        out[key] = value.strip()
    if out.get("pattern", "").startswith("'"):
        out["pattern"] = out["pattern"][1:-1]
    return out


def test_eval_set_composition():
    trig = cases("trigger-")
    near = cases("notrigger-near-")
    notrig = cases("notrigger-")  # includes the near cases
    tasks = cases("task-")
    assert len(trig) >= 10 and len([c for c in trig if re.search(r"[가-힣]", body(c))]) >= 2
    assert len(notrig) >= 10 and len(near) >= 5
    assert len(tasks) >= 5 and len([c for c in tasks if c.name.startswith("task-error-")]) >= 1
    for case in trig:
        text = body(case)
        assert NAME not in text and not re.search(r"\bskill\b|스킬", text, re.I), case.name
        assert "tool: Skill" in (case / "graders" / "skill-fired.md").read_text()
    for case in notrig:
        assert "max: 0" in (case / "graders" / "skill-not-fired.md").read_text()
    for case in tasks:
        assert (EVALS / "fixtures" / case.name).is_dir(), case.name
        assert "with-only" in (case / "graders" / "script-ran.md").read_text()
        assert list((case / "graders").glob("value-*.md")), case.name


TASK_RUNS = {
    "task-cps-width": [["check", "sample.srt", "bad.ko.json", "--target", "ko", "--lang", "en", "-o", "report.json"]],
    "task-anchorless-merge": [["check", "sample.srt", "shifted.ko.json", "--target", "ko", "-o", "report.json"]],
    "task-vtt-bytes": [["assemble", "rich.vtt", "tr.json", "--target", "ko", "-o", "ko.vtt"]],
    "task-fps-retime": [["retime", "movie.srt", "--fps", "23.976:25", "--min-duration", "0.83",
                       "--min-gap", "0.083", "-o", "movie.25.srt"]],
    "task-retry-batch": [["extract", "talk.srt", "--target", "ko", "--retry-from", "report.json", "--context", "1",
                          "-o", "retry.json"]],
    "task-error-broken-srt": [["extract", "broken.srt", "--target", "ko", "-o", "batch.json"]],
}


VTT_SHA256 = "a5947894faf4c38e97fc74a6388bba5cb20b71e5de87b787cf275f60f7abeead"


def file_views(path: Path) -> dict[str, str]:
    """The same output file read the ways an evaluation harness might read it.

    `read_text` turns CRLF into LF, so file graders must not depend on line endings;
    byte-exactness (BOM, CRLF) is checked by the SHA-256 grader on the trace instead.
    """
    return {
        "bytes": path.read_bytes().decode("utf-8"),
        "read_text": path.read_text(encoding="utf-8"),
        "read_text_sig": path.read_text(encoding="utf-8-sig"),
    }


def trace_views(text: str) -> dict[str, str]:
    """The same trace as plain text and as a JSON-encoded transcript (quotes escaped, non-ASCII escaped or not)."""
    return {
        "plain": text,
        "json": json.dumps(text),
        "json_utf8": json.dumps(text, ensure_ascii=False),
    }


def all_graders():
    return sorted(EVALS.glob("*/graders/*.md"))


@pytest.mark.parametrize("path", all_graders(), ids=lambda p: f"{p.parent.parent.name}/{p.name}")
def test_patterns_survive_wrapping(path):
    """A harness may wrap or combine patterns; inline global flags like (?i) then stop compiling."""
    g = grader(path)
    if "pattern" not in g:
        return
    assert not re.search(r"\(\?[aiLmsux]+\)", g["pattern"]), f"{path}: inline global flag"
    re.compile(f"(?:{g['pattern']})")
    re.compile(f"(?m)(?:{g['pattern']})")


@pytest.mark.parametrize("name", sorted(TASK_RUNS))
def test_task_graders_match_real_output(name, tmp_path, cli, monkeypatch):
    work = tmp_path / name
    shutil.copytree(EVALS / "fixtures" / name, work)
    monkeypatch.chdir(work)
    trace = []
    for args in TASK_RUNS[name]:
        _, out, err = cli(*args)
        trace.append(out + err)
    if name == "task-vtt-bytes":
        # 프롬프트가 요구하는 대로 에이전트가 `shasum -a 256 ko.vtt` 를 돌렸을 때 trace 에 남는 줄
        trace.append(f"{hashlib.sha256((work / 'ko.vtt').read_bytes()).hexdigest()}  ko.vtt")
    trace_text = "\n".join(trace)
    graders = sorted((EVALS / name / "graders").glob("value-*.md"))
    assert graders
    for path in graders:
        g = grader(path)
        if g["target"] == "trace":
            # trace 는 평문일 수도, 따옴표가 \" 로 바뀐 JSON 기록일 수도 있다 — 둘 다 맞아야 한다
            for view, haystack in trace_views(trace_text).items():
                assert re.search(g["pattern"], haystack), f"{name}/{path.name} does not match the trace ({view})"
            continue
        match = re.search(r"path: ([^}]+)\}", g.get("target", ""))
        # 파일 채점은 하네스가 어떤 방식으로 읽어도(줄 끝 변환·BOM 제거) 같은 결과여야 한다
        for view, haystack in file_views(work / match.group(1).strip()).items():
            assert re.search(g["pattern"], haystack), f"{name}/{path.name} does not match ({view})"


def test_vtt_hash_grader_is_the_exact_output():
    """The hash grader pins the byte-exact output: BOM, CRLF, NOTE/STYLE/REGION and cue settings."""
    g = grader(EVALS / "task-vtt-bytes" / "graders" / "value-5.md")
    assert g["target"] == "trace" and VTT_SHA256 in g["pattern"]
    assert "SHA-256" in body(EVALS / "task-vtt-bytes")


def test_graders_reject_a_hand_edited_result(tmp_path, cli, monkeypatch):
    """Hand-made results must fail: NOTE dropped fails the file grader, CRLF/BOM/final newline lost fails the hash grader."""
    value1 = grader(EVALS / "task-vtt-bytes" / "graders" / "value-1.md")
    value5 = grader(EVALS / "task-vtt-bytes" / "graders" / "value-5.md")
    hand = "WEBVTT\n\nintro\n00:01.000 --> 00:03.500\n나는 그가 여기 있었다고\n"
    assert not re.search(value1["pattern"], hand)
    # 스크립트 없이 직접 만든 답(평범한 완료 보고)은 스크립트 결과 채점(value-3)에 걸리지 않는다
    value3 = grader(EVALS / "task-vtt-bytes" / "graders" / "value-3.md")
    baseline_reply = "I wrote ko.vtt and kept the NOTE, STYLE and REGION blocks. The file was written; true to the source."
    assert not re.search(value3["pattern"], baseline_reply)

    work = tmp_path / "vtt"
    shutil.copytree(EVALS / "fixtures" / "task-vtt-bytes", work)
    monkeypatch.chdir(work)
    cli("assemble", "rich.vtt", "tr.json", "--target", "ko", "-o", "ko.vtt")
    good = (work / "ko.vtt").read_bytes()
    assert hashlib.sha256(good).hexdigest() == VTT_SHA256
    resaved = {
        "crlf_to_lf": good.replace(b"\r\n", b"\n"),
        "bom_dropped": good.removeprefix(b"\xef\xbb\xbf"),
        "final_newline_dropped": good.rstrip(b"\r\n"),
    }
    for label, data in resaved.items():
        assert data != good, label
        assert not re.search(value5["pattern"], f"{hashlib.sha256(data).hexdigest()}  ko.vtt"), label
