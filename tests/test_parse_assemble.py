from __future__ import annotations

import json

import pytest

from conftest import EX, FIX, cg, jwrite, write

ALL_FILES = sorted(FIX.glob("*.srt")) + sorted(FIX.glob("*.vtt")) + [EX / "sample.srt", EX / "sample.vtt"]
PARSEABLE = [p for p in ALL_FILES if p.name != "broken.srt"]


@pytest.mark.parametrize("path", PARSEABLE, ids=lambda p: p.name)
def test_identity_roundtrip_byte_exact(path, tmp_path, cli):
    original = path.read_bytes()
    sub = cg.parse_subtitle(original.decode("utf-8"), str(path))
    assert sub.render([]).encode("utf-8") == original
    # also through the CLI: every cue falls back to the source text
    empty = jwrite(tmp_path / "empty.json", {})
    out = tmp_path / ("out" + path.suffix)
    code, _, _ = cli("assemble", path, empty, "--fallback", "source", "-o", out)
    assert code == 0
    assert out.read_bytes() == original


def test_parser_handles_odd_files():
    dup = cg.parse_subtitle((FIX / "dup_numbers.srt").read_text(encoding="utf-8"), "dup")
    assert [c.id for c in dup.cues] == ["1", "2", "3"]  # ids are positions, not the numbers in the file
    assert dup.cues[1].text == "Second line\nwith two rows."
    hours = cg.parse_subtitle((FIX / "long_hours.srt").read_text(encoding="utf-8"), "h")
    assert hours.cues[1].start == (103 * 3600 + 30 * 60) * 1000 + 500
    vtt = cg.parse_subtitle((FIX / "rich.vtt").read_text(encoding="utf-8"), "r")
    assert vtt.fmt == "vtt" and len(vtt.cues) == 3
    assert vtt.cues[0].start == 1000 and vtt.cues[0].rest == " align:start line:10%"
    crlf = cg.parse_subtitle((FIX / "bom_crlf.srt").read_bytes().decode("utf-8"), "c")
    assert crlf.bom and crlf.cues[2].text == "The meeting starts at 10:30."


def test_stray_block_is_kept_and_reported():
    text = "1\n00:00:01,000 --> 00:00:02,000\nHello\n\nstray words here\n\n2\n00:00:03,000 --> 00:00:04,000\nBye\n"
    sub = cg.parse_subtitle(text, "s")
    assert len(sub.cues) == 2 and sub.stray == [5]
    assert sub.render([]) == text


def _rich_translation():
    return {
        "1": "⟦1⟧나는 그가 여기 있었다고\n말한 적 없어.⟦2⟧",
        "2": "⟦1⟧잠깐.⟦2⟧",
        "3": "어디 가?",
    }


def test_assemble_changes_only_text_lines(tmp_path, cli):
    src = FIX / "rich.vtt"
    tr = jwrite(tmp_path / "tr.json", _rich_translation())
    out = tmp_path / "out.vtt"
    code, _, _ = cli("assemble", src, tr, "--target", "ko", "-o", out)
    assert code == 0
    before = src.read_text(encoding="utf-8").split("\n")
    after = out.read_text(encoding="utf-8").split("\n")
    changed_before = {i for i, line in enumerate(before) if line not in after}
    # header, STYLE, REGION, NOTE, ids, timing lines and settings are untouched
    for keep in ("WEBVTT - sample", "Kind: captions", "STYLE", "::cue { color: lime }", "REGION", "id:top",
                 "NOTE", "Translator note: keep names.", "intro", "00:01.000 --> 00:03.500 align:start line:10%",
                 "00:03.600 --> 00:05.000 region:top", "2", "00:05.200 --> 00:07.000"):
        assert keep in after, keep
    assert [before[i] for i in sorted(changed_before)] == [
        "<v Anna>I never said", "that he was here.</v>", "<c.yellow>Wait.</c.yellow>", "Where are you going?"]
    # placeholders were restored to the original tags
    assert "<v Anna>나는 그가 여기 있었다고" in after
    assert "말한 적 없어.</v>" in after
    assert "<c.yellow>잠깐.</c.yellow>" in after


def test_assemble_keeps_bom_crlf_and_missing_final_newline(tmp_path, cli):
    src = FIX / "bom_crlf.srt"
    tr = jwrite(tmp_path / "tr.json", {"1": "⟦1⟧좋은 아침.⟦2⟧\n오늘 기분 어때요?", "2": "괜찮아요, 고마워요.",
                                       "3": "회의는 10:30에 시작해요."})
    out = tmp_path / "out.srt"
    assert cli("assemble", src, tr, "--target", "ko", "-o", out)[0] == 0
    expected = ("﻿1\r\n00:00:01,000 --> 00:00:03,000\r\n<i>좋은 아침.</i>\r\n오늘 기분 어때요?\r\n\r\n"
                "2\r\n00:00:03,500 --> 00:00:05,000\r\n괜찮아요, 고마워요.\r\n\r\n"
                "3\r\n00:00:05,500 --> 00:00:08,000\r\n회의는 10:30에 시작해요.")
    assert out.read_bytes() == expected.encode("utf-8")


def test_assemble_refuse_and_fallback(tmp_path, cli):
    src = EX / "sample.srt"
    bad = EX / "bad.ko.json"
    out = tmp_path / "out.srt"
    code, stdout, _ = cli("assemble", src, bad, "--target", "ko", "-o", out)
    assert code == 1 and not out.exists()
    assert json.loads(stdout)["written"] is False
    report = tmp_path / "report.json"
    code, stdout, _ = cli("assemble", src, bad, "--target", "ko", "--fallback", "source", "-o", out, "--report", report)
    result = json.loads(stdout)
    assert code == 0 and result["written"] is True and result["fallback"] == ["1", "2", "3"]
    text = out.read_text(encoding="utf-8")
    assert "I never said\nthat he was here." in text  # cue 1 kept its source text
    assert "<i>Wait.</i>" in text and "{\\an8}Where are you going?" in text
    assert "역으로, 9시에." in text  # cue 4 was fine and is translated
    rep = json.loads(report.read_text(encoding="utf-8"))
    assert rep["fallback"] == ["1", "2", "3"] and rep["written"] is True
    code, text_out, _ = cli("assemble", src, bad, "--target", "ko", "--format", "text", "-o", out)
    assert code == 1 and "1, 2, 3" in text_out


def test_assemble_refuses_unexpected_id_and_never_overwrites(tmp_path, cli):
    src = tmp_path / "s.srt"
    write(src, "1\n00:00:01,000 --> 00:00:02,000\nHello there\n")
    tr = jwrite(tmp_path / "t.json", {"1": "안녕", "9": "extra"})
    out = tmp_path / "o.srt"
    code, stdout, _ = cli("assemble", src, tr, "-o", out)
    assert code == 1 and not out.exists()
    code, _, err = cli("assemble", src, tr, "-o", src)
    assert code == 2 and "is also an input file" in err
    code, _, _ = cli("assemble", src, tr, "--fallback", "source", "-o", out)
    assert code == 0 and "안녕" in out.read_text(encoding="utf-8")


def test_overlay_retry_files(tmp_path, cli):
    src = EX / "sample.srt"
    first = jwrite(tmp_path / "tr.json", {"1": "그가 여기 있었다고는\n말 안 했어.", "2": "", "3": "Where are you going?",
                                          "4": "역에, 9시에."})
    retry = jwrite(tmp_path / "tr.retry1.json", [{"id": "2", "text": "⟦1⟧잠깐.⟦2⟧"}, {"id": 3, "text": "⟦1⟧어디 가?"}])
    code, stdout, _ = cli("check", src, first, retry, "--target", "ko")
    assert code == 0, stdout
    out = tmp_path / "o.srt"
    assert cli("assemble", src, first, retry, "--target", "ko", "-o", out)[0] == 0
    assert out.read_text(encoding="utf-8") == (EX / "sample.srt").read_text(encoding="utf-8").replace(
        "I never said\nthat he was here.", "그가 여기 있었다고는\n말 안 했어.").replace(
        "<i>Wait.</i>", "<i>잠깐.</i>").replace("{\\an8}Where are you going?", "{\\an8}어디 가?").replace(
        "To the station, at 9 o'clock.", "역에, 9시에.")


def test_bilingual_and_renumber(tmp_path, cli):
    src = FIX / "dup_numbers.srt"
    tr = jwrite(tmp_path / "t.json", {"1": "첫 줄.", "2": "둘째 줄,\n두 행.", "3": "셋째 줄."})
    out = tmp_path / "o.srt"
    assert cli("assemble", src, tr, "--bilingual", "--renumber", "-o", out)[0] == 0
    text = out.read_text(encoding="utf-8")
    assert text.startswith("1\n00:00:01,000 --> 00:00:02,500\nFirst line.\n첫 줄.\n")
    assert "\n2\n00:00:03,000" in text and "\n3\n00:00:05,000" in text
    assert "Second line\nwith two rows.\n둘째 줄,\n두 행.\n" in text
    # renumber inserts a number when the source had none
    nonum = tmp_path / "n.srt"
    write(nonum, "00:00:01,000 --> 00:00:02,000\nHello there\n")
    out2 = tmp_path / "o2.srt"
    assert cli("assemble", nonum, jwrite(tmp_path / "t2.json", {"1": "안녕"}), "--renumber", "-o", out2)[0] == 0
    assert out2.read_text(encoding="utf-8") == "1\n00:00:01,000 --> 00:00:02,000\n안녕\n"


def test_cue_without_text_and_without_final_newline(tmp_path, cli):
    src = tmp_path / "s.srt"
    write(src, "1\n00:00:01,000 --> 00:00:02,000")
    out = tmp_path / "o.srt"
    tr = jwrite(tmp_path / "t.json", {"1": "안녕"})
    assert cli("assemble", src, tr, "-o", out)[0] == 0
    assert out.read_text(encoding="utf-8") == "1\n00:00:01,000 --> 00:00:02,000\n안녕"


def test_translation_text_is_sanitized(tmp_path, cli):
    src = tmp_path / "s.srt"
    write(src, "1\n00:00:01,000 --> 00:00:02,000\nHello there\n")
    tr = jwrite(tmp_path / "t.json", {"1": "\n안녕  \n\n  하세요 --> \n"})
    out = tmp_path / "o.srt"
    assert cli("assemble", src, tr, "-o", out)[0] == 0
    assert out.read_text(encoding="utf-8") == "1\n00:00:01,000 --> 00:00:02,000\n안녕\n하세요 ->\n"
