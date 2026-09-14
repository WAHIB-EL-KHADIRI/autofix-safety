"""Round-trip a linter's own test corpus through its --fix mode.

    If an input parses cleanly, its fixed output must parse cleanly too.

Two adapters implement that invariant. They share nothing but the idea, on
purpose: each tool needs its own oracle, and the ruff adapter's oracle is
CPython's `ast.parse` rather than ruff itself.
"""

__version__ = "0.2.0"
