# Changelog

Derived from the project's two published releases and the commits between
them. Full release notes: <https://github.com/WAHIB-EL-KHADIRI/autofix-safety/releases>.

There is no `v0.2.0` tag: the version moved 0.1.0 -> 0.2.0 -> 0.3.0 without the
intermediate point being published, and tagging it retroactively would mark a
tree nobody installed.

## [0.3.0] - 2026-09-16

### Changed

- **Breaking:** every result artifact is now a run manifest plus its findings
  (`{"run": {...}, "findings": [...]}`) instead of a bare JSON array, so a clean
  run is distinguishable from a scanner that crashed or scanned nothing. The
  manifest is written at the first checkpoint; intermediate writes carry
  `"complete": false`. Existing files under `results/` predate this and are
  deliberately not back-filled (see `results/README.md`).
- The ruff adapter reports progress and checkpoints on a clean run.
- `TIMEOUT` is now its own class, separate from `FIX_CRASH`.

### Added

- One-command installation straight from the repository.
- CodeQL analysis.
- A code of conduct, and triage turned into an issue form.
- A record of one report that was rejected upstream, with the reason, plus the
  hand-verified RF06 example pair.

### Results

- Both ruff corpora re-scanned on ruff 0.16.7 (1,607 ruff fixtures, 1,805
  CPython `Lib` files, `--select ALL --fix --unsafe-fixes`): still no findings.

### Internal

- The repository is now linted with ruff.

## [0.1.0] - 2026-09-11

First tagged version.

### Added

- Round-trip scanner: every file in a corpus is passed through a linter's
  `--fix`, and the result is classified as `FIX_CRASH`, `CORRUPTION`,
  `COMMENTED`, `GUARDED` or `UNSTABLE`. Only `CORRUPTION` is a finding on sight.
- Two adapters: sqlfluff and ruff. The ruff adapter uses CPython's `ast.parse`
  as its oracle rather than the tool under test.

### Results

| Corpus | Tool | Size | Result |
|---|---|---|---|
| sqlfluff `test/fixtures/dialects` @ `85dfbdff` | sqlfluff 4.3.0 | 2,262 | 8 `CORRUPTION`, 29 `UNSTABLE` |
| ruff's own fixtures @ `b5dba861c` | ruff 0.15.20 | 1,607 | 0 |
| CPython 3.12.10 `Lib/` | ruff 0.15.20 | 1,805 | 0 |

### Notes

- One original finding (`1 * - - 5` fusing into `--`) no longer reproduces; it
  was fixed upstream in sqlfluff#8395 between the run and the writeup.

[0.3.0]: https://github.com/WAHIB-EL-KHADIRI/autofix-safety/compare/v0.1.0...v0.3.0
[0.1.0]: https://github.com/WAHIB-EL-KHADIRI/autofix-safety/releases/tag/v0.1.0
