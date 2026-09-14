# autofix-safety

Round-trip a linter's own test corpus through its `--fix` mode and check that
the output is still valid.

```
If an input parses cleanly, its fixed output must parse cleanly too.
```

That single invariant found a data-loss bug in sqlfluff, a 9.8k-star SQL linter
that many teams run with `--fix` in CI.

## The problem

Auto-fix is the only part of a linter that *writes* to your code. Everything
else reads. And it usually runs unattended, across a whole repository, with
nobody reading the diff.

Projects test that fixtures **parse**, and they test that each rule's fix does
what that rule intends. The composition — *fix the whole corpus, then re-check
it* — is rarely tested, because it belongs to no single rule's test file.

## The approach

For every file in the corpus:

1. Parse it. If it does not parse, skip it — a pre-existing parser gap is not a
   fixer defect, and conflating the two is the fastest way to get an issue
   dismissed.
2. Run the fixer.
3. Parse the output.
4. Run the fixer again and compare, to catch non-convergence.

Findings are classified, in this precedence:

| class | meaning |
|---|---|
| `FIX_CRASH` | the fixer raised or exited non-zero |
| `CORRUPTION` | parsed before the fix, does not parse after |
| `COMMENTED` | parses after, but the fix introduced a comment — text was swallowed |
| `GUARDED` | the tool detected its own fix would corrupt and declined to apply it |
| `UNSTABLE` | fixing twice does not converge |

**`CORRUPTION` is the only class that is a finding on sight.** The rest are
hypotheses. See [Triage](#triage) — it is the part that matters.

### On oracles

The sqlfluff scanner asks sqlfluff whether it can re-read its own output. That
is a weakness: in principle a lexer bug could hide itself.

The ruff scanner does not have that problem. Python's own `ast.parse` is the
judge — the reference implementation of the language, with no stake in ruff
being correct. **Where an independent oracle exists, use it.**

## Install

```bash
pipx install "autofix-safety[ruff] @ git+https://github.com/WAHIB-EL-KHADIRI/autofix-safety"
```

or, inside an environment that already has the tool you want to scan:

```bash
pip install "git+https://github.com/WAHIB-EL-KHADIRI/autofix-safety"
```

Two commands land on your path: `autofix-safety-sqlfluff` and
`autofix-safety-ruff`.

**The package declares no hard dependencies, deliberately.** Each adapter drives
whichever `ruff` or `sqlfluff` is already installed in the environment you point
it at. Pinning a version here would mean scanning a different build of the tool
than the project under test actually uses — which is the one thing that makes a
finding worthless. The `[ruff]` and `[sqlfluff]` extras exist for when you have
no preference.

## Usage

```bash
# sqlfluff: run from a checkout that has sqlfluff installed
autofix-safety-sqlfluff test/fixtures/dialects out.json
autofix-safety-sqlfluff test/fixtures/dialects out.json mysql   # one dialect

# ruff: any directory of Python files, not just ruff's own
autofix-safety-ruff path/to/corpus out.json
autofix-safety-ruff path/to/corpus out.json --safe-only
```

Output is a JSON array of findings with paths relative to the corpus root.
Write to a file rather than piping — a long run buffers and you see nothing.

### Check it works in ten seconds

You do not need sqlfluff's 2,262-fixture corpus to see the tool do something.
[`examples/minimal-corpus`](examples/) in this repository is three files:

```bash
pip install sqlfluff
autofix-safety-sqlfluff examples/minimal-corpus out.json
```

Two of the three should come back `CORRUPTION`; the third is ordinary SQL and
must not, because a scanner that flags everything finds nothing.

## Reproducible results

Every number below came from a completed run on this machine. Commands and
versions are given so they can be checked rather than believed.

**Environment for all three:** Windows 10, Python 3.12.10, single process.

### 1. sqlfluff — 8 corruptions

| | |
|---|---|
| tool | sqlfluff 4.3.0 |
| corpus | `sqlfluff/test/fixtures/dialects` at commit `85dfbdff` |
| size | 2,262 fixtures, 28 dialects |
| command | `autofix-safety-sqlfluff test/fixtures/dialects out.json` |
| result | **8 `CORRUPTION`, 29 `UNSTABLE`** |
| runtime | ~40 min |

The 8 corruptions are two root causes, not eight bugs:

- **Token fusion** (`ansi/arithmetic_a`, `sqlite/arithmetric_a`,
  `oracle/multiset_operators`) — removing whitespace welds two tokens into a
  different one, so the file the fixer writes lexes differently from the one it
  read. Verified on `85dfbdff`: `SELECT 8 | ~ ~ ~4;` → `SELECT 8 | ~~~4;`, and in
  Oracle two *keywords*, `MULTISET EXCEPT` → `MULTISETEXCEPT` — welded by `LT02`,
  a rule whose only job is indentation. Reported as
  [sqlfluff#8415](https://github.com/sqlfluff/sqlfluff/pull/8415), with a fix.

  A fourth case, `1 * - - 5` fusing into the comment marker `--`, was in the
  original run and is **no longer reproducible**: upstream fixed that instance in
  [#8395](https://github.com/sqlfluff/sqlfluff/pull/8395) on 2026-09-05. It is
  mentioned here because a stale repro is worse than no repro, and because it is
  the argument for guarding at the token layer rather than per rule — the class
  outlives each individual patch.
- **`RF06` vs account specifications** (`mysql/create_user`, `mysql/grant`,
  `mariadb/create_user`, `mariadb/grant`,
  `mariadb/create_view_if_not_exists`) — `'user'@'host'` is MySQL syntax, not
  two quoted identifiers. Reported as
  [sqlfluff#8462](https://github.com/sqlfluff/sqlfluff/issues/8462).

Raw output: [`results/sqlfluff-4.3.0-dialects-2026-09-09.json`](results/sqlfluff-4.3.0-dialects-2026-09-09.json).

### 2. ruff, its own fixtures — nothing

| | |
|---|---|
| tool | ruff 0.15.20 |
| corpus | `ruff/crates/ruff_linter/resources/test/fixtures` at commit `b5dba861c` |
| size | 1,607 files |
| flags | `--select ALL --fix --unsafe-fixes` |
| result | **0 `CORRUPTION`, 0 `FIX_CRASH`, 0 `UNSTABLE`** |

`--unsafe-fixes` is included deliberately. Ruff's contract for an unsafe fix is
that it *may change the meaning* of the code; it is nowhere promised that it may
produce output that is not Python.

### 3. ruff, the CPython standard library — nothing

| | ruff 0.15.20 | ruff 0.16.7 |
|---|---|---|
| corpus | CPython 3.12.10 `Lib/`, excluding `site-packages` | same |
| size | 1,805 files | 1,805 files |
| flags | `--select ALL --fix --unsafe-fixes` | same |
| date | 2026-09-10 | 2026-09-14 |
| result | **0 findings** | **0 findings** |

Raw output for the re-scan:
[`results/ruff-0.16.7-cpython-3.12.10-lib.json`](results/ruff-0.16.7-cpython-3.12.10-lib.json)
— which is `[]`, and on its own proves nothing. The provenance that makes it
meaningful lives in the table above rather than in the file; that asymmetry is
tracked in [#9](https://github.com/WAHIB-EL-KHADIRI/autofix-safety/issues/9).

Curated fixtures are a weaker adversary than they look — each exercises one
construct. CPython's `Lib/` includes the CPython test suite, which contains
every syntactic edge the language has, plus deliberately invalid files (those
are skipped by the before-state check).

The re-scan exists because a clean result expires. 0.15.20 → 0.16.7 is a whole
minor series of new and changed fixes, and "ruff was clean four days ago" is not
a claim about the ruff anyone is running today. Re-running is cheap; leaving a
stale negative result standing is not.

**Two clean runs is a real result about ruff, and it is reported here for the
same reason the failures are.** A method that publishes only its hits is a sales
pitch.

## Triage

Finding candidates is easy. Knowing which are real is the work.

- **`UNSTABLE` is almost always noise.** sqlfluff's CLI loops the fixer until
  output stabilises, so one unconverged pass is expected behaviour. 9 of the
  first 10 findings on the first run were this.
- **Measure the before state.** `ALTER USER 'x'@'y'` fails to parse after the
  fix — and before it. That is a parser gap, not corruption. One soft claim next
  to a hard one gets both discounted.
- **Comparing all code tokens does not work.** It fires on every legitimate fix:
  added commas, capitalised keywords, dropped parens. The narrow invariant
  ("a fix never introduces a comment") is the one that survives a real corpus.
- **Extracted statements lie.** A statement pulled out of a fixture may not
  parse standalone even when the whole file does. Minimise from the real
  fixture, then re-verify against it.
- **Read the log, not just the findings.** `GUARDED` exists because sqlfluff
  prints *"Please report this as a bug"* when it declines its own fix — and the
  scanner was discarding that as noise.
- **A scanner hit is not a report.** The `GUARDED` class produced
  [sqlfluff#8466](https://github.com/sqlfluff/sqlfluff/issues/8466), which was
  **closed as not-planned** — not because the behaviour was imagined, but
  because the report was filed before the cause was understood and then
  corrected twice in public. The maintainer's words are worth quoting, because
  they are the most useful feedback in this repository's history:

  > *"This issue was opened, then reframed twice. Please review your findings
  > again, reproduce manually, and open a clear issue."*

  Correcting yourself in the open is right **after** filing wrong. It is not a
  substitute for being right at filing time, and the second correction spends
  more credibility than the first one earns. Root-cause it, measure the whole
  scope, build one manual repro, then file once.

## Limitations

- **Not a fuzzer.** It only sees what is in the corpus you point it at.
- **`CORRUPTION` means "does not parse", not "is wrong".** Output that parses
  but has changed meaning is largely invisible; `COMMENTED` covers one narrow
  case of it.
- **`GUARDED` is sqlfluff-specific.** It matches that project's warning text.
  Other tools would need their own pattern.
- **Single process.** `ProcessPoolExecutor` hung on Windows during development,
  so it was not pursued. A 2,000-file sqlfluff run takes about 40 minutes.
- **Two adapters, not a framework.** The invariant generalises to any fixer with
  a validator and a corpus; nothing here auto-discovers one for you.

## Requirements

Python 3.11+. `sqlfluff` for the sqlfluff scanner, `ruff` for the ruff scanner —
neither is needed to run the other.

## License

MIT. See [LICENSE](LICENSE).
