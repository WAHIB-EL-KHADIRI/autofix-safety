"""Provenance for a scan, so that a clean run is still evidence.

A findings list answers "what went wrong". On a clean corpus that list is
empty, and an empty list is indistinguishable from a scanner that crashed on
startup, walked an empty directory, or was pointed at the wrong corpus.

This project's stated position is that a negative result is a result, which
only holds if the negative result carries enough context to be checked. So
every artifact records what was scanned, with which build of which tool, under
which flags, and when -- next to the findings rather than instead of them.

The manifest is written at the first checkpoint, not at the end, so a run that
is killed half way still leaves a file that says what it was doing.
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import __version__

SCHEMA = "autofix-safety/run/1"


def _run(args: list[str], cwd: Path | None = None) -> str | None:
    """Best-effort capture of a short command's stdout, or None."""
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=cwd,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def tool_version(executable: str) -> str | None:
    """`<tool> --version` as the tool itself reports it.

    Recorded verbatim rather than parsed. The point is to identify the build
    that produced these findings; normalising it would only add a way to be
    wrong about it.
    """
    return _run([executable, "--version"])


def corpus_revision(root: Path) -> str | None:
    """The corpus commit, when the corpus happens to be a git checkout.

    A fixture directory usually is one, and the finding is worth much less
    without knowing which revision of it was scanned. Returns None for a plain
    directory, which is a fact about the corpus rather than an error.
    """
    if not root.is_dir():
        return None
    return _run(["git", "-C", str(root), "rev-parse", "HEAD"])


@dataclass
class RunManifest:
    """What a reader needs in order to disbelieve the findings."""

    tool: str
    corpus: str
    flags: list[str]
    tool_version: str | None = None
    corpus_revision: str | None = None
    files_scanned: int = 0
    files_total: int = 0
    errors: int = 0
    complete: bool = False
    scanner_version: str = __version__
    schema: str = SCHEMA
    python_version: str = field(
        default_factory=lambda: platform.python_version()
    )
    platform: str = field(default_factory=platform.platform)
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    duration_s: float = 0.0

    _monotonic_start: float = field(
        default_factory=time.monotonic, repr=False, compare=False
    )

    def to_dict(self) -> dict:
        data = asdict(self)
        data.pop("_monotonic_start", None)
        data["duration_s"] = round(time.monotonic() - self._monotonic_start, 1)
        return data


def write_results(
    out_path: Path, manifest: RunManifest, findings: list[dict]
) -> None:
    """Write `{run, findings}` atomically.

    Atomically because this is also the checkpoint writer: a run killed while
    the file is being rewritten would otherwise leave truncated JSON where the
    previous checkpoint used to be, which is worse than either outcome.
    """
    document = {"run": manifest.to_dict(), "findings": findings}
    payload = json.dumps(document, indent=2, sort_keys=False)

    tmp_path = out_path.with_name(out_path.name + ".tmp")
    tmp_path.write_text(payload, encoding="utf-8")
    tmp_path.replace(out_path)


def load_results(path: Path) -> tuple[dict | None, list[dict]]:
    """Read an artifact, tolerating the bare-list files written before v0.3.

    Those older files are exactly what this module exists to stop producing,
    so they come back with a `None` manifest rather than a synthesised one --
    the absence of provenance is the thing a reader needs to be told about.
    """
    document = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(document, list):
        return None, document
    return document.get("run"), document.get("findings", [])


def summarise(manifest: RunManifest, findings: list[dict]) -> str:
    """The one-line verdict printed after a run."""
    scanned = f"{manifest.files_scanned}/{manifest.files_total}"
    if not findings:
        return (
            f"clean: {scanned} files, 0 findings "
            f"({manifest.tool_version or manifest.tool})"
        )
    return (
        f"{len(findings)} findings over {scanned} files "
        f"({manifest.tool_version or manifest.tool})"
    )
