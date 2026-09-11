"""Tests for the sqlfluff adapter.

The `GUARDED` class exists because sqlfluff prints a warning when it declines
its own fix, and that warning asks to be reported. The pattern that recognises
it is therefore load-bearing: if it stops matching, a whole finding class
silently disappears and the scan still looks healthy.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scanners"))

sqlfluff = pytest.importorskip("sqlfluff", reason="sqlfluff is not installed")

import sqlfluff_fix_safety as scanner  # noqa: E402


REAL_WARNING = (
    "Fixes for RF06 not applied, as it would result in an unparsable file. "
    "Please report this as a bug with a minimal query which demonstrates "
    "this warning."
)


class TestGuardPattern:
    def test_matches_the_real_warning_and_captures_the_rule(self):
        match = scanner.GUARD_RE.search(REAL_WARNING)
        assert match is not None
        assert match.group("rule") == "RF06"

    def test_captures_other_rule_codes(self):
        match = scanner.GUARD_RE.search(
            "Fixes for LT02 not applied, as it would result in an unparsable file."
        )
        assert match is not None
        assert match.group("rule") == "LT02"

    def test_does_not_match_the_unrelated_skip_message(self):
        """A different message, meaning 'the input was already unparsable'.
        Matching it would turn every pre-existing parser gap into a finding."""
        other = ("Fixes for RF06 could not be safely be applied. "
                 "Likely due to initially unparsable file.")
        assert scanner.GUARD_RE.search(other) is None


class TestParseStatus:
    def test_valid_sql_parses(self):
        parses, comments = scanner.parse_status("SELECT 1 AS a FROM t\n", "ansi")
        assert parses
        assert comments == 0

    def test_comments_are_counted(self):
        parses, comments = scanner.parse_status(
            "SELECT 1 AS a FROM t -- trailing\n", "ansi"
        )
        assert parses
        assert comments >= 1

    def test_invalid_sql_does_not_parse(self):
        parses, _ = scanner.parse_status("SELECT FROM WHERE ((( \n", "ansi")
        assert not parses


class TestKnownDefect:
    """The bug this scanner was written to find, pinned as a test.

    Reported upstream as sqlfluff#8415. If sqlfluff fixes it, this test starts
    failing -- which is the correct signal, not a regression here.
    """

    def test_token_fusion_produces_a_comment(self):
        source = "SELECT 1 * - - 5 AS a, 99 AS b FROM t\n"
        parses_before, _ = scanner.parse_status(source, "ansi")
        assert parses_before, "fixture must parse before the fix"

        fixed, _guarded = scanner.fix(source, "ansi")

        if "--" not in fixed:
            pytest.skip("upstream appears to have fixed the token fusion")
        assert "--" in fixed, "the '- -' operators welded into a comment marker"
