# Results

Each file here is one scan. From scanner **0.3.0** onward an artifact is a
manifest plus its findings:

```json
{
  "run": {
    "schema": "autofix-safety/run/1",
    "tool": "ruff",
    "tool_version": "ruff 0.16.7",
    "corpus": "cpython-3.12.10/Lib",
    "corpus_revision": null,
    "files_scanned": 1805,
    "files_total": 1805,
    "errors": 0,
    "complete": true,
    "flags": ["--select", "ALL", "--fix", "--unsafe-fixes"],
    "scanner_version": "0.3.0",
    "started_at": "2026-09-14T13:51:45Z",
    "duration_s": 843.0
  },
  "findings": []
}
```

The manifest is the point. A run that finds nothing writes `"findings": []`,
and without the block above that file is indistinguishable from a scanner that
crashed on startup, walked an empty directory, or was pointed at the wrong
corpus. This project's claim is that a clean run is a result; that only holds
if the clean run says what it actually did.

`complete` separates a finished scan from a checkpoint. The artifact is
rewritten every 100 files so a killed run still leaves something readable, and
those intermediate writes carry `"complete": false`.

## Artifacts written before 0.3.0

The three files below are bare JSON arrays with no manifest — they are the
exact problem the format above was introduced to fix (#9). They are kept as
they were rather than back-filled: the provenance for those runs exists only
as prose in the top-level README, and inventing a manifest from it would
assert machine-checked facts that were never machine-checked.

| file | tool | corpus | per the README |
|---|---|---|---|
| `sqlfluff-4.3.0-dialects-2026-09-09.json` | sqlfluff 4.3.0 | its own dialect fixtures | findings present |
| `ruff-0.16.7-fixtures-a65f3d6.json` | ruff 0.16.7 | ruff fixtures @ `a65f3d6` | clean |
| `ruff-0.16.7-cpython-3.12.10-lib.json` | ruff 0.16.7 | CPython 3.12.10 `Lib/` | clean |

Re-running any of them on 0.3.0 produces a self-describing replacement.
