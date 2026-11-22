from __future__ import annotations

import json
import re

import pytest

from conftest import EX, FIX, cg, write


def timings(path):
    return re.findall(r"^(\S+) --> (\S+)", path.read_text(), re.M)


def retime(cli, tmp_path, src, *args, name="out.srt"):
    out = tmp_path / name
    code, stdout, err = cli("retime", src, *args, "-o", out)
    return code, out, stdout, err


def test_fps_exact_values(tmp_path, cli):
    src = write(tmp_path / "s.srt", "1\n00:00:01,000 --> 01:00:00,000\nHello there\n")
    code, out, stdout, _ = retime(cli, tmp_path, src, "--fps", "23.976:25")
    assert code == 0 and timings(out) == [("00:00:00,959", "00:57:32,544")]
    result = json.loads(stdout)
    assert result["changed"] == 1 and result["warnings"] == []


def test_fps_rounds_half_up_and_accepts_fractions(tmp_path, cli):
    src = write(tmp_path / "s.srt", "1\n00:00:00,500 --> 00:00:01,001\nHello there\n")
    _, out, _, _ = retime(cli, tmp_path, src, "--fps", "1:2")
    assert timings(out) == [("00:00:00,250", "00:00:00,501")]  # 500.5 rounds up
    _, out, _, _ = retime(cli, tmp_path, src, "--fps", "24000/1001:24")
    assert timings(out) == [("00:00:00,500", "00:00:01,000")]


def test_shift_units_and_clamping(tmp_path, cli):
    src = write(tmp_path / "s.srt", "1\n00:00:01,000 --> 00:00:02,000\nHello\n\n2\n00:00:05,000 --> 00:00:06,000\nBye\n")
    _, out, _, _ = retime(cli, tmp_path, src, "--shift", "+1.5s")
    assert timings(out) == [("00:00:02,500", "00:00:03,500"), ("00:00:06,500", "00:00:07,500")]
    _, out, _, _ = retime(cli, tmp_path, src, "--shift", "300ms")
    assert timings(out)[0] == ("00:00:01,300", "00:00:02,300")
    code, out, stdout, _ = retime(cli, tmp_path, src, "--shift", "-2s")  # glued automatically
    assert code == 0 and timings(out) == [("00:00:00,000", "00:00:00,000"), ("00:00:03,000", "00:00:04,000")]
    result = json.loads(stdout)
    assert [w["id"] for w in result["warnings"]] == ["1"] and result["warnings"][0]["code"] == "clamped_to_zero"
    code, out, stdout, _ = retime(cli, tmp_path, src, "--shift=-2s", "--format", "text", "--lang", "ko")
    assert "시작 시각이 0 아래로" in stdout


def test_min_duration_never_crosses_next_cue(tmp_path, cli):
    text = ("1\n00:00:01,000 --> 00:00:01,200\nShort one\n\n2\n00:00:02,000 --> 00:00:02,100\nShort two\n\n"
            "3\n00:00:10,000 --> 00:00:10,100\nShort three\n")
    src = write(tmp_path / "s.srt", text)
    _, out, _, _ = retime(cli, tmp_path, src, "--min-duration", "1.5", "--min-gap", "0.083")
    assert timings(out) == [("00:00:01,000", "00:00:01,917"), ("00:00:02,000", "00:00:03,500"),
                            ("00:00:10,000", "00:00:11,500")]
    # without a gap the end may reach the next start
    _, out, _, _ = retime(cli, tmp_path, src, "--min-duration", "5")
    assert timings(out)[0][1] == "00:00:02,000" and timings(out)[1][1] == "00:00:07,000"


def test_min_gap_shortens_overlapping_end(tmp_path, cli):
    text = "1\n00:00:01,000 --> 00:00:03,000\nOne\n\n2\n00:00:03,010 --> 00:00:04,000\nTwo\n"
    src = write(tmp_path / "s.srt", text)
    _, out, _, _ = retime(cli, tmp_path, src, "--min-gap", "0.1")
    assert timings(out) == [("00:00:01,000", "00:00:02,910"), ("00:00:03,010", "00:00:04,000")]


def test_vtt_settings_and_short_form_preserved(tmp_path, cli):
    code, out, _, _ = retime(cli, tmp_path, FIX / "rich.vtt", "--shift", "+1s", name="o.vtt")
    assert code == 0
    text = out.read_text()
    assert "00:02.000 --> 00:04.500 align:start line:10%" in text
    assert "00:04.600 --> 00:06.000 region:top" in text
    assert "NOTE\nTranslator note: keep names." in text and "<v Anna>" in text
    _, out, _, _ = retime(cli, tmp_path, FIX / "rich.vtt", "--shift", "+3599s", name="o2.vtt")
    assert "01:00:00.000 --> 01:00:02.500 align:start line:10%" in out.read_text()


def test_unchanged_times_keep_bytes(tmp_path, cli):
    src = FIX / "bom_crlf.srt"
    out = tmp_path / "o.srt"
    code, stdout, _ = cli("retime", src, "--shift", "0s", "-o", out)
    assert code == 0 and out.read_bytes() == src.read_bytes() and json.loads(stdout)["changed"] == 0
    code, out2, _, _ = retime(cli, tmp_path, src, "--shift", "1s", name="o2.srt")
    data = out2.read_bytes()
    assert data.startswith(b"\xef\xbb\xbf1\r\n00:00:02,000 --> 00:00:04,000\r\n")
    assert data.endswith(b"The meeting starts at 10:30.")


def test_long_hours(tmp_path, cli):
    _, out, _, _ = retime(cli, tmp_path, FIX / "long_hours.srt", "--shift", "+1s")
    assert timings(out)[1] == ("103:30:01,500", "103:30:04,000")


def test_text_output(tmp_path, cli):
    out = tmp_path / "o.srt"
    code, stdout, _ = cli("retime", EX / "sample.srt", "--fps", "23.976:25", "--format", "text", "-o", out)
    assert code == 0 and "retimed 4 of 4 cues" in stdout


@pytest.mark.parametrize("args,needle", [
    (["--fps", "23.976"], "--fps expects SRC:DST like 23.976:25"),
    (["--fps", "a:b"], "--fps expects SRC:DST"),
    (["--fps", "0:25"], "--fps expects SRC:DST"),
    (["--fps", "1:0"], "--fps expects SRC:DST"),
    (["--shift", "abc"], "--shift expects a value"),
    (["--min-duration", "x"], "invalid value for --min-duration"),
    (["--min-gap=-1"], "must not be negative"),
    ([], "retime needs at least one"),
])
def test_retime_errors(tmp_path, cli, args, needle):
    code, _, err = cli("retime", EX / "sample.srt", *args, "-o", tmp_path / "o.srt")
    assert code == 2 and needle in err


def test_retime_refuses_to_overwrite_input(tmp_path, cli):
    src = write(tmp_path / "s.srt", "1\n00:00:01,000 --> 00:00:02,000\nHello\n")
    code, _, err = cli("retime", src, "--shift", "1s", "-o", src)
    assert code == 2 and "is also an input file" in err
    assert src and open(src).read().startswith("1\n00:00:01,000")


def test_fps_helpers():
    assert cg.round_half_up(cg.Fraction(5, 2)) == 3
    assert cg.parse_shift("-250ms") == -250
    assert cg.parse_shift("+0.5s") == 500
