"""Shared helpers: load the script as a module and run its CLI in-process."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "skills" / "subtitle-cue-guard" / "scripts" / "cue_guard.py"
FIX = ROOT / "tests" / "fixtures"
EX = ROOT / "examples"

_spec = importlib.util.spec_from_file_location("cue_guard", SCRIPT)
cg = importlib.util.module_from_spec(_spec)
import sys

sys.modules["cue_guard"] = cg
_spec.loader.exec_module(cg)


def child_env(**extra: str) -> dict:
    """Minimal environment for a child process: only what the OS needs to start Python, plus `extra`.

    Nothing else leaks in from the runner (locale, colour and proxy variables), so a child behaves the same
    on a laptop and on CI. Pass the variables a test cares about as keyword arguments.
    """
    env = {k: os.environ[k] for k in ("PATH", "SYSTEMROOT", "TMPDIR", "TEMP", "TMP") if k in os.environ}
    env.update(extra)
    return env


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in ("LC_ALL", "LC_MESSAGES", "SUBTITLE_CUE_GUARD_LANG"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LANG", "en_GB.UTF-8")
    # Python 3.14 의 argparse 는 색을 기본으로 켠다 — CI 러너의 FORCE_COLOR 등에 따라
    # 도움말·오류 문구에 ANSI 코드가 섞이지 않도록 테스트 안에서는 색을 끈다
    for key in ("FORCE_COLOR", "PYTHON_COLORS"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("NO_COLOR", "1")


@pytest.fixture
def cli(capsys):
    def run(*args):
        try:
            code = cg.main([str(a) for a in args])
        except SystemExit as e:  # argparse exits for --help and usage errors
            code = int(e.code or 0)
        out = capsys.readouterr()
        return code, out.out, out.err

    return run


def make_srt(n: int, step: float = 2.0, dur: float = 1.5, text=lambda i: f"Line number {i} is here.") -> str:
    def ts(sec: float) -> str:
        ms = round(sec * 1000)
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"

    blocks = [f"{i}\n{ts(i * step)} --> {ts(i * step + dur)}\n{text(i)}\n" for i in range(1, n + 1)]
    return "\n".join(blocks)


def write(path: Path, text: str) -> str:
    path.write_text(text, encoding="utf-8", newline="")
    return str(path)


def jwrite(path: Path, obj) -> str:
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return str(path)
