"""Find auto-fix corruption by round-tripping a linter's own fixture corpus.

The invariant:

    If a fixture parses cleanly, its `fix` output must parse cleanly too.

A linter's test fixtures are the best adversarial input available for free --
maintainers wrote them to sit on the edges of the grammar. They are normally
used to test the *parser*; pointing them at the *fixer* asks a question nobody
asked.

Usage:
    autofix-safety-sqlfluff <fixtures-dir> <out.json> [dialect]

    <fixtures-dir>  e.g. test/fixtures/dialects  (dialect taken from the
                    subdirectory name) or a single dialect directory.
    [dialect]       optional filter, e.g. `mysql`.

Run it from a checkout where the linter is installed (`pip install -e .`).
Expect roughly an hour for ~2,250 fixtures.

Findings, in the order they are checked (first match wins):

    FIX_CRASH   the fixer raised.
    CORRUPTION  parsed before the fix, does not parse after.
    COMMENTED   parses after, but the fix introduced a comment -- meaning
                source text was swallowed into one.
    GUARDED     the fixer worked out that a rule's fix would corrupt the file
                and declined to apply it. The file still parses, so every check
                above stays silent -- but sqlfluff's own warning text says
                "Please report this as a bug", so these are solicited reports
                the other classes would throw away.
    UNSTABLE    fixing twice does not converge.

Triage rules, learned the hard way and worth more than the scan:

  * UNSTABLE is a hypothesis, never a finding. sqlfluff's CLI loops the fixer
    until output stabilises, so one unconverged pass is expected behaviour.
    9 of the first 10 findings on the first run were this noise.
  * Measure the *before* state too. `ALTER USER 'x'@'y'` fails to parse after
    the fix and also before it -- a parser gap, not corruption. Reporting it
    inside a corruption issue would weaken every hard claim next to it.
  * Comparing *all* code tokens before/after does NOT work: it fires on every
    legitimate fix (added commas, capitalised keywords, dropped parens) and
    buries the signal. The narrow invariant "a fix never introduces a comment"
    is the one that survives contact with a real corpus.
  * Extracted statements lie. A statement pulled out of a fixture may not parse
    standalone even when the file does. Minimise from the real fixture, then
    re-verify against the real fixture.
  * Redirect to a file, never pipe through `tail` -- it buffers until EOF and
    you watch nothing happen for an hour.

Single-process on purpose: ProcessPoolExecutor hangs on Windows here.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import traceback
from pathlib import Path

from sqlfluff.core import FluffConfig, Linter

# sqlfluff declines some fixes it can tell would corrupt, and says so on the
# logger: "Fixes for RF06 not applied, as it would result in an unparsable
# file. Please report this as a bug ...". The file still parses afterwards, so
# the CORRUPTION check cannot see these -- yet they are precisely what the tool
# is asking to be told about. Capture them as their own class.
GUARD_RE = re.compile(
    r"Fixes for (?P<rule>\w+) not applied.*?unparsable", re.IGNORECASE | re.DOTALL
)

# Violation codes that mean "the input is not valid SQL for this dialect",
# as opposed to a style rule firing.
UNPARSABLE_CODES = ("PRS", "LXR", "TMP")

_LINTERS: dict[str, Linter] = {}


def linter_for(dialect: str) -> Linter:
    """One Linter per dialect, reused -- construction is the expensive part."""
    if dialect not in _LINTERS:
        _LINTERS[dialect] = Linter(
            config=FluffConfig(overrides={"dialect": dialect, "rules": "all"})
        )
    return _LINTERS[dialect]


def _violation_code(violation) -> str:
    """Violation code across sqlfluff versions, without assuming the API."""
    for attr in ("rule_code",):
        fn = getattr(violation, attr, None)
        if callable(fn):
            try:
                return str(fn())
            except Exception:
                pass
    return str(getattr(violation, "code", "") or "")


def parse_status(sql: str, dialect: str) -> tuple[bool, int]:
    """Return (parses_cleanly, number_of_comment_segments).

    A file parses cleanly when it produces a tree, that tree contains no
    `unparsable` segment, and no lex/parse violation was raised.
    """
    parsed = linter_for(dialect).parse_string(sql)

    for violation in getattr(parsed, "violations", []) or []:
        if _violation_code(violation).startswith(UNPARSABLE_CODES):
            return False, 0

    tree = getattr(parsed, "tree", None)
    if tree is None:
        return False, 0

    try:
        if any(True for _ in tree.recursive_crawl("unparsable")):
            return False, 0
    except Exception:
        # Older/newer crawl signatures: fall back to the violation check above.
        pass

    return True, count_comments(tree)


def count_comments(tree) -> int:
    try:
        return sum(1 for _ in tree.recursive_crawl("comment"))
    except Exception:
        return 0


class _GuardCollector(logging.Handler):
    """Collects the rule codes sqlfluff refused to fix during one run."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.rules: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            match = GUARD_RE.search(record.getMessage())
        except Exception:
            return
        if match and match.group("rule") not in self.rules:
            self.rules.append(match.group("rule"))


def fix(sql: str, dialect: str) -> tuple[str, list[str]]:
    """Run the fixer once. Returns (output, rules the fixer declined to apply)."""
    collector = _GuardCollector()
    root = logging.getLogger("sqlfluff")
    previous = root.level
    root.addHandler(collector)
    # The warning is only emitted if WARNING is not filtered out upstream.
    if previous > logging.WARNING or previous == logging.NOTSET:
        root.setLevel(logging.WARNING)
    try:
        result = linter_for(dialect).lint_string(sql, fix=True)
        fixed = result.fix_string()
        # fix_string() returns (text, success) in current versions, text in older.
        text = fixed[0] if isinstance(fixed, tuple) else fixed
    finally:
        root.removeHandler(collector)
        root.setLevel(previous)
    return text, collector.rules


def scan_file(path: Path, dialect: str, root: Path | None = None) -> dict | None:
    """Round-trip one fixture. Returns a finding dict, or None if it is fine."""
    rel = str(path.relative_to(root) if root else path).replace("\\", "/")
    try:
        sql = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as exc:
        return {"path": rel, "dialect": dialect, "kind": "READ_ERROR",
                "detail": str(exc)}

    if not sql.strip():
        return None

    # The `before` measurement is what separates corruption from a parser gap.
    try:
        parsed_before, comments_before = parse_status(sql, dialect)
    except Exception:
        return None  # cannot establish a baseline -> nothing to claim

    if not parsed_before:
        return None  # already unparsable: not the fixer's fault

    try:
        once, guarded = fix(sql, dialect)
    except Exception as exc:
        return {"path": rel, "dialect": dialect, "kind": "FIX_CRASH",
                "detail": f"{type(exc).__name__}: {exc}"}

    try:
        parsed_after, comments_after = parse_status(once, dialect)
    except Exception as exc:
        return {"path": rel, "dialect": dialect, "kind": "CORRUPTION",
                "detail": f"re-parse raised {type(exc).__name__}: {exc}"}

    if not parsed_after:
        return {"path": rel, "dialect": dialect, "kind": "CORRUPTION",
                "detail": diff_lines(sql, once)}

    # Output that parses but lost meaning. Nothing a linter legitimately does
    # creates a comment, so a new one means source text was swallowed.
    if comments_after > comments_before:
        return {"path": rel, "dialect": dialect, "kind": "COMMENTED",
                "detail": {"before": comments_before, "after": comments_after,
                           "lines": diff_lines(sql, once)}}

    # The fixer caught itself: it would have corrupted this file and backed off.
    # Invisible to every check above, and the warning text asks for a report.
    if guarded:
        return {"path": rel, "dialect": dialect, "kind": "GUARDED",
                "detail": {"rules": guarded}}

    try:
        twice, _ = fix(once, dialect)
    except Exception as exc:
        return {"path": rel, "dialect": dialect, "kind": "FIX_CRASH",
                "detail": f"second pass: {type(exc).__name__}: {exc}"}

    if twice != once:
        # Almost always benign multi-pass convergence. Reported so it can be
        # counted, not so it can be filed.
        return {"path": rel, "dialect": dialect, "kind": "UNSTABLE",
                "detail": {"len1": len(once), "len2": len(twice)}}

    return None


def diff_lines(before: str, after: str, limit: int = 5) -> list[str]:
    """Lines present in `after` but not in `before` -- the changed output."""
    old = set(before.splitlines())
    return [line.strip() for line in after.splitlines()
            if line.strip() and line not in old][:limit]


def fixtures(root: Path, only: str | None) -> list[tuple[Path, str]]:
    """Every .sql under root, paired with the dialect from its directory."""
    found: list[tuple[Path, str]] = []
    for path in sorted(root.rglob("*.sql")):
        dialect = path.parent.name if path.parent != root else root.name
        if only and dialect != only:
            continue
        found.append((path, dialect))
    return found


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2

    root, out_path = Path(argv[1]), Path(argv[2])
    only = argv[3] if len(argv) > 3 else None

    if not root.is_dir():
        print(f"not a directory: {root}")
        return 2

    targets = fixtures(root, only)
    print(f"{len(targets)} fixtures, "
          f"{len({d for _, d in targets})} dialects", flush=True)

    findings: list[dict] = []
    for index, (path, dialect) in enumerate(targets, start=1):
        try:
            finding = scan_file(path, dialect, root)
        except Exception:
            traceback.print_exc()
            continue

        if finding:
            findings.append(finding)
            print(f"  {finding['kind']:<11} {dialect}/{path.name}", flush=True)

        if index % 100 == 0:
            print(f"[{index}/{len(targets)}] {len(findings)} so far", flush=True)
            out_path.write_text(json.dumps(findings, indent=2), encoding="utf-8")

    out_path.write_text(json.dumps(findings, indent=2), encoding="utf-8")

    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding["kind"]] = counts.get(finding["kind"], 0) + 1

    print(f"\nwrote {out_path}")
    for kind in ("CORRUPTION", "COMMENTED", "GUARDED", "FIX_CRASH", "UNSTABLE",
                 "READ_ERROR"):
        if kind in counts:
            print(f"  {kind:<11} {counts[kind]}")
    print("\nCORRUPTION and COMMENTED are worth reading. GUARDED is the fixer "
          "asking to be told. UNSTABLE is noise until proven otherwise.")
    return 0


def cli() -> None:
    """Console entry point. `main` keeps taking argv so it stays testable."""
    raise SystemExit(main(sys.argv))


if __name__ == "__main__":
    cli()
