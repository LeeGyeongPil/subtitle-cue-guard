"""Things that pass on a developer machine but break on a fresh CI checkout.

Each test guards one way the GitHub Actions run can differ from a local run:
line endings rewritten by git, a non-UTF-8 locale, forced colour output,
an extra dev dependency, a CI matrix that skips the oldest supported Python,
or SKILL.md frontmatter the external spec validator would reject.
Only the standard library and pytest are used, and nothing touches the network.
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

import pytest

from conftest import EX, ROOT, SCRIPT

# 줄 끝·BOM 을 일부러 담은 픽스처 — 바이트가 바뀌면 바이트 비교 테스트와 평가 해시가 깨진다
BYTE_EXACT = [ROOT / "tests" / "fixtures" / "bom_crlf.srt", ROOT / "evals" / "fixtures" / "task-vtt-bytes" / "rich.vtt"]
BOM = b"\xef\xbb\xbf"
SKILL_DIR = ROOT / "skills" / "subtitle-cue-guard"
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def read(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


# ① 바이트 고정 픽스처 ------------------------------------------------------------------

@pytest.mark.parametrize("path", BYTE_EXACT, ids=lambda p: p.name)
def test_byte_exact_fixtures_keep_bom_and_crlf(path):
    data = path.read_bytes()
    hint = (f"{path.relative_to(ROOT)} lost its UTF-8 BOM or CRLF line endings. Git probably normalised it: "
            "check .gitattributes (the file must be -text) and `git ls-files --eol` (expect i/crlf w/crlf), "
            "then restore the original bytes.")
    assert data.startswith(BOM), hint
    assert b"\r\n" in data, hint
    assert data.count(b"\n") == data.count(b"\r\n"), hint  # 모든 줄 끝이 CRLF


# ② .gitattributes ------------------------------------------------------------------------

def test_gitattributes_protects_byte_exact_files():
    path = ROOT / ".gitattributes"
    assert path.is_file(), "add .gitattributes so git never rewrites the byte-exact fixtures"
    rules = {tuple(line.split()) for line in read(path).splitlines() if line.strip() and not line.startswith("#")}
    assert ("*", "text=auto", "eol=lf") in rules
    for pattern in ("*.srt", "*.vtt", "tests/fixtures/**", "evals/fixtures/**"):
        assert (pattern, "-text") in rules or (pattern, "binary") in rules, pattern


def _git(*args: str) -> "subprocess.CompletedProcess[str]":
    try:
        # stdin 을 닫고 시간 상한을 둔다 — CI 에서 무언가를 기다리며 멈추면 job 상한(15분)까지 로그 없이 끌린다
        proc = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, encoding="utf-8",
                              stdin=subprocess.DEVNULL, timeout=60)
    except (FileNotFoundError, PermissionError, OSError) as e:  # git 이 없거나 실행이 막힌 환경
        pytest.skip(f"git is not available: {e}")
    if proc.returncode != 0:
        pytest.skip(f"not a usable git checkout: {proc.stderr.strip()[:200]}")
    return proc


def test_git_treats_byte_exact_files_as_binary_text():
    """Only this check needs git; it is skipped in a plain source copy (sdist, zip download)."""
    rels = [str(p.relative_to(ROOT)) for p in BYTE_EXACT]
    attrs = _git("check-attr", "text", "--", *rels).stdout.splitlines()
    assert attrs == [f"{rel}: text: unset" for rel in rels], attrs
    for line in _git("ls-files", "--eol", "--", *rels).stdout.splitlines():
        index_eol = line.split()[0]
        assert index_eol == "i/crlf", f"{line!r}: the committed blob must keep CRLF (see .gitattributes)"


# ③ pyproject — 런타임 의존성 0, dev 는 pytest 하나 -----------------------------------------

def _toml_array(text: str, key: str) -> list[str]:
    """Read a one-line or multi-line string array without tomllib (Python 3.10 has none)."""
    match = re.search(rf"(?m)^{re.escape(key)}\s*=\s*\[(.*?)\]", text, re.S)
    assert match, f"{key} not found in pyproject.toml"
    return re.findall(r'"([^"]*)"', match.group(1))


def _requires_python_floor(text: str) -> str:
    match = re.search(r'(?m)^requires-python\s*=\s*">=\s*(3\.\d+)', text)
    assert match, "requires-python must be a >=3.x floor"
    return match.group(1)


def test_dependencies_are_minimal():
    text = read(ROOT / "pyproject.toml")
    project = text.split("[project]", 1)[1].split("\n[", 1)[0]
    assert _toml_array(project, "dependencies") == []  # 스크립트는 표준 라이브러리만
    dev = _toml_array(text, "dev")
    assert [re.split(r"[<>=!~ ;\[]", d, maxsplit=1)[0] for d in dev] == ["pytest"], dev
    lock = read(ROOT / "uv.lock")
    assert 'name = "coverage"' not in lock and 'name = "pytest-cov"' not in lock, "run `uv lock` after editing pyproject"


# ④ CI 워크플로 --------------------------------------------------------------------------

def test_ci_workflow_matches_supported_pythons():
    ci = read(ROOT / ".github" / "workflows" / "ci.yml")
    floor = _requires_python_floor(read(ROOT / "pyproject.toml"))
    matrix = re.search(r"python:\s*\[([^\]]*)\]", ci)
    assert matrix, "the scripts job needs a python matrix"
    versions = re.findall(r'"([^"]+)"', matrix.group(1))
    assert floor in versions, f"CI must test the oldest supported Python {floor}: {versions}"
    assert "uv sync --locked" in ci
    assert "--cov" not in ci
    assert "git ls-files --eol" in ci, "keep the diagnostics step: it shows whether git rewrote the fixtures"
    assert ci.count("timeout-minutes:") >= 2


# ⑤ SKILL.md frontmatter — skills-ref(83021e2) validator 규칙의 오프라인 미러 ---------------

ALLOWED_FIELDS = {"name", "description", "license", "allowed-tools", "metadata", "compatibility"}


def _frontmatter(text: str) -> dict[str, str]:
    assert text.startswith("---"), "SKILL.md must start with YAML frontmatter (---)"
    parts = text.split("---", 2)
    assert len(parts) == 3, "frontmatter not closed with ---"
    lines = text.splitlines()
    closing = lines.index("---", 1)
    # 값 안에 --- 가 있으면 skills-ref 는 거기서 frontmatter 를 끊는다 — 줄 단위 구분과 같아야 한다
    assert parts[1].strip("\n") == "\n".join(lines[1:closing]), "a frontmatter value contains ---"
    fields: dict[str, str] = {}
    for line in lines[1:closing]:
        if not line.strip() or line.startswith((" ", "\t")):
            continue  # metadata 의 하위 항목
        key, sep, value = line.partition(":")
        assert sep, f"not a key: value line: {line!r}"
        value = value.strip()
        # strictyaml 이 읽을 수 있는 평범한 스칼라(따옴표 없는 값에 ': '·' #'·흐름 기호 금지)
        if value and value[0] not in "\"'":
            assert ": " not in value and " #" not in value, f"{key}: quote the value"
            assert value[0] not in "{[&*!|>%@`", f"{key}: plain scalar cannot start with {value[0]!r}"
        fields[key.strip()] = value.strip("\"'")
    return fields


def test_skill_frontmatter_passes_the_spec_rules():
    raw = (SKILL_DIR / "SKILL.md").read_bytes()
    text = raw.decode("utf-8")  # UTF-8 이어야 한다(깨지면 여기서 UnicodeDecodeError)
    fields = _frontmatter(text)
    assert set(fields) <= ALLOWED_FIELDS, set(fields) - ALLOWED_FIELDS
    name = unicodedata.normalize("NFKC", fields["name"].strip())
    assert 0 < len(name) <= 64 and name == name.lower()
    assert not name.startswith("-") and not name.endswith("-") and "--" not in name
    assert all(c.isalnum() or c == "-" for c in name)
    assert unicodedata.normalize("NFKC", SKILL_DIR.name) == name
    assert 0 < len(fields["description"]) <= 1024
    assert len(fields.get("compatibility", "")) <= 500


def test_plugin_manifest_names_match():
    plugin = json.loads(read(ROOT / ".claude-plugin" / "plugin.json"))
    market = json.loads(read(ROOT / ".claude-plugin" / "marketplace.json"))
    skills = sorted(p.name for p in (ROOT / "skills").iterdir() if p.is_dir())
    assert skills == [plugin["name"]]
    assert [p["name"] for p in market["plugins"]] == [plugin["name"]]


# ⑥ 테스트 소스의 기본 인코딩 의존 -----------------------------------------------------------

def _encoding_free_calls(path: Path) -> list[str]:
    """Calls that use the platform's default encoding: read_text/write_text/open/subprocess text mode."""
    found = []
    for node in ast.walk(ast.parse(read(path), str(path))):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
        keywords = {k.arg for k in node.keywords}
        if "encoding" in keywords:
            continue
        if name in ("read_text", "write_text"):
            found.append(f"{path.name}:{node.lineno} {name}()")
        elif name == "open":
            mode = next((k.value for k in node.keywords if k.arg == "mode"), None)
            if mode is None:  # Path.open(mode) 는 첫 인자, open(file, mode) 는 둘째 인자
                index = 0 if isinstance(func, ast.Attribute) else 1
                mode = node.args[index] if len(node.args) > index else None
            if not (isinstance(mode, ast.Constant) and "b" in str(mode.value)):
                found.append(f"{path.name}:{node.lineno} open() in text mode")
        elif name == "run" and keywords & {"text", "universal_newlines"}:
            found.append(f"{path.name}:{node.lineno} subprocess text mode")
    return found


def test_tests_never_rely_on_the_default_encoding():
    """Python 3.15 turns UTF-8 mode on by default; 3.10-3.14 use the locale encoding (ASCII under LANG=C)."""
    found = [hit for path in sorted((ROOT / "tests").glob("*.py")) for hit in _encoding_free_calls(path)]
    assert found == [], "pass encoding='utf-8': " + ", ".join(found)


# ⑦ 미배정 문자 ----------------------------------------------------------------------------

def _data_files():
    for folder in (ROOT / "examples", ROOT / "tests" / "fixtures", ROOT / "evals"):
        for path in sorted(folder.rglob("*")):
            if path.is_file() and path.suffix in (".srt", ".vtt", ".json", ".md"):
                yield path


def test_fixture_characters_are_assigned_in_this_python():
    """Python 3.10 ships Unicode 13.0: a newer character would get a different width there."""
    unassigned = [f"{p.relative_to(ROOT)}: U+{ord(c):04X}" for p in _data_files() for c in set(read(p))
                  if unicodedata.category(c) == "Cn"]
    assert unassigned == [], f"unicodedata {unicodedata.unidata_version}: {unassigned}"


# ⑧ 나쁜 환경(ASCII 로캘·UTF-8 모드 끔·강제 색)의 실제 프로세스 ---------------------------------

def _hostile_run(*args: str) -> "subprocess.CompletedProcess[bytes]":
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C", "LANG": "C",
           "PYTHONCOERCECLOCALE": "0", "FORCE_COLOR": "1"}
    # 출력은 바이트로 받아 직접 UTF-8 로 푼다 — 부모 프로세스의 로캘에 기대지 않는다
    return subprocess.run([sys.executable, "-X", "utf8=0", str(SCRIPT), *args], capture_output=True, env=env,
                          cwd=str(ROOT), stdin=subprocess.DEVNULL, timeout=120)


def test_cli_under_ascii_locale_and_forced_colour():
    proc = _hostile_run("--lang", "ko", "check", str(EX / "sample.srt"), str(EX / "bad.ko.json"),
                        "--target", "ko", "--format", "text")
    out = proc.stdout.decode("utf-8")
    assert proc.returncode == 1, proc.stderr.decode("utf-8", "replace")
    assert "다시 번역: 1, 2, 3" in out

    proc = _hostile_run("--help")
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    assert "usage:" in ANSI.sub("", proc.stdout.decode("utf-8"))

    proc = _hostile_run("--lang", "ko", "check", str(ROOT / "no-such-file.srt"), str(EX / "bad.ko.json"),
                        "--target", "ko")
    assert proc.returncode == 2
    assert "오류:" in ANSI.sub("", proc.stderr.decode("utf-8"))


# ⑨ 멈춤(hang) 방지 — 자식 프로세스는 stdin 을 닫고 시간 상한을 둔다 ---------------------------

SUBPROCESS_CALLS = {"run", "Popen", "call", "check_call", "check_output"}


def _unbounded_subprocess_calls(path: Path) -> list[str]:
    """subprocess calls in the tests that could wait forever: no timeout, or stdin left open."""
    found = []
    for node in ast.walk(ast.parse(read(path), str(path))):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        owner = node.func.value
        if not (isinstance(owner, ast.Name) and owner.id == "subprocess" and node.func.attr in SUBPROCESS_CALLS):
            continue
        keywords = {k.arg for k in node.keywords}
        if "timeout" not in keywords and node.func.attr != "Popen":
            found.append(f"{path.name}:{node.lineno} no timeout")
        if not keywords & {"stdin", "input"}:
            found.append(f"{path.name}:{node.lineno} stdin not closed")
    return found


def test_child_processes_cannot_hang():
    """A child that waits on stdin or never exits stalls the CI job until its timeout with no useful log."""
    found = [hit for path in sorted((ROOT / "tests").glob("*.py")) for hit in _unbounded_subprocess_calls(path)]
    assert found == [], "pass stdin=subprocess.DEVNULL and timeout=...: " + ", ".join(found)


def _workflow_steps(ci: str) -> list[str]:
    """Split ci.yml into step blocks (lines starting with `      - `) without a YAML parser."""
    steps: list[str] = []
    for line in ci.splitlines():
        if line.startswith("      - "):
            steps.append(line)
        elif steps and line.startswith("        "):
            steps[-1] += "\n" + line
        elif not line.startswith("      "):
            steps.append("")  # 다음 job·키로 넘어가면 블록을 끊는다
    return [s for s in steps if s]


def test_every_ci_command_step_has_a_timeout():
    """Each `run:` step has its own timeout, and pytest dumps tracebacks when a test hangs."""
    ci = read(ROOT / ".github" / "workflows" / "ci.yml")
    run_steps = [s for s in _workflow_steps(ci) if "run:" in s]
    assert run_steps, "no run steps found in ci.yml"
    missing = [s.splitlines()[0].strip() for s in run_steps if "timeout-minutes:" not in s]
    assert missing == [], f"add timeout-minutes to these steps: {missing}"
    assert re.search(r"(?m)^faulthandler_timeout\s*=\s*\d+", read(ROOT / "pyproject.toml")), \
        "set faulthandler_timeout in [tool.pytest.ini_options] so a hanging test prints where it hangs"
