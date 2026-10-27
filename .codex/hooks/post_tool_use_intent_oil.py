#!/usr/bin/env python3
"""Codex PostToolUse entrypoint (IO2-104, IO2-041).

Registered (`--oil-root ...`): the shared local-only core through
`intent_oil.hooks.codex`. Invoked bare by an older adopted configuration: the
legacy bridge, unchanged, so its migration telemetry keeps counting it.
"""
from __future__ import annotations
import json,sys
from pathlib import Path
def main():
    if "--oil-root" in sys.argv:
        from intent_oil.hooks.codex import run_hook
        return run_hook(allowed_events=("PostToolUse",))
    from intent_oil.codex_bridge.auto_debugger import process_post_tool_use
    try:p=json.loads(sys.stdin.read() or "{}")
    except Exception:p={}
    try:c=process_post_tool_use(p,repo_root=Path(p.get("cwd") or ".").resolve())
    except Exception:c=""
    if c: print(c)
    return 0
if __name__=="__main__":raise SystemExit(main())
