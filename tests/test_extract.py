from __future__ import annotations

import json

import pytest

from conftest import EX, FIX, cg, jwrite, make_srt, write


def extract(cli, *args):
    code, out, err = cli("extract", *args)
    assert code == 0, err
    return json.loads(out)


def test_tags_become_placeholders_and_budgets(cli):
    data = extract(cli, EX / "sample.srt", "--target", "ko")
    cues = data["batches"][0]["cues"]
    assert cues[1]["text"] == "⟦1⟧Wait.⟦2⟧"
    assert cues[2]["text"] == "⟦1⟧Where are you going?"
    assert cues[0] == {"id": "1", "text": "I never said\nthat he was here.", "seconds": 2.5, "max_chars": 30,
                       "max_width": 32.0}
    assert cues[2]["max_chars"] == 21  # floor(1.8 s * 12) = 21 (21.6)
    assert data["limits"] == {"cps": 12, "line_width": 16, "max_lines": 2, "width_mode": "eaw"}
    assert "placeholder" in data["reply_format"]


def test_vtt_tags_and_speaker(cli):
    data = extract(cli, FIX / "rich.vtt", "--target", "ko")
    texts = [c["text"] for c in data["batches"][0]["cues"]]
    assert texts[0] == "⟦1⟧I never said\nthat he was here.⟦2⟧"
    assert texts[1] == "⟦1⟧Wait.⟦2⟧"
    assert data["format"] == "vtt"


def test_keep_tags(cli):
    data = extract(cli, EX / "sample.srt", "--target", "ko", "--keep-tags")
    assert data["batches"][0]["cues"][1]["text"] == "<i>Wait.</i>"
    assert "tag" in data["reply_format"]


def test_batch_size_and_gap_split(tmp_path, cli):
    src = write(tmp_path / "s.srt", make_srt(10))
    data = extract(cli, src, "--target", "en", "--batch", "4", "--gap", "0")
    assert [len(b["cues"]) for b in data["batches"]] == [4, 4, 2]
    # a pause of 3 s or more closes a batch once it holds half the batch size
    text = make_srt(6, step=2.0) + "\n7\n00:01:00,000 --> 00:01:01,000\nAfter the pause here.\n"
    src2 = write(tmp_path / "g.srt", text)
    data = extract(cli, src2, "--target", "en", "--batch", "10", "--gap", "3")
    assert [len(b["cues"]) for b in data["batches"]] == [6, 1]
    data = extract(cli, src2, "--target", "en", "--batch", "10", "--gap", "0")
    assert [len(b["cues"]) for b in data["batches"]] == [7]
    # not before the batch holds half of its capacity
    data = extract(cli, src2, "--target", "en", "--batch", "40", "--gap", "3")
    assert len(data["batches"]) == 1


def test_retry_batch_contains_only_failed_cues_and_context(tmp_path, cli):
    src = write(tmp_path / "s.srt", make_srt(30))
    report = jwrite(tmp_path / "report.json", {"retry": ["17", "18"]})
    data = extract(cli, src, "--target", "en", "--retry-from", report, "--context", "1")
    assert len(data["batches"]) == 1
    batch = data["batches"][0]
    assert [c["id"] for c in batch["cues"]] == ["17", "18"]
    assert [c["id"] for c in batch["context"]] == ["16", "19"]
    assert all(set(c) == {"id", "text"} for c in batch["context"])


def test_only_ids_ranges_and_errors(tmp_path, cli):
    src = write(tmp_path / "s.srt", make_srt(12))
    data = extract(cli, src, "--target", "en", "--only", "3,5-6", "--context", "0")
    assert [c["id"] for c in data["batches"][0]["cues"]] == ["3", "5", "6"]
    code, _, err = cli("extract", src, "--target", "en", "--only", "99")
    assert code == 2 and "unknown cue id '99'" in err
    code, _, err = cli("extract", src, "--target", "en", "--only", "a,b")
    assert code == 2 and "--only expects ids" in err
    code, _, err = cli("extract", src, "--target", "en", "--only", "5-3")
    assert code == 2
    bad = jwrite(tmp_path / "r.json", {"nothing": []})
    code, _, err = cli("extract", src, "--target", "en", "--retry-from", bad)
    assert code == 2 and "no 'retry' list" in err
    notjson = write(tmp_path / "r.txt", "nope")
    assert cli("extract", src, "--target", "en", "--retry-from", notjson)[0] == 2
    assert cli("extract", src, "--target", "en", "--batch", "0")[0] == 2
    assert cli("extract", src, "--target", "en", "--context", "-1")[0] == 2


def test_unlimited_language_has_null_budgets(cli):
    data = extract(cli, EX / "sample.srt", "--target", "ja")
    cue = data["batches"][0]["cues"][0]
    assert cue["max_chars"] is None and cue["max_width"] is None


def test_text_format_and_output_file(tmp_path, cli):
    code, out, _ = cli("extract", EX / "sample.srt", "--target", "ko", "--format", "text")
    assert code == 0 and "[batch 1]" in out and "2: ⟦1⟧Wait.⟦2⟧" in out
    target = tmp_path / "b.json"
    code, out, _ = cli("extract", EX / "sample.srt", "--target", "ko", "-o", target)
    assert code == 0 and json.loads(target.read_text())["tool"] == "subtitle-cue-guard" and "wrote" in out


def test_retry_report_round_trip_with_check(tmp_path, cli):
    code, out, _ = cli("check", EX / "sample.srt", EX / "shifted.ko.json", "--target", "ko")
    report = write(tmp_path / "report.json", out)
    data = extract(cli, EX / "sample.srt", "--target", "ko", "--retry-from", report)
    assert [c["id"] for c in data["batches"][0]["cues"]] == ["2", "3", "4"]
