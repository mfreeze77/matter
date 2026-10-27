#!/usr/bin/env python3
from __future__ import annotations
import json,sys
from intent_oil.hooks.post_tool_use import process_post_tool

def main():
    if "--oil-root" in sys.argv:
        from intent_oil.hooks.claude import run_hook
        return run_hook(allowed_events=('PostToolUse', 'PostToolUseFailure'))
    try: payload=json.loads(sys.stdin.read() or "{}")
    except Exception: payload={}
    try: context=process_post_tool(payload,cwd=payload.get("cwd"))
    except Exception:
        context=""
    if context:
        print(json.dumps({"hookSpecificOutput":{"hookEventName":payload.get("hook_event_name","PostToolUse"),"additionalContext":context}}))
    return 0
if __name__=="__main__":raise SystemExit(main())
