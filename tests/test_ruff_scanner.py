"""Tests for the ruff adapter.

These cover the parts that decide whether a finding is reported at all. A
scanner that silently stops finding things looks exactly like a scanner that
found nothing, so the oracle and the corpus filter are the things worth pinning
down.
"""

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scanners"))

import ruff_fix_safety as scanner  # noqa: E402


class TestOracle:
    def test_valid_python_parses(self):
        assert scanner.parses("x = 1\nprint(x)\n")

    def test_unclosed_bracket_does_not_parse(self):
        assert not scanner.parses("x = 1\nprint(x\n")

    def test_null_bytes_do_not_raise(self):
        """ValueError, not SyntaxError -- must be caught, not propagated."""
        assert not scanner.parses("x = '\0'\nimport os\0\n")

    def test_error_detail_carries_line_and_text(self):
        detail = scanner.first_syntax_error("x = 1\nprint(x\n")
        assert detail["lineno"] == 2
        assert "print(x" in detail["line"]
        assert detail["msg"]


class TestCorpusFilter:
    def test_vendored_directories_are_excluded(self):
        """Without this, pointing at a Python install scans every installed
        package -- 56,549 files instead of 1,805."""
        for vendored in ("site-packages", "node_modules", ".venv", "__pycache__"):
            assert vendored in scanner.SKIP_DIRS

    def test_filter_matches_on_parent_directories_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pkg").mkdir()
            (root / "site-packages" / "dep").mkdir(parents=True)
            (root / "pkg" / "mine.py").write_text("x = 1\n", encoding="utf-8")
            (root / "site-packages" / "dep" / "theirs.py").write_text("y = 2\n", encoding="utf-8")

            kept = [
                p for p in root.rglob("*.py")
                if scanner.SKIP_DIRS.isdisjoint(p.relative_to(root).parts[:-1])
            ]

            assert [p.name for p in kept] == ["mine.py"]


@pytest.mark.skipif(
    not scanner.ruff_available(), reason="ruff is not installed"
)
class TestAgainstRealRuff:
    def test_fix_actually_rewrites_the_file(self):
        """If ruff stopped being invoked, every other test here would still
        pass and the scanner would report a clean corpus forever."""
        source = "import os\nimport sys\nprint(1)\n"
        with tempfile.TemporaryDirectory() as tmp:
            out, crash = scanner.run_fix(source, unsafe=True, workdir=Path(tmp))
        assert crash is None
        assert out != source, "ruff did not remove the unused imports"
        assert scanner.parses(out)

    def test_valid_input_survives_the_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            corpus = workdir / "corpus"
            corpus.mkdir()
            (corpus / "sample.py").write_text(
                "import os\n\n\ndef f(a, b):\n    return a + b\n", encoding="utf-8"
            )
            finding = scanner.scan_file(
                corpus / "sample.py", corpus, workdir, unsafe=True
            )
        assert finding is None, f"unexpected finding: {finding}"

    def test_already_broken_input_is_skipped_not_reported(self):
        """A pre-existing parse failure is a parser gap, not a fixer defect.
        Reporting it would weaken every real finding filed alongside it."""
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            corpus = workdir / "corpus"
            corpus.mkdir()
            (corpus / "broken.py").write_text("def f(\n", encoding="utf-8")
            finding = scanner.scan_file(
                corpus / "broken.py", corpus, workdir, unsafe=True
            )
        assert finding is None
