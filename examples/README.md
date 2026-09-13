# A corpus you can run in ten seconds

`minimal-corpus/` holds three files, so the tool can be checked without cloning
sqlfluff and waiting forty minutes.

```bash
pip install sqlfluff
python scanners/sqlfluff_fix_safety.py examples/minimal-corpus out.json
```

Expected on sqlfluff 4.3.0:

```
3 fixtures, 2 dialects
  CORRUPTION  ansi/tilde_fusion.sql
  CORRUPTION  oracle/keyword_fusion.sql

  CORRUPTION  2
```

```json
[
  {
    "path": "ansi/tilde_fusion.sql",
    "dialect": "ansi",
    "kind": "CORRUPTION",
    "detail": ["SELECT 8 | ~~~4;"]
  },
  {
    "path": "oracle/keyword_fusion.sql",
    "dialect": "oracle",
    "kind": "CORRUPTION",
    "detail": ["SELECT a MULTISETEXCEPT b AS c FROM t;"]
  }
]
```

## What each file is for

| file | what it shows |
|---|---|
| `ansi/tilde_fusion.sql` | `8 \| ~ ~ ~4` → `8 \| ~~~4`. Three separate operators become one token that the dialect does not have. |
| `oracle/keyword_fusion.sql` | `MULTISET EXCEPT` → `MULTISETEXCEPT`. Two *keywords* welded, by `LT02` — a rule whose only job is indentation. This is the case that argues for guarding where fixes are applied rather than rule by rule. |
| `ansi/benign.sql` | Ordinary SQL that the fixer handles correctly. It has to be here: a scanner that flagged everything would "find" both bugs above and be worthless. |

Reported upstream as
[sqlfluff#8415](https://github.com/sqlfluff/sqlfluff/pull/8415).

**If these stop reporting `CORRUPTION`, that is good news, not a broken tool** —
it means the fix landed. The same thing already happened to this project's
original repro: `1 * - - 5` fusing into the comment marker `--` was fixed
upstream in [#8395](https://github.com/sqlfluff/sqlfluff/pull/8395), so it is
deliberately not used here.

## The other directory

[`rf06-guard-both-directions/`](rf06-guard-both-directions/) is not a corpus for
the scanner. It is a hand-verified pair showing sqlfluff's unparsable-fix guard
failing in *both* directions on one rule — declining a safe fix, and applying a
corrupting one. It also records the report that was closed as not-planned, and
why.
