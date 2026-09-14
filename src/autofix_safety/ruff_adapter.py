"""Round-trip ruff's own fixture corpus through `ruff check --fix`.

Same invariant as the sqlfluff adapter, one tool down:

    If a fixture parses cleanly, its `--fix` output must parse cleanly too.

The difference from the sqlfluff version, and it is an improvement: **the oracle
is CPython's own `ast.parse`, not the tool under test.** sqlfluff had to be asked
whether it could read its own output, so a lexer bug could in principle hide
itself. Here the judge is the reference implementation of the language, and it
has no stake in ruff being correct.

`--unsafe-fixes` is included deliberately. Ruff's contract for an unsafe fix is
that it *may change the meaning* of the code -- it is nowhere promised that it
may produce code that is not Python. Syntactically invalid output is a bug at
either safety level; the report records which level produced it so severity can
be argued honestly.

Usage:
    autofix-safety-ruff <corpus-dir> <out.json> [--safe-only]

Findings:
    CORRUPTION  parsed before the fix, does not parse after.
    UNSTABLE    fixing twice does not converge.
    FIX_CRASH   ruff exited on a signal, or panicked.

Triage rules carried over -- they cost real time to learn:
  * UNSTABLE is a hypothesis, never a finding. Fixers legitimately need several
    passes to converge, which is why `--fix` is normally run in a loop.
  * Measure the *before* state. A fixture using syntax newer than the running
    interpreter fails `ast.parse` before and after; that is a version gap, not
    corruption, and reporting it would poison an otherwise good issue.
  * Minimise from the real fixture, never from a statement pulled out of it.
"""

from __future__ import annotations

import ast
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RUFF = [sys.executable, "-m", "ruff"]

# Directories that are never the corpus under test. Without this, pointing the
# scanner at a Python installation's Lib/ picks up every installed package and
# turns a 1,807-file run into a 56,549-file one -- measuring third-party code
# nobody asked about.
SKIP_DIRS = {"site-packages", "dist-packages", ".venv", "venv", "node_modules",
             ".git", "__pycache__", ".tox", "build", "dist"}


def ruff_available() -> bool:
    """Whether the ruff module can actually be invoked, for test skipping."""
    try:
        proc = subprocess.run(RUFF + ["--version"], capture_output=True, timeout=30)
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def parses(source: str) -> bool:
    """CPython's own parser is the oracle -- ruff gets no say here."""
    try:
        ast.parse(source)
        return True
    except SyntaxError:
        return False
    except (ValueError, RecursionError, MemoryError):
        # Null bytes, pathological nesting: not a fixer defect.
        return False


def run_fix(source: str, unsafe: bool, workdir: Path) -> tuple[str, str | None]:
    """Fix `source` in a scratch file. Returns (output, crash_reason|None)."""
    target = workdir / "subject.py"
    target.write_text(source, encoding="utf-8")

    cmd = RUFF + ["check", "--isolated", "--no-cache", "--select", "ALL",
                  "--fix", "--exit-zero", str(target)]
    if unsafe:
        cmd.append("--unsafe-fixes")

    try:
        # Capture bytes, never text=True. On Windows that decodes the child's
        # output with the locale codec (cp1252) inside subprocess's own reader
        # *thread* -- so a non-cp1252 byte in ruff's output raises there, where
        # no `except` in this file can see it, and the run dies silently.
        proc = subprocess.run(cmd, capture_output=True, timeout=90)
    except subprocess.TimeoutExpired:
        return source, "timeout after 90s"

    # --exit-zero means lint findings do not set the code, so anything
    # non-zero here is ruff itself failing.
    if proc.returncode != 0:
        stderr = (proc.stderr or b"").decode("utf-8", errors="replace")
        detail = stderr.strip().splitlines()
        return source, f"exit {proc.returncode}: {detail[-1] if detail else '?'}"

    try:
        return target.read_text(encoding="utf-8"), None
    except UnicodeDecodeError as exc:
        # Ruff turning valid UTF-8 into something that is not is itself a
        # finding, so surface it rather than swallowing it.
        return source, f"output is not valid UTF-8: {exc}"


def scan_file(path: Path, root: Path, workdir: Path, unsafe: bool) -> dict | None:
    try:
        source = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None

    if not source.strip():
        return None

    # Fixtures often target a newer Python than the interpreter running this.
    # Those are skipped, not reported.
    if not parses(source):
        return None

    rel = str(path.relative_to(root)).replace("\\", "/")
    level = "unsafe" if unsafe else "safe"

    once, crash = run_fix(source, unsafe, workdir)
    if crash:
        return {"path": rel, "level": level, "kind": "FIX_CRASH", "detail": crash}

    if not parses(once):
        return {"path": rel, "level": level, "kind": "CORRUPTION",
                "detail": first_syntax_error(once)}

    twice, crash = run_fix(once, unsafe, workdir)
    if crash:
        return {"path": rel, "level": level, "kind": "FIX_CRASH",
                "detail": f"second pass: {crash}"}

    if twice != once:
        return {"path": rel, "level": level, "kind": "UNSTABLE",
                "detail": {"len1": len(once), "len2": len(twice)}}

    return None


def first_syntax_error(source: str) -> dict:
    """The exact line the output stopped being Python on."""
    try:
        ast.parse(source)
    except SyntaxError as exc:
        line = ""
        if exc.lineno:
            lines = source.splitlines()
            if 0 < exc.lineno <= len(lines):
                line = lines[exc.lineno - 1].strip()
        return {"msg": exc.msg, "lineno": exc.lineno, "line": line[:200]}
    return {"msg": "parsed on retry (non-deterministic)"}


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2

    root, out_path = Path(argv[1]), Path(argv[2])
    unsafe = "--safe-only" not in argv

    if not root.is_dir():
        print(f"not a directory: {root}")
        return 2

    targets = sorted(
        path for path in root.rglob("*.py")
        if SKIP_DIRS.isdisjoint(path.relative_to(root).parts[:-1])
    )
    print(f"{len(targets)} files | fixes: "
          f"{'safe + unsafe' if unsafe else 'safe only'}", flush=True)

    findings: list[dict] = []

    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        for index, path in enumerate(targets, start=1):
            try:
                finding = scan_file(path, root, workdir, unsafe)
            except Exception as exc:                       # keep the run alive
                print(f"  ERROR {path.name}: {exc}", flush=True)
                continue

            if finding is not None:
                findings.append(finding)
                print(f"  {finding['kind']:<11} {finding['path']}", flush=True)

            # Outside the `finding` branch on purpose. A clean corpus is the
            # expected result, and when these lived under an early `continue`
            # a run with no findings printed nothing after the header and
            # checkpointed nothing -- 1,805 files of silence that is
            # indistinguishable from a hang, and no partial output if the run
            # is killed near the end.
            if index % 100 == 0:
                out_path.write_text(json.dumps(findings, indent=2), encoding="utf-8")

            if index % 200 == 0:
                print(f"[{index}/{len(targets)}] {len(findings)} so far", flush=True)

    out_path.write_text(json.dumps(findings, indent=2), encoding="utf-8")

    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding["kind"]] = counts.get(finding["kind"], 0) + 1

    print(f"\nwrote {out_path}")
    for kind in ("CORRUPTION", "FIX_CRASH", "UNSTABLE"):
        if kind in counts:
            print(f"  {kind:<11} {counts[kind]}")
    print("\nCORRUPTION first. UNSTABLE is noise until proven otherwise.")
    return 0


def cli() -> None:
    """Console entry point. `main` keeps taking argv so it stays testable."""
    raise SystemExit(main(sys.argv))


if __name__ == "__main__":
    cli()
