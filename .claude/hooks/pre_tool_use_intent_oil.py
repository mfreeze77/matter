#!/usr/bin/env python3
"""Intent-Oil PreToolUse hook: the pre-commit hold (IO2-129). Advisory, bounded, fail-open.

This hook runs before EVERY shell call, so its common path must cost nothing. It reads the
payload with the standard library only and asks one cheap question: could this possibly be a
`git commit`? Nothing that says both "git" and "commit" (case-insensitively), or that uses a
JSON unicode escape (which could hide either word), can be one. Only then is Intent-Oil
imported and the exact detection (`hooks.post_tool_use.is_commit_command`) plus the hold run.
The prefilter may pass a non-commit through to the exact check; it must never drop a commit.
A call the prefilter drops leaves no receipt and no output.
"""
from __future__ import annotations
import sys

MAX_INPUT_BYTES = 1_048_576


def might_be_commit(raw: bytes) -> bool:
    """IO2-129 prefilter: False only when ``raw`` cannot hold a `git commit` invocation."""
    if b"\\u" in raw:                      # an escaped character could spell either word
        return True
    low = raw.lower()
    return b"commit" in low and b"git" in low


def main():
    if "--oil-root" not in sys.argv:
        return 0
    raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    if len(raw) <= MAX_INPUT_BYTES and not might_be_commit(raw):
        return 0
    import io
    sys.stdin = io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8")
    from intent_oil.hooks.claude import run_hook
    return run_hook(allowed_events=('PreToolUse',))


if __name__ == "__main__":
    raise SystemExit(main())
