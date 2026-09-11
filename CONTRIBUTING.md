# Contributing

The useful contribution here is **a new adapter**, not more features in the
existing two.

## Adding an adapter

A tool qualifies if it has an auto-fix mode, a way to validate output, and a
corpus. Prefer an oracle that is *not* the tool under test — the ruff adapter
uses `ast.parse` for exactly this reason.

Keep the four checks and their precedence. They were arrived at by being wrong
first, and the ordering matters: `CORRUPTION` before `COMMENTED` before
`GUARDED` before `UNSTABLE`.

## Before you report anything upstream

Read the Triage section of the README. Short version:

- `UNSTABLE` is a hypothesis, never a finding.
- Measure the before state — a pre-existing parse failure is not a fixer bug.
- Minimise from the real corpus file, then re-verify against it.
- **Re-run the repro against the project's current `main` before filing.** A
  claim about someone else's code has a shelf life; one of the findings in this
  repository was fixed upstream between the run and the writeup.

A report that mixes one soft claim with three hard ones gets all four
discounted.

## Tests

```bash
pip install pytest ruff sqlfluff
python -m pytest tests/ -q
```

The sqlfluff tests skip if sqlfluff is not installed, and the ruff tests skip if
ruff is not on the path.
