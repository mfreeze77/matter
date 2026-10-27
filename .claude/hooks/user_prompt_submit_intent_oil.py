#!/usr/bin/env python3
from __future__ import annotations
import json,sys
from intent_oil.hooks.user_prompt_submit import build_prompt_context

def main():
    if "--oil-root" in sys.argv:
        from intent_oil.hooks.claude import run_hook
        return run_hook(allowed_events=('UserPromptSubmit',))
    try: payload=json.loads(sys.stdin.read() or "{}")
    except Exception: payload={}
    try: context=build_prompt_context(prompt=payload.get("prompt",""),cwd=payload.get("cwd"))
    except Exception as exc:
        context=f"Intent-Oil 2 WARNING: prompt retrieval degraded ({type(exc).__name__}: {exc})."
    if context:
        print(json.dumps({"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":context}}))
    return 0
if __name__=="__main__":raise SystemExit(main())
