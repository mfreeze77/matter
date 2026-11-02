# Decision 0003: permanent host storage before StateCivics production activation

**Status:** adopted by the owner, 2026-11-02. Backend implementation is planned
in [MAT-092](../../tickets/MAT-092.md); this decision does not activate production.

## Context and authority

StateCivics' [PostgreSQL request](https://github.com/mfreeze77/state-civics-ai/blob/5b38eab72489017a5fba5734a129840b7dcc188e/docs/MATTER-REQUEST-2026-11-02-postgres-storage-backend.md)
and [KS-1158](https://github.com/mfreeze77/state-civics-ai/blob/5b38eab72489017a5fba5734a129840b7dcc188e/tickets/KS-1158-matter-store-custody-interim-directory-then-postgres-backend.md)
were merged at `5b38eab72489017a5fba5734a129840b7dcc188e`. The owner's current
instruction rejects work on a temporary production storage arrangement and
directs Matter to record the permanent path. That instruction supersedes the handoff's
"Until then" mount proposal and its request for approval of `data/matter`.

At this intake, Matter is based on `e568e58`; the receiving handoff records
StateCivics' SDK pin as `401f1a4` (dev20). Recording this decision neither updates
that pin nor supplies a PostgreSQL implementation. MAT-083 excluded PostgreSQL;
its completed contention investigation is not backend acceptance.

The [assistant-review contract](../contracts/assistant-review.md) keeps host
sessions, findings and evidence under StateCivics ownership and stores their
pointers plus Matter's review/pressure/control state. That boundary is not a
claim that all Matter records contain only pointers: observation payloads and
semantic execution receipts can retain exact evidence and model material.
Pending pressure, claims and historical pins also require durable recovery;
the ledger must not be treated as a disposable cache.

## Decision and ownership

StateCivics production activation requires both **PostgreSQL ledger storage and
host-backed payload persistence**, with connected receiving and recovery checks
completed. There will be **no interim production mount**, `MATTER_STORE_ROOT`
directory rollout, or associated temporary deployment/file-backup plumbing.
Activation waits for the permanent path; no production SQLite migration or
temporary fallback is presumed necessary.

Keep the existing SQLite rehearsal and its evidence as a comparison and
verification reference. SQLite remains a supported reference backend for replay
and conformance; this StateCivics activation decision does not impose PostgreSQL
on every Matter consumer. Real rehearsal stores and payloads stay outside this
repository; use synthetic fixtures here and external artifact references.

- **Matter / MAT-092:** implement the neutral PostgreSQL `Storage` backend,
  preserve the existing `PayloadStore` contract, supply shared behavioral
  conformance and recovery checks, and document the host integration boundary.
  Reuse the current ports, guards, canonical encoding and test scenarios.
- **StateCivics / KS-1158:** supply connections, roles and place/schema mapping;
  implement its evidence and response-artifact payload adapter; wire backend and
  worker coordination; include ledger, payloads and required host/sweep receipts
  in its permanent recovery arrangement; perform associated storage receiving
  and recovery acceptance. Encryption remains KS-637/KS-1152 work. The
  production dispatcher (KS-1127) and activation remain separate StateCivics/owner
  work. Matter does not implement those host changes through this ticket.

The host supplies a synchronous psycopg connection factory or pool lease,
matching Matter's synchronous handlers. Connection lifecycle and transaction
ownership must be explicit: a successful Matter command must already be durable
when returned, and Matter must not silently commit or roll back unrelated host
work. Sharing PostgreSQL does not make the claim/call/complete workflow one
atomic transaction. Existing wake identity and unknown-outcome reconciliation
remain necessary. Host clients, civic vocabulary and deployment choices stay
outside the neutral core.

## Exact evidence and payload mapping

The handoff correction is part of the receiving contract:

1. `evidence_hash` is the SHA-256 of the packet's **identity object**. It is not
   Matter's payload digest and must not be used as one.
2. The host locates the authorized packet row by `packet_hash`, using the
   existing packet identity/locator. The storage ports do not become a second
   evidence repository or a generic locator-fetching service.
3. Reconstruct exact payload bytes from that row's `exact_material` with
   Matter's `canonical_bytes`. Derive the payload digest with `source_digest`
   (unframed SHA-256 of those bytes) and verify it, and the byte length, against
   the Matter content reference before returning bytes.
4. Missing, withheld, foreign-scope or changed material must preserve the
   existing explicit availability/error behavior. A mismatch cannot silently
   rewrite an observation or substitute another packet.

The digest-only `PayloadStore` interface does not itself resolve a host packet
row. The host adapter must retain or derive a scope-bound association between
the payload digest and `packet_hash`, verify it against canonical bytes, and
support both `put` and `read` without relaxing guards. Raw model responses need
durable host-owned artifact storage keyed by their exact byte digest; they are
not reconstructed from evidence packets. Payload publication must satisfy the
existing durability contract before a ledger reference can be committed.

The handoff reports 14 payload files with 63 KB of content and 96 KB on disk,
and a 43 MB rehearsal ledger after captures and sweeps. These are attributed
receiving observations, not newly measured inventories or sizing guarantees.

## Coordination, recovery and compatibility gates

- Preserve atomic versions, heads, watches, command journal, operation receipt
  and exact result; checked current and historical reads; immutable canonical
  bytes/digests; scoped identity and guarded retry disclosure. A terminal
  refusal must roll back handler writes while retaining the appropriate
  failure receipt. Database failure must not appear as successful empty data.
- Replace filesystem coordination with database/host coordination, including
  a per-scope advisory lock or a proven equivalent that protects absent reads
  and competing discoveries. Locks on existing rows alone are insufficient.
  Preserve the logical per-lens review exclusion across revisions and matters;
  a transaction-scoped lock alone does not span the external assistant call.
  Define bounded waits and deterministic acquisition/release, and prove the
  backend and worker share the same coordination scope.
- Preserve transaction-hook timing and rollback, current control/access checks,
  and post-commit effects only after a known commit. An uncertain commit needs
  exact-command reconciliation, not a blind rerun of a handler or assistant.
- Verify an actual restore into a separate target with consistent ledger and
  host payload/artifact recovery: canonical bytes, histories, current heads,
  watches, exact retries, pending pressure and unresolved wakes must survive.
  Schema checksums or row counts alone cannot establish recoverability. Host
  backup/encryption ownership stays with StateCivics, including KS-1152.
- Keep SDK/image, schema/semantic versions, ledger and payload recovery
  compatible. PostgreSQL custody does not make older SDKs support newer stored
  meanings. Refuse unsupported versions and document one-way boundaries;
  rollback requires a compatible recovery set, not just an older image.

MAT-092 remains `planned` with completion `not_run`. Matter acceptance requires
real PostgreSQL concurrency/recovery evidence and comparison with SQLite.
StateCivics connected receiving evidence is an additional activation prerequisite.
The [planning validation receipt](../validation/MAT-092-planning.md) records the
checks on these documents and ticket projections. This planning change does not
modify runtime code, frozen monitoring/review wires, provider qualification or
any downstream repository. It does not claim production readiness.
