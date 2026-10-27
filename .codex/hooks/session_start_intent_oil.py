#!/usr/bin/env python3
"""Codex SessionStart entrypoint (IO2-104, IO2-041).

Registered (`--oil-root ...`): the shared local-only core through
`intent_oil.hooks.codex`. Invoked bare by an older adopted configuration: the
legacy bridge, unchanged, so its migration telemetry keeps counting it.
"""
from __future__ import annotations
import json,sys
def main():
    if "--oil-root" in sys.argv:
        from intent_oil.hooks.codex import run_hook
        return run_hook(allowed_events=("SessionStart",))
    from intent_oil.codex_bridge.retrieval import build_session_start_context
    try:p=json.loads(sys.stdin.read() or "{}")
    except Exception:p={}
    try:c=build_session_start_context(cwd=p.get("cwd"))
    except Exception as exc:c=f"Intent-Oil 2 WARNING: retrieval degraded ({type(exc).__name__}: {exc})."
    if c: print(c)
    return 0
if __name__=="__main__":raise SystemExit(main())
