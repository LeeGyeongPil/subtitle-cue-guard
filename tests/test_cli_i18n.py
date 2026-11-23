from __future__ import annotations

import json
import re
import subprocess
import sys

import pytest

from conftest import EX, FIX, SCRIPT, cg, child_env, jwrite, write


def test_message_keys_equal():
    en, ko = cg.MESSAGES["en"], cg.MESSAGES["ko"]
    assert set(en) == set(ko)
    for key in en:
        fields = lambda s: sorted(re.findall(r"\{(\w*)\}", s))
        assert fields(en[key]) == fields(ko[key]), key
        assert en[key].strip() and ko[key].strip(), key


def test_every_issue_code_has_messages():
    for code in cg.ERROR_CODES | cg.READABILITY_CODES | {"kept_as_is", "shift_suspect", "overlap", "out_of_order",
                                                        "nonpositive_duration", "stray_block"}:
        assert any(k.startswith(f"issue.{code}") for k in cg.MESSAGES["en"]), code


@pytest.mark.parametrize("env,cli_lang,expected", [
    ({}, None, "en"),
    ({"LANG": "ko_KR.UTF-8"}, None, "ko"),
    ({"LANG": "ko_KR.UTF-8", "LC_ALL": "en_GB.UTF-8"}, None, "en"),
    ({"LANG": "en_GB.UTF-8", "LC_MESSAGES": "ko_KR.UTF-8"}, None, "ko"),
    ({"LC_ALL": "ko_KR.UTF-8", "SUBTITLE_CUE_GUARD_LANG": "en"}, None, "en"),
    ({"SUBTITLE_CUE_GUARD_LANG": "ko", "LC_ALL": "en_GB.UTF-8"}, None, "ko"),
    ({"SUBTITLE_CUE_GUARD_LANG": "ko"}, "en", "en"),
    ({"LANG": "ja_JP.UTF-8"}, None, "en"),
    ({"LANG": "C"}, "ko", "ko"),
])
def test_lang_precedence(env, cli_lang, expected):
    assert cg.resolve_lang(cli_lang, env) == expected


def test_lang_precedence_end_to_end(monkeypatch, cli):
    src = EX / "sample.srt"
    bad = EX / "bad.ko.json"
    base = ["check", src, bad, "--target", "ko", "--format", "text"]
    monkeypatch.setenv("LANG", "ko_KR.UTF-8")
    assert "다시 번역:" in cli(*base)[1]
    assert "retry:" in cli(*base, "--lang", "en")[1]
    assert "retry:" in cli("--lang", "en", *base)[1]
    monkeypatch.setenv("SUBTITLE_CUE_GUARD_LANG", "en")
    assert "retry:" in cli(*base)[1]
    assert "다시 번역:" in cli(*base, "--lang=ko")[1]
    monkeypatch.setenv("LC_ALL", "ko_KR.UTF-8")
    assert "retry:" in cli(*base)[1]  # the tool variable beats LC_ALL


def test_help_in_both_languages(cli):
    code, out, _ = cli("--lang", "ko", "check", "--help")
    assert code == 0 and "번역을 원본과 대조" in out and "--no-retry-readability" in out
    code, out, _ = cli("--lang", "en", "check", "--help")
    assert code == 0 and "verify translations against the source" in out
    code, out, _ = cli("check", "--help", "--lang", "ko")
    assert "번역을 원본과 대조" in out
    code, out, _ = cli("--lang", "ko", "--help")
    assert code == 0 and "결정적 도우미" in out and "extract" in out


def test_report_codes_do_not_depend_on_language(cli):
    args = ["check", EX / "sample.srt", EX / "bad.ko.json", "--target", "ko"]
    en = json.loads(cli(*args, "--lang", "en")[1])
    ko = json.loads(cli(*args, "--lang", "ko")[1])
    strip = lambda r: [{k: v for k, v in x.items() if k != "message"} for x in r["issues"]]
    assert strip(en) == strip(ko) and en["retry"] == ko["retry"]
    assert en["issues"][0]["message"] != ko["issues"][0]["message"]


@pytest.fixture
def broken(tmp_path):
    return write(tmp_path / "broken.srt", (FIX / "broken.srt").read_text(encoding="utf-8"))


def test_error_exit_codes_and_messages(tmp_path, cli, broken):
    good = jwrite(tmp_path / "t.json", {"1": "x"})
    # broken timing line
    code, _, err = cli("check", broken, good, "--target", "ko")
    assert code == 2 and err.splitlines()[0] == f"error: {broken}:6: invalid timing line"
    code, _, err = cli("--lang", "ko", "check", broken, good, "--target", "ko")
    assert err.splitlines()[0] == f"오류: {broken}:6: 시간 코드 줄을 읽을 수 없습니다"
    assert err.splitlines()[1].startswith("  힌트:")
    # invalid JSON
    notjson = write(tmp_path / "n.json", "{oops")
    code, _, err = cli("check", EX / "sample.srt", notjson, "--target", "ko")
    assert code == 2 and err.startswith(f"error: {notjson}: not valid JSON (")
    code, _, err = cli("--lang", "ko", "check", EX / "sample.srt", notjson, "--target", "ko")
    assert err.startswith(f"오류: {notjson}: JSON 형식이 아닙니다 (")
    # no cues
    empty = write(tmp_path / "e.srt", "just some text\n")
    code, _, err = cli("check", empty, good, "--target", "ko")
    assert code == 2 and err.splitlines()[0] == f"error: {empty}: no cues found"
    code, _, err = cli("--lang", "ko", "check", empty, good, "--target", "ko")
    assert err.splitlines()[0] == f"오류: {empty}: 자막 큐가 없습니다"
    # unknown language
    code, _, err = cli("check", EX / "sample.srt", good, "--target", "xx")
    assert code == 2 and err.splitlines()[0] == ("error: unknown target language 'xx' "
                                                 "(use --profile or --cps/--line-width/--max-lines)")
    code, _, err = cli("--lang", "ko", "check", EX / "sample.srt", good, "--target", "xx")
    assert err.splitlines()[0] == ("오류: 알 수 없는 목표 언어 'xx' (--profile 이나 --cps/--line-width/--max-lines 를 지정하세요)")
    # bad fps
    code, _, err = cli("retime", EX / "sample.srt", "--fps", "25", "-o", tmp_path / "o.srt")
    assert code == 2 and err.splitlines()[0] == "error: --fps expects SRC:DST like 23.976:25"
    code, _, err = cli("--lang", "ko", "retime", EX / "sample.srt", "--fps", "25", "-o", tmp_path / "o.srt")
    assert err.splitlines()[0] == "오류: --fps 는 23.976:25 같은 SRC:DST 형식이어야 합니다"


def test_file_errors(tmp_path, cli):
    good = jwrite(tmp_path / "t.json", {"1": "x"})
    code, _, err = cli("check", tmp_path / "missing.srt", good, "--target", "ko")
    assert code == 2 and "cannot read file" in err
    latin = tmp_path / "latin.srt"
    latin.write_bytes("1\n00:00:01,000 --> 00:00:02,000\ncaf\xe9\n".encode("latin-1"))
    code, _, err = cli("check", latin, good, "--target", "ko")
    assert code == 2 and "not valid UTF-8" in err
    code, _, err = cli("retime", EX / "sample.srt", "--shift", "1s", "-o", tmp_path / "no" / "dir" / "o.srt")
    assert code == 2 and "cannot write file" in err


def test_usage_errors_exit_2(cli):
    assert cli()[0] == 2
    assert cli("check")[0] == 2
    assert cli("--lang", "fr", "check")[0] == 2
    code, _, err = cli("--lang", "ko", "bogus")
    assert code == 2 and "오류:" in err


def test_real_process_smoke(tmp_path):
    proc = subprocess.run([sys.executable, str(SCRIPT), "check", str(EX / "sample.srt"), str(EX / "bad.ko.json"),
                           "--target", "ko"], capture_output=True, encoding="utf-8", env=child_env(LANG="C.UTF-8"),
                          stdin=subprocess.DEVNULL, timeout=120)
    assert proc.returncode == 1 and '"retry": ["1", "2", "3"]' in proc.stdout
    proc = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, encoding="utf-8", env=child_env(LANG="C.UTF-8"),
                          stdin=subprocess.DEVNULL, timeout=120)
    assert proc.returncode == 0 and "usage" in proc.stdout.lower()
