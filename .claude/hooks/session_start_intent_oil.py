#!/usr/bin/env python3
from __future__ import annotations
import json,sys
from intent_oil.hooks.session_start import build_session_context

def main():
    if "--oil-root" in sys.argv:
        from intent_oil.hooks.claude import run_hook
        return run_hook(allowed_events=('SessionStart',))
    try: payload=json.loads(sys.stdin.read() or "{}")
    except Exception: payload={}
    try: context=build_session_context(cwd=payload.get("cwd"))
    except Exception as exc:
        context=f"Intent-Oil 2 WARNING: context injection degraded ({type(exc).__name__}: {exc})."
    if context:
        print(json.dumps({"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":context}}))
    return 0
if __name__=="__main__":raise SystemExit(main())
