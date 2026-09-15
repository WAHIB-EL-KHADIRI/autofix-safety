"""The manifest exists so that a clean run is still evidence.

These tests hold that line: an artifact with no findings must still say what
was scanned, and a half-finished run must be distinguishable from a finished
one.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from autofix_safety import __version__
from autofix_safety.manifest import (
    SCHEMA,
    RunManifest,
    corpus_revision,
    load_results,
    summarise,
    tool_version,
    write_results,
)


def a_manifest(**overrides) -> RunManifest:
    defaults = {
        "tool": "ruff",
        "corpus": "/corpus/Lib",
        "flags": ["--select", "ALL", "--fix"],
        "tool_version": "ruff 0.16.7",
        "files_total": 3,
    }
    return RunManifest(**{**defaults, **overrides})


def test_a_clean_run_still_records_what_was_scanned(tmp_path: Path) -> None:
    out = tmp_path / "clean.json"
    run = a_manifest(files_scanned=3, complete=True)

    write_results(out, run, [])

    document = json.loads(out.read_text(encoding="utf-8"))

    assert document["findings"] == []
    assert document["run"]["tool"] == "ruff"
    assert document["run"]["tool_version"] == "ruff 0.16.7"
    assert document["run"]["corpus"] == "/corpus/Lib"
    assert document["run"]["files_scanned"] == 3
    assert document["run"]["flags"] == ["--select", "ALL", "--fix"]
    assert document["run"]["complete"] is True


def test_the_artifact_is_no_longer_a_bare_list(tmp_path: Path) -> None:
    """The whole point of the change: `[]` proved nothing."""
    out = tmp_path / "clean.json"

    write_results(out, a_manifest(), [])

    assert out.read_text(encoding="utf-8").strip() != "[]"
    assert isinstance(json.loads(out.read_text(encoding="utf-8")), dict)


def test_findings_survive_alongside_the_manifest(tmp_path: Path) -> None:
    out = tmp_path / "dirty.json"
    findings = [{"path": "a.sql", "kind": "CORRUPTION"}]

    write_results(out, a_manifest(tool="sqlfluff"), findings)

    _, loaded = load_results(out)
    assert loaded == findings


def test_an_unfinished_run_says_so(tmp_path: Path) -> None:
    """A checkpoint must not look like a completed clean scan."""
    out = tmp_path / "partial.json"
    run = a_manifest(files_scanned=1, files_total=1805)

    write_results(out, run, [])

    document = json.loads(out.read_text(encoding="utf-8"))
    assert document["run"]["complete"] is False
    assert document["run"]["files_scanned"] < document["run"]["files_total"]


def test_errors_are_counted_separately_from_scans(tmp_path: Path) -> None:
    out = tmp_path / "errs.json"

    write_results(out, a_manifest(files_scanned=2, errors=1), [])

    document = json.loads(out.read_text(encoding="utf-8"))
    assert document["run"]["errors"] == 1
    assert document["run"]["files_scanned"] == 2


def test_the_manifest_carries_the_scanner_and_schema_version(tmp_path: Path) -> None:
    out = tmp_path / "v.json"

    write_results(out, a_manifest(), [])

    document = json.loads(out.read_text(encoding="utf-8"))
    assert document["run"]["scanner_version"] == __version__
    assert document["run"]["schema"] == SCHEMA


def test_started_at_is_utc_and_second_precision(tmp_path: Path) -> None:
    out = tmp_path / "t.json"

    write_results(out, a_manifest(), [])

    started = json.loads(out.read_text(encoding="utf-8"))["run"]["started_at"]
    assert started.endswith("Z")
    assert "." not in started


def test_writing_is_atomic_and_leaves_no_temp_file(tmp_path: Path) -> None:
    out = tmp_path / "atomic.json"

    write_results(out, a_manifest(), [])
    write_results(out, a_manifest(files_scanned=2), [])

    assert list(tmp_path.iterdir()) == [out]


def test_a_rewrite_never_leaves_truncated_json(tmp_path: Path) -> None:
    """The checkpoint writer overwrites a larger file with a smaller one."""
    out = tmp_path / "shrink.json"
    many = [{"path": f"{n}.py", "kind": "CORRUPTION"} for n in range(50)]

    write_results(out, a_manifest(), many)
    write_results(out, a_manifest(), [])

    document = json.loads(out.read_text(encoding="utf-8"))
    assert document["findings"] == []


def test_old_bare_list_artifacts_are_readable_but_report_no_provenance(
    tmp_path: Path,
) -> None:
    """Pre-0.3 files are exactly what this module exists to stop producing."""
    legacy = tmp_path / "legacy.json"
    legacy.write_text('[{"path": "a.sql", "kind": "CORRUPTION"}]', encoding="utf-8")

    run, findings = load_results(legacy)

    assert run is None
    assert findings == [{"path": "a.sql", "kind": "CORRUPTION"}]


def test_summarise_names_the_tool_build_on_a_clean_run() -> None:
    line = summarise(a_manifest(files_scanned=1805, files_total=1805), [])

    assert "clean" in line
    assert "1805/1805" in line
    assert "ruff 0.16.7" in line


def test_summarise_counts_findings_when_there_are_some() -> None:
    line = summarise(
        a_manifest(files_scanned=3, files_total=3),
        [{"kind": "CORRUPTION"}, {"kind": "UNSTABLE"}],
    )

    assert "2 findings" in line


def test_duration_is_recorded_as_a_number(tmp_path: Path) -> None:
    out = tmp_path / "d.json"

    write_results(out, a_manifest(), [])

    duration = json.loads(out.read_text(encoding="utf-8"))["run"]["duration_s"]
    assert isinstance(duration, (int, float))
    assert duration >= 0


def test_tool_version_returns_none_for_a_missing_executable() -> None:
    assert tool_version("definitely-not-a-real-tool-xyzzy") is None


def test_corpus_revision_is_none_for_a_plain_directory(tmp_path: Path) -> None:
    assert corpus_revision(tmp_path) is None


def test_corpus_revision_is_none_for_a_path_that_is_not_a_directory(
    tmp_path: Path,
) -> None:
    a_file = tmp_path / "f.txt"
    a_file.write_text("x", encoding="utf-8")

    assert corpus_revision(a_file) is None


@pytest.mark.skipif(
    subprocess.run(
        ["git", "--version"], capture_output=True, check=False
    ).returncode
    != 0,
    reason="git is not available",
)
def test_corpus_revision_reports_the_commit_of_a_git_corpus(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "t"], check=True)
    (tmp_path / "a.sql").write_text("SELECT 1", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-qm", "seed"], check=True
    )

    revision = corpus_revision(tmp_path)

    assert revision is not None
    assert len(revision) == 40
