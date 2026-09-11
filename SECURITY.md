# Security

These scanners run a linter's own fixer over files you point them at, in a
temporary directory. They do not send anything anywhere and have no network
access of their own.

Two things worth knowing:

- **They execute the tool under test.** `ruff_fix_safety.py` shells out to
  `ruff`. Point it at a corpus you trust, for the same reason you would not run
  a formatter over untrusted input.
- **Output can contain source fragments.** Findings include the lines that
  changed, so a results JSON from a private codebase is as sensitive as that
  codebase. Paths are recorded relative to the corpus root, not absolute.

To report a problem with the scanners themselves, open an issue. There is no
private disclosure process here — nothing in this repository is deployed or
handles anyone's data.
