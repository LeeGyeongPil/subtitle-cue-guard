from __future__ import annotations

import json

import pytest

from conftest import EX, FIX, cg, jwrite, make_srt, write


def run_check(cli, src, *trs, target="ko", extra=()):
    code, out, err = cli("check", src, *trs, "--target", target, *extra)
    assert code in (0, 1), err
    return code, json.loads(out)


def codes(report, cid=None):
    return [(x["id"], x["code"]) for x in report["issues"] if cid is None or x["id"] == cid]


def one_cue(tmp_path, text="Hello there friend.", start="00:00:01,000", end="00:00:02,000"):
    return write(tmp_path / "one.srt", f"1\n{start} --> {end}\n{text}\n")


def test_bad_fixture_exact_report(cli):
    code, rep = run_check(cli, EX / "sample.srt", EX / "bad.ko.json")
    assert code == 1 and rep["ok"] is False
    assert rep["retry"] == ["1", "2", "3"]
    assert rep["counts"] == {"source": 4, "translated": 5}
    assert codes(rep) == [("1", "merge_suspect"), ("1", "cps"), ("1", "line_width"), ("2", "empty"),
                          ("3", "untranslated"), ("3", "tag_mismatch"), ("5", "unexpected_id")]
    by = {(x["id"], x["code"]): x for x in rep["issues"]}
    assert by[("1", "cps")]["value"] == 12.8 and by[("1", "cps")]["limit"] == 12
    assert by[("1", "line_width")]["value"] == 36.0 and by[("1", "line_width")]["limit"] == 16
    assert by[("3", "tag_mismatch")]["source"] == ["{\\an8}"]
    assert not [x for x in rep["issues"] if x["code"] == "number_mismatch"]  # the 8 inside {\an8} is not a number


def test_bad_fixture_command_output_text(cli):
    code, out, _ = cli("check", EX / "sample.srt", EX / "bad.ko.json", "--target", "ko")
    assert code == 1
    assert '"retry": ["1", "2", "3"]' in out and '"value": 12.8' in out and '"value": 36.0' in out


def test_good_fixture_is_ok(cli):
    code, rep = run_check(cli, EX / "sample.srt", EX / "good.ko.json")
    assert code == 0 and rep["ok"] is True and rep["issues"] == [] and rep["retry"] == []
    assert rep["readability"] == "checked"


def test_shifted_fixture_anchorless_merge(cli):
    code, rep = run_check(cli, EX / "sample.srt", EX / "shifted.ko.json")
    assert code == 1 and rep["retry"] == ["2", "3", "4"]
    assert codes(rep) == [("2", "merge_suspect"), ("3", "shift_suspect"), ("4", "number_mismatch")]
    by = {x["code"]: x for x in rep["issues"]}
    assert by["merge_suspect"]["reason"] == "sentences"
    assert by["shift_suspect"]["neighbors"] == ["4"] and by["shift_suspect"]["numbers"] == ["9"]


def test_no_false_positive_guards(tmp_path, cli):
    text = ("1\n00:00:01,000 --> 00:00:03,000\nAnna\n\n"
            "2\n00:00:03,500 --> 00:00:05,500\nWe waited nine hours.\n\n"
            "3\n00:00:06,000 --> 00:00:08,000\nWow!\n\n"
            "4\n00:00:08,500 --> 00:00:10,500\nOkay, I will go there now.\n\n"
            "5\n00:00:11,000 --> 00:00:13,000\nPlease wait.\n")
    src = write(tmp_path / "s.srt", text)
    tr = jwrite(tmp_path / "t.json", {"1": "Anna", "2": "우리는 9시간 기다렸어.", "3": "와우!",
                                      "4": "알았어, 지금 갈게.", "5": "잠깐만 기다려 주세요."})
    code, rep = run_check(cli, src, tr)
    assert code == 0, rep["issues"]
    assert [x["code"] for x in rep["issues"]] == ["kept_as_is"] and rep["issues"][0]["severity"] == "info"
    assert rep["ok"] is True and rep["retry"] == []


def test_missing_and_unexpected_ids(tmp_path, cli):
    src = write(tmp_path / "s.srt", make_srt(3, text=lambda i: "Some words here."))
    tr = jwrite(tmp_path / "t.json", {"1": "몇 마디 말.", "3": "몇 마디 말.", "7": "x"})
    code, rep = run_check(cli, src, tr)
    assert code == 1 and rep["retry"] == ["2"]
    assert codes(rep) == [("2", "missing"), ("7", "unexpected_id")]


@pytest.mark.parametrize("translation,code", [("", "empty"), ("⟦1⟧", "empty"), ("   \n ", "empty")])
def test_empty_variants(tmp_path, cli, translation, code):
    src = one_cue(tmp_path, "<i>Hello there friend.</i>")
    code_, rep = run_check(cli, src, jwrite(tmp_path / "t.json", {"1": translation}))
    assert ("1", "empty") in codes(rep)


def test_untranslated_rules(tmp_path, cli):
    src = one_cue(tmp_path, "Hello there friend.")
    _, rep = run_check(cli, src, jwrite(tmp_path / "t.json", {"1": "Hello there friend."}))
    assert rep["issues"][0]["reason"] == "same_as_source" and rep["retry"] == ["1"]
    _, rep = run_check(cli, src, jwrite(tmp_path / "t2.json", {"1": "Hola amigo mio."}))
    assert rep["issues"][0]["reason"] == "wrong_script"
    _, rep = run_check(cli, src, jwrite(tmp_path / "t3.json", {"1": "안녕 친구야."}))
    assert rep["ok"] is True
    # Latin targets only check "same as source"
    _, rep = run_check(cli, src, jwrite(tmp_path / "t4.json", {"1": "Hola amigo."}), target="es")
    assert rep["ok"] is True
    _, rep = run_check(cli, src, jwrite(tmp_path / "t5.json", {"1": "hello  there FRIEND."}), target="es")
    assert rep["issues"][0]["code"] == "untranslated"
    # Japanese needs kana or Han, Chinese needs Han
    _, rep = run_check(cli, src, jwrite(tmp_path / "t6.json", {"1": "こんにちは友よ。"}), target="ja")
    assert rep["ok"] is True
    _, rep = run_check(cli, src, jwrite(tmp_path / "t7.json", {"1": "こんにちは、ともよ。"}), target="zh")
    assert rep["issues"][0]["reason"] == "wrong_script"
    _, rep = run_check(cli, src, jwrite(tmp_path / "t8.json", {"1": "你好朋友。"}), target="zh-CN")
    assert rep["ok"] is True and rep["readability"] == "skipped"


def test_kept_as_is_single_word_and_letterless(tmp_path, cli):
    src = write(tmp_path / "s.srt", "1\n00:00:01,000 --> 00:00:02,000\nAnna\n\n2\n00:00:03,000 --> 00:00:04,000\n♪♪\n")
    _, rep = run_check(cli, src, jwrite(tmp_path / "t.json", {"1": "Anna", "2": "♪♪"}))
    assert codes(rep) == [("1", "kept_as_is"), ("2", "kept_as_is")] and rep["retry"] == []


def test_tag_mismatch_cases(tmp_path, cli):
    src = one_cue(tmp_path, "<i>Hello</i> {\\an8}there friend.")
    _, rep = run_check(cli, src, jwrite(tmp_path / "a.json", {"1": "⟦1⟧안녕⟦2⟧ ⟦3⟧친구야."}))
    assert rep["ok"] is True
    _, rep = run_check(cli, src, jwrite(tmp_path / "b.json", {"1": "⟦1⟧안녕 ⟦3⟧친구야."}))
    assert codes(rep) == [("1", "tag_mismatch")]
    _, rep = run_check(cli, src, jwrite(tmp_path / "c.json", {"1": "⟦1⟧안녕⟦1⟧ ⟦3⟧친구야."}))
    assert codes(rep) == [("1", "tag_mismatch")]
    _, rep = run_check(cli, src, jwrite(tmp_path / "d.json", {"1": "⟦1⟧안녕⟦2⟧ ⟦3⟧친구야.⟦9⟧"}))
    assert codes(rep) == [("1", "tag_mismatch")]
    # raw tags (the --keep-tags way) are compared as well
    _, rep = run_check(cli, src, jwrite(tmp_path / "e.json", {"1": "<i>안녕</i> {\\an8}친구야."}))
    assert rep["ok"] is True


def test_number_mismatch_and_normalisation(tmp_path, cli):
    src = one_cue(tmp_path, "It costs 1,000 won and 3.5 percent.", end="00:00:09,000")
    _, rep = run_check(cli, src, jwrite(tmp_path / "a.json", {"1": "가격은 1000원이고 3.5퍼센트야."}))
    assert rep["ok"] is True
    _, rep = run_check(cli, src, jwrite(tmp_path / "b.json", {"1": "가격은 1000원이고 3퍼센트야."}))
    assert codes(rep) == [("1", "number_mismatch")] and rep["issues"][0]["missing"] == ["3.5"]
    _, rep = run_check(cli, src, jwrite(tmp_path / "c.json", {"1": "가격은 １０００원이고 ３.５퍼센트야."}),
                       extra=["--line-width", "40"])
    assert rep["ok"] is True  # full-width digits count as digits


def test_cps_boundary(tmp_path, cli):
    src = one_cue(tmp_path, "Twelve letters here.")
    _, rep = run_check(cli, src, jwrite(tmp_path / "a.json", {"1": "가나다라마바사아자차카타"}))  # 12 chars in 1 s
    assert rep["ok"] is True
    _, rep = run_check(cli, src, jwrite(tmp_path / "b.json", {"1": "가나다라마바사아자차카타파"}))
    assert [(x["code"], x["value"]) for x in rep["issues"]] == [("cps", 13.0)] and rep["retry"] == ["1"]
    _, rep = run_check(cli, src, jwrite(tmp_path / "c.json", {"1": "가나다라마바사아자차카타파"}),
                       extra=["--cps", "13"])
    assert rep["ok"] is True
    # spaces are not counted for ko (they are for en)
    _, rep = run_check(cli, src, jwrite(tmp_path / "d.json", {"1": "가나 다라 마바 사아 자차 카타"}))
    assert rep["ok"] is True


def test_cps_english_counts_spaces(tmp_path, cli):
    src = write(tmp_path / "s.srt", "1\n00:00:01,000 --> 00:00:02,000\nUn texto en espanol.\n")
    tr = jwrite(tmp_path / "t.json", {"1": "a" * 20})
    _, rep = run_check(cli, src, tr, target="en")
    assert rep["ok"] is True
    tr = jwrite(tmp_path / "t2.json", {"1": "word " * 4 + "ab"})  # 22 chars with spaces in 1 s
    _, rep = run_check(cli, src, tr, target="en")
    assert [x["code"] for x in rep["issues"]] == ["cps"] and rep["issues"][0]["value"] == 22.0


def test_lines_and_width(tmp_path, cli):
    src = one_cue(tmp_path, "One two three four five six.", end="00:00:09,000")
    _, rep = run_check(cli, src, jwrite(tmp_path / "a.json", {"1": "가나다라마바사아\n자차카타파하가나"}))  # 8+8 wide
    assert rep["ok"] is True
    _, rep = run_check(cli, src, jwrite(tmp_path / "b.json", {"1": "가나다라마바사아\n자차카타파하가나다라마바사아자차카\n라"}))
    assert [x["code"] for x in rep["issues"]] == ["too_many_lines", "line_width"]
    wide = [x for x in rep["issues"] if x["code"] == "line_width"][0]
    assert wide["value"] == 17.0 and wide["limit"] == 16
    # exactly 16 wide characters pass, hangul counts 1.0, latin and spaces 0.5
    _, rep = run_check(cli, src, jwrite(tmp_path / "c.json", {"1": "가나다라마바사아자차카타파하가나"}))
    assert rep["ok"] is True
    _, rep = run_check(cli, src, jwrite(tmp_path / "d.json", {"1": "abcdefghijklmnopqrstuvwxyzabcdefg 가"}))
    assert [x["code"] for x in rep["issues"]] == ["line_width"]


def test_width_helpers():
    assert cg.display_width("가나abc", "eaw") == 3.5
    assert cg.display_width("가́", "eaw") == 1.0  # combining mark has no width
    assert cg.display_width("abc", "count") == 3.0


def test_no_retry_readability_flag(cli):
    code, rep = run_check(cli, EX / "sample.srt", EX / "good.ko.json", extra=["--cps", "3"])
    assert code == 1 and rep["retry"] == ["1", "4"]
    code, rep = run_check(cli, EX / "sample.srt", EX / "good.ko.json", extra=["--cps", "3", "--no-retry-readability"])
    assert code == 0 and rep["retry"] == [] and rep["ok"] is True
    assert any(x["code"] == "cps" for x in rep["issues"])


def test_unknown_language_and_profiles(tmp_path, cli):
    src = one_cue(tmp_path)
    tr = jwrite(tmp_path / "t.json", {"1": "xx"})
    code, _, err = cli("check", src, tr, "--target", "xx")
    assert code == 2 and "unknown target language 'xx'" in err
    code, _, err = cli("check", src, tr, "--target", "xx", "--cps", "20", "--line-width", "30", "--max-lines", "2")
    assert code == 0
    prof = jwrite(tmp_path / "p.json", {"cps": 1, "line_width": 10, "max_lines": 1, "script": "none"})
    code, out, _ = cli("check", src, tr, "--target", "xx", "--profile", prof)
    assert code == 1 and json.loads(out)["limits"]["cps"] == 1
    for bad in ({"nope": 1}, {"cps": -1}, {"max_lines": 0}, {"width_mode": "x"}, {"script": "x"}, {"cps_spaces": 1}, [1]):
        code, _, err = cli("check", src, tr, "--target", "ko", "--profile", jwrite(tmp_path / "bp.json", bad))
        assert code == 2 and "invalid profile" in err
    assert cli("check", src, tr, "--target", "ko", "--profile", write(tmp_path / "bad.json", "{"))[0] == 2


def test_translation_inputs(tmp_path, cli):
    src = EX / "sample.srt"
    arr = jwrite(tmp_path / "a.json", [{"id": "1", "text": "그가 여기 있었다고는\n말 안 했어."},
                                      {"id": 2, "translation": "<i>잠깐.</i>"},
                                      {"id": "3", "text": "{\\an8}어디 가?"}, {"id": "4", "text": "역에, 9시에."}])
    assert run_check(cli, src, arr)[0] == 0
    good = write(tmp_path / "t.ko.srt", (EX / "sample.srt").read_text(encoding="utf-8")
                 .replace("I never said\nthat he was here.", "그가 여기 있었다고는\n말 안 했어.")
                 .replace("To the station, at 9 o'clock.", "역에, 9시에.")
                 .replace("Where are you going?", "어디 가?").replace("Wait.", "잠깐."))
    code, rep = run_check(cli, src, good)
    assert code == 0 and rep["counts"]["translated"] == 4
    assert cli("check", src, jwrite(tmp_path / "x.json", "text"), "--target", "ko")[0] == 2
    assert cli("check", src, jwrite(tmp_path / "y.json", {"1": 5}), "--target", "ko")[0] == 2
    assert cli("check", src, jwrite(tmp_path / "z.json", [1, 2]), "--target", "ko")[0] == 2
    assert cli("check", src, write(tmp_path / "e.json", ""), "--target", "ko")[0] == 2
    assert cli("check", src, tmp_path / "nope.json", "--target", "ko")[0] == 2


def test_source_issues(tmp_path, cli):
    text = ("1\n00:00:01,000 --> 00:00:04,000\nFirst words here.\n\n2\n00:00:03,000 --> 00:00:05,000\nSecond words here.\n\n"
            "3\n00:00:02,000 --> 00:00:02,000\nThird words here.\n\nstray text block\n")
    src = write(tmp_path / "s.srt", text)
    tr = jwrite(tmp_path / "t.json", {"1": "첫째 말.", "2": "둘째 말.", "3": "셋째 말."})
    code, rep = run_check(cli, src, tr)
    assert code == 0 and rep["ok"] is True  # source problems are information only
    assert sorted(x["code"] for x in rep["source_issues"]) == [
        "nonpositive_duration", "out_of_order", "overlap", "stray_block"]


def test_merge_suspect_needs_both_signals(tmp_path, cli):
    # many sentences in the translation but a normal length: no merge suspicion
    text = make_srt(4, text=lambda i: "This is a normal sentence." if i != 2 else "Short.")
    src = write(tmp_path / "s.srt", text)
    tr = {"1": "이것은 평범한 문장이다.", "2": "짧다. 네.", "3": "이것은 평범한 문장이다.", "4": "이것은 평범한 문장이다."}
    _, rep = run_check(cli, src, jwrite(tmp_path / "t.json", tr))
    assert not [x for x in rep["issues"] if x["code"] == "merge_suspect"]
    # a long translation with the same number of sentences is not a merge either
    tr["2"] = "아주 길고 긴 한 문장이지만 문장은 하나뿐이다"
    _, rep = run_check(cli, src, jwrite(tmp_path / "t2.json", tr))
    assert not [x for x in rep["issues"] if x["code"] == "merge_suspect"]
    # sentence count grows and the cue is much longer than the median: suspect, retry includes the next cue
    tr["2"] = "아주 길고 긴 첫 번째 문장이 여기 있다. 그리고 두 번째 문장도 같은 큐 안에 들어 있다."
    _, rep = run_check(cli, src, jwrite(tmp_path / "t3.json", tr))
    assert ("2", "merge_suspect") in codes(rep) and rep["retry"] == ["2", "3"]
    # thresholds are flags
    _, rep = run_check(cli, src, jwrite(tmp_path / "t3.json", tr), extra=["--merge-ratio", "50"])
    assert not [x for x in rep["issues"] if x["code"] == "merge_suspect"]


def test_text_report_languages(cli):
    code, out, _ = cli("check", EX / "sample.srt", EX / "bad.ko.json", "--target", "ko", "--format", "text", "--lang", "ko")
    assert code == 1 and "다시 번역: 1, 2, 3" in out and "12.8" in out
    code, out, _ = cli("check", EX / "sample.srt", EX / "bad.ko.json", "--target", "ko", "--format", "text", "--lang", "en")
    assert "retry: 1, 2, 3" in out and "Reading speed 12.8" in out
    code, out, _ = cli("check", EX / "sample.srt", EX / "good.ko.json", "--target", "ko", "--format", "text")
    assert code == 0 and "no problems found" in out
    code, out, _ = cli("check", EX / "sample.srt", EX / "good.ko.json", "--target", "ja", "--format", "text")
    assert "readability limits skipped" in out


def test_check_writes_output_file(tmp_path, cli):
    target = tmp_path / "r.json"
    code, out, _ = cli("check", EX / "sample.srt", EX / "bad.ko.json", "--target", "ko", "-o", target)
    assert code == 1 and "retry: 1, 2, 3" in out
    assert json.loads(target.read_text(encoding="utf-8"))["retry"] == ["1", "2", "3"]
    code, out, _ = cli("check", EX / "sample.srt", EX / "good.ko.json", "--target", "ko", "-o", target)
    assert code == 0 and "wrote" in out
