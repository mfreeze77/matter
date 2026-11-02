# MAT-092 planning record validation

Date: 2026-11-02. Scope: the Matter-owned ticket and permanent-storage decision,
based on Matter `e568e5894e4e80d0d7199cd4bd58c2496f570ad2` and the StateCivics
handoff at `5b38eab72489017a5fba5734a129840b7dcc188e`.

## Recorded change

[Decision 0003](../decisions/0003-permanent-host-storage.md) makes PostgreSQL
ledger storage and host-backed payload persistence prerequisites for StateCivics
production activation. It supersedes the proposed interim production mount and
temporary deployment/file-backup plumbing, retains the existing SQLite rehearsal
for comparison, and preserves coordination, recovery and SDK compatibility gates.

[MAT-092](../../tickets/MAT-092.md) is a planned Matter implementation ticket.
Its completion remains `not_run` with no completion evidence. README, storage,
assistant-review plan and receiving docs link the decision; ticket Markdown,
indexes and requirement coverage were regenerated from canonical JSON.

## Source review

Inspected the pinned StateCivics request and KS-1158 read-only. Checked
`matter_monitoring_host.py:project_source`, the objective/statewide packet
identity-hash construction, and Matter's `canonical_bytes`, `source_digest`,
`Storage` and `PayloadStore` boundaries. The mapping is packet lookup by
`packet_hash`, canonical reconstruction of `exact_material`, then exact-byte
payload digest/length verification. `evidence_hash` is not the payload digest.

Reviewed the core storage and assistant-review contracts, existing ownership
and reuse maps, SQLite transaction/hook documentation and MAT-074/MAT-091
compatibility context. This is source review by the editing agent, not an
independent review or a new rehearsal-store inventory.

## Executed checks

All commands used the existing repository `.venv` interpreter.

| Command | Actual result |
|---|---|
| `python -m matter render` | Passed; regenerated canonical ticket projections. |
| `python -m matter render --check` | Passed; no stale projections. |
| `python -m matter validate` | Passed; 92 tickets, 107 requirements, 110 schemas, three synthetic walkthroughs, no errors. |
| `python -m unittest discover -s tests -p test_repository.py -v` | 18 tests passed, including repository validity and negative graph/schema cases. |
| `python -m unittest discover -s tests -p test_hardening.py -v` | 21 tests passed, including malformed-input and unsafe projection-destination refusals. |
| `git diff --check` | Passed. |

The full runtime suite, PostgreSQL conformance, restore drills, installed-wheel
checks and connected StateCivics receiving tests were not run for this
documentation-only change. No runtime/backend code or downstream repository was
changed. These checks validate the planning records, not PostgreSQL behavior,
provider quality, live usefulness or production readiness.
