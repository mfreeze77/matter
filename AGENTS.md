# Working in Matter

Follow the user's current task and scope. Read README.md, the relevant governing contract, and the selected canonical ticket before implementation.

- Keep the common core independent of Oil, civic vocabulary, JEV, and speaker identity. Put specialized meaning in explicit profiles and adapters.
- Preserve evidence origin, scope, availability, uncertainty, and derivation. A model judgment does not acquire source authority or permission to act.
- Direct user instructions, corrections, and stop signals use the host control path. Do not buffer them as ordinary evidence awaiting importance.
- Treat the root starter notes as design history. Governing contracts and recorded decisions resolve their older shorthand; user instructions take precedence.
- Scope tickets to their declared owner. This repository's roadmap does not by itself authorize changes or deployment in Oil, StateCivics, the crawler, or DIAT.
- Keep real audio, transcripts, embeddings, identity labels, credentials, and evaluation corpora out of this repository. Use synthetic examples and external artifact references.
- Inspect the existing owners and reuse maps before introducing replacement clients, retrieval, storage, or orchestration infrastructure.
- Edit canonical ticket JSON. Regenerate its Markdown/index, run validation, and record actual evidence before marking work done.
- Use behavioral tests that can detect incorrect outcomes. Keep source review, synthetic checks, provider evaluation, and live usefulness separate in reports.
- Preserve unrelated concurrent changes. Commit coherent progress on a task branch; provide a reviewable PR and accurate limitations.

## Local checks

```bash
python -m matter render --check
python -m matter validate
python -m unittest discover -s tests -v
```

Full implementation targets remain in the backlog. Do not describe the scaffold's synthetic walkthrough as a qualified runtime or identity system.

<!-- intent-oil:begin (managed by `oildrop full`; edit outside the markers) -->

## Intent-Oil (observational; no closeout)

Intent-Oil watches this repository through host hooks. Normal work needs no Oil step: do not run
closeout commands or record memory for Oil's sake. The full set of standing rules comes at session
start (and again after a compaction); a prompt gets only the rules and ticket decisions for the files
and tickets in play (the branch, this branch's own commits, the files edited or modified).
`.oil/RULES.md` is generated from the ledger, never edited by hand. Ticket decisions are ingested from
the ticket files on the commit that changes them.

**Sessions a script launches with a brief** (`claude -p`, `codex exec`, an orchestrator): set
`INTENT_OIL_PROMPT_AUTHOR=agent` in that process's environment. The hooks still serve context and
deliver findings; the brief is not captured as the operator's intent. Nothing in a hook payload marks
a session as headless, so this is the only seam. Subagents spawned from inside a session need nothing:
they arrive with an agent id and nothing is captured from them. Do not put the variable in a settings
file the operator's own sessions read.

**Repository intent graph (MCP server `exais-intent-graph`, deterministic, no model).** Available to
this session and to subagents. Pass the `vector_store_id` named in the session-start context, or
read it from `intent-oil doctor`.

- `search_repository(query, kind?)`: start here when you have a question and no id. Free-text search
  through the graph lens; every hit names the tool to follow it (a function, a commit, a ticket).
- `ticket_context(ticket_id)`: the commits that address a ticket, the code that cites it, and drift.
  Call it before changing code a ticket owns.
- `why_is_this_here(function_id)`: which tickets a function serves and which commits changed it.
  Use a canonical id, repository-relative file, `file#symbol` (including `Class.method`), or
  `file:line`. Files and ambiguous names return bounded candidates to follow; an interior
  line needs an indexed source range. Every answer carries per-query freshness.
- `commit_context(sha)`: what one commit addresses or mentions, and what it changed.

The graph is rebuilt in the background after commits and can lag: the session-start context states
"indexed through <commit>, N behind HEAD". "Nothing indexed" for very recent work means stale, not
absent. `intent-oil doctor` reports the graph's age, the core's liveness and the hooks' state.

<!-- intent-oil:end -->
