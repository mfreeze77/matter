# Ticket contract and workflow

The canonical backlog is `records/MAT-NNN.json`. [ticket.schema.json](../schemas/ticket.schema.json) is JSON Schema Draft 2020-12. Each individual [ticket page](INDEX.md), `index.json`, and [coverage report](../docs/COVERAGE.md) is a deterministic projection of canonical records and the requirement inventory.

## Required content

| Field group | Meaning |
|---|---|
| Identity and ownership | Stable ID, title, track, phase, priority, work type, target repository, and component |
| Scheduling | Explicit dependencies and recorded status; readiness is derived |
| Traceability | Requirement IDs and sources supporting the work |
| Implementation | Purpose, scope boundaries, concrete steps, planned artifacts, and reuse candidates |
| Acceptance | At least three identified criteria, each with a specific verification method |
| Tests and risks | Behavioral cases, relevant failure cases, and material limitations |
| Completion | Actual validation state and evidence; planned work uses `not_run` with no claimed completion |

## States

- `planned`: defined work that has not begun. The index shows `ready` only when all recorded dependencies are done.
- `in_progress`: implementation is underway; completion remains `not_run`.
- `blocked`: a recorded blocker prevents work even if graph dependencies are complete. Describe the blocker in the ticket.
- `done`: the required work and acceptance evidence exist. Dependencies must also be done, completion must be `passed`, and evidence must be nonempty.

Readiness is a planning calculation. It does not imply deployment approval, successful provider qualification, or that another repository has already been changed.

Phases are coarse ordered planning waves, not calendar estimates. A ticket may share a phase with its prerequisites, but it cannot precede one. The explicit dependency graph determines execution order within each phase. Independent corpus and annotation preparation can start early; common evaluation and release qualification remain separate prerequisites for later comparisons and rollout.

## Add or update a ticket

Use [the template](template.json) as a field guide. Give the record its final ID, remove template text, use concrete acceptance criteria, reference known requirements and dependencies, and write it under `records/` with a matching filename. The template is intentionally excluded from the backlog.

```bash
python -m matter render
python -m matter validate
python -m matter tickets --ready
```

Validation rejects malformed records, duplicate IDs and acceptance IDs, missing dependencies, cycles, phase inversions, unknown or uncovered requirements, stale generated files, orphan ticket pages, broken local documentation links, and completion without evidence. Detailed source/evidence correctness still requires review; JSON validation cannot establish that a claim is true.

## Scope of this delivery

MAT-001 records the scaffold milestone. MAT-002 records the executable structural and canonical-encoding contracts with their own validation evidence. The remaining records describe future implementation, integration, research, and qualification. Domain learning stays with DIAT; civic authority stays with its reviewed host; Oil controls and delivery stay under Oil's host boundary.
