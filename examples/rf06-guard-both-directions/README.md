# One rule, a guard wrong in both directions

sqlfluff refuses to apply a fix when it works out the result would not parse.
These two files show that check failing in opposite directions on the same
rule, `RF06`.

Verified by hand through the CLI — not through the scanner — on sqlfluff 4.3.0
at commit `818243e2`.

## A. The safe fix it declines

```bash
sqlfluff parse --dialect mysql declined_but_safe.sql   # parses, no unparsable segments
sqlfluff lint  --dialect mysql --rules RF06 declined_but_safe.sql
# L: 1 | P: 18 | RF06 | Unnecessary quoted identifier `testprocedure`.

sqlfluff fix --dialect mysql --rules RF06 --force declined_but_safe.sql
# WARNING  Fixes for RF06 not applied, as it would result in an unparsable file.
#          Please report this as a bug with a minimal query which demonstrates this warning.
```

The file is left unchanged and the violation stays. But the output it refused to
write is fine — unquote it by hand and sqlfluff parses it and reports nothing:

```sql
CREATE PROCEDURE testprocedure(in test int)
BEGIN
END~
```

```
All Finished!
```

So the guard declined a fix that was safe to apply.

## B. The corrupting fix it applies

```bash
sqlfluff fix --dialect mysql --rules RF06 --force applied_but_broken.sql
# == [applied_but_broken.sql] FIXED
```

```sql
CREATE USER jeffrey@localhost;
```

```bash
sqlfluff parse --dialect mysql applied_but_broken.sql
# 2 unparsable segments
```

`'jeffrey'@'localhost'` is one MySQL account specification, not two quoted
identifiers. Here the guard did not fire at all, and the corruption was written
to disk. Reported as
[sqlfluff#8462](https://github.com/sqlfluff/sqlfluff/issues/8462).

## Why this pair is in the repository

The first case was reported as
[sqlfluff#8466](https://github.com/sqlfluff/sqlfluff/issues/8466) and **closed
as not-planned** — the report was filed before the cause was understood and then
corrected twice, so the maintainer reasonably asked for one clear issue instead
of three versions of one.

These files are the manual reproduction that should have existed before that
issue was opened. They are kept here as an example of the check's limits, and of
the difference between a scanner hit and a report.

The underlying mechanism, for whoever picks it up: `FunctionNameSegment` accepts
`TypedParser("word")` or a quoted identifier, and `RF06` builds its replacement
from the dialect's `NakedIdentifierSegment`, a `RegexParser`. The new segment's
type fits neither branch, so the re-match returns nothing and the whole fix is
dropped — even though the *text* would lex and parse correctly.
