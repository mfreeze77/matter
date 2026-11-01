# SDK structural-validation performance and public milestone API

Runtime pin: `eb6f563a6ce064e76eea50e5f864cf0353c1bb01`, SDK `matter-foundation==0.1.0.dev17`. This is separate from frozen dev16 at main `35f330ae44657db46bc443aff6823a088501c693`. The 1.0 and 1.1 schema/vector bytes are unchanged.

## Unprofiled consumer benchmark

The unchanged StateCivics `prototype.py` (one shared synthetic source, two audience-specific native host-rule decisions, a recorded executor, isolated in-memory captures) ran twice per SDK with no cProfile or network. Both returned digest/quiet, one capture, shared source and separate assessments. This measures native MAT-082 plumbing on the new SDK, not JEV latency or a live/provider-quality result.

Cold means a fresh Python process. Warm means a second call to the same unchanged script main in that process, with SDK caches retained but a new synthetic database and fresh clocks. It is not a replay returning cached command results.

- Cold: dev16 289.127s → dev17 32.763s for the full two-audience workload (8.82×).
- Warm: dev16 295.160s → dev17 30.411s for the full two-audience workload (9.71×).

Recorded execution phases fall from 63.6–69.1s per audience to 5.01–5.30s. The full workload averages roughly 16s per audience including shared setup, probes and both guarded handoffs; that average is not a throughput or production latency guarantee. Fresh timestamps/contexts mean much content is different between cold and warm runs. These are one cold/warm pair per SDK on a working Mac, not controlled-load confidence intervals. A separate original race test ran during part of the baseline; background workstation/rehearsal services also remained running.

Both use Python 3.11.17 and the existing image `ks-test-runner:matter-1f525c6` (`sha256:e6d1f7c98e5735e5dde8e74d121f4067391f40d18d65e8c1c4e5752eec72ef6e`). Baseline uses its installed dev16. The final wheel adds the same bounded structural cache to the opt-in 1.1 adapter, with no wire change. Candidate installs the wheel into a temporary target in the same image and verifies its imported module/version. Containers have network disabled, read-only root filesystems and 128MiB temporary filesystems. No StateCivics service/image is modified.

Retained small artifacts under `data/validation/manager-closeout-20261031/`: unchanged `prototype.py`, `bench.py`, `baseline.json/log`, `release-benchmark.json/log` (supersedes preliminary optimized runs), package inventory, tests and reviews. The harness removes synthetic stores after each run. Script SHA-256: `745e347f746c452e5b1b75ce7a9d7cfaa74509dfff151c294c4f73b94febf4fa`.

## Scope and safety

Successful structural validation is cached only after locally encoding and hashing the complete content. The cache binds exact canonical bytes, validator/registry identity and schema version; collisions still require byte equality. It retains at most 2,048 entries and 8MiB of encoded content, with detached decode on every return. Only success is cached. Bundled validators are immutable for process lifetime; new schema/registry/format semantics require a new validator instance. Fragment and domain validator pools are bounded at 128 to avoid reconstructing the same schema validators and defeating content-cache identity.

No storage read, freshness token, current head, policy, clock, authorization, revocation, dependency closure or capture permission is cached. SQLite still compares row identity, type, revision, recomputed snapshot digest and exact canonical bytes on every read. A warm-row corruption check changes schema-valid text while retaining the claimed digest and requires E_STORAGE_UNAVAILABLE. Cache tests also cover changed same-ID content, invalid input, schema/validator separation, detached values, digest collisions and bounded eviction.

## Public native milestone details

`matter.attention.build_delivery_milestone_details` is keyword-only: `decision`, `assessment`, `matter`, `purpose`, `audience`, `material_digest`, `delivered_at`. It returns the existing `attention-delivery-milestone` schema wrapper, with no storage or I/O. Consumers can replace private `matter._rule_values.domain` imports. It does not verify delivery or create assessment authority; native AttentionService still checks actual host receipts and refuses study output. See [attention API](../attention.md#public-host-milestone-details-builder).

## Pinned candidate package

- Wheel SHA-256: `1919681566fe261a537984f06d80a5df69a85cfeaf7dd4c16e81d4ef30c00194`.
- Packaged runtime files: 205, all byte-equal to the runtime candidate.
- Retained wheel: `data/validation/manager-closeout-20261031/wheel/matter_foundation-0.1.0.dev17-py3-none-any.whl`.
- 1.1 remains `monitoring-handoff/1.1.0`; no wire migration or new HostMonitoringState field is introduced by dev17.
- MAT-085 and MAT-086 record completion, with the final package/source identity above.

## Separate SQLite investigation

MAT-083 already owns the named cross-handle dispatch race and both intermittent failures; no duplicate ticket is needed. The unchanged installed dev16 race test passed in 53.027s in this investigation. The three named cases passed on the current candidate in 21.331s. Those results do not reproduce the retained failures or prove their causes repaired. The SQLite ticket remains open pending a controlled failing interleaving or demonstrated alternative cause; no blind retries, weakened assertions or storage-error relabelling were added.

No live JEV call, qualification, production delivery or activation is claimed.

## Executed verification checkpoints

- Initial broad run: 1,472 tests in 1,113.352s; 1,471 passed, one macOS test
  compared `/var/...` with the equivalent resolved `/private/var/...` backup
  destination. The implementation already resolves destination parents. The
  assertion now compares `destination.resolve()`; all 12 backup regressions pass
  in 0.258s. The final broad run on this runtime passed all 1,474 tests in 1,060.025s (no failures/errors/skips).
- Final wheel: 41 installed checks pass in 340.323s on Python 3.11 with provider
  network forbidden, no failures/errors/skips. They cover legacy and 1.1 schema
  inventories, exact thresholds/unknown, native-versus-study baselines, real
  receipt admission, shared-source access, in-flight revocation, duplicate and
  linked correction, atomic control-conflict recovery and production refusal.
- Post-review focused checks: 35 canonical/cache/builder checks pass. Strict
  decoder exhaustion stays a safe E_SCHEMA_INVALID in core and domain helpers;
  the corruption test restores the append-only trigger and asserts the actual
  stored-content integrity failure rather than accepting a missing-trigger error.
- Initial two-round review: 12 files, three findings (safe exception mapping,
  generated coverage omission, unused import), all addressed. Follow-up reviews:
  four files then five files, two rounds each, no findings or warnings.
- Three synthetic walkthroughs, generated projections/roadmap validation, and
  JavaScript's 26 canonical plus eight exact-source vectors pass. There are no
  live JEV calls or empirical provider qualification claims.

The task retains under 3MiB of small artifacts, one wheel and a profile diagnostic;
synthetic benchmark databases are deleted. No new Docker image was built. The
host had about 37GiB free before and 36GiB at the intermediate check; this is a
bounded small-output task, not a bulk storage/research run.

Final closeout: `render --check`, `validate` (86 tickets, 104 requirements, 108 schemas and three walkthroughs), `git diff --check`, all 1,474 final broad checks and 41 final installed checks pass. Canonical ticket/index review is recorded separately. StateCivics subsequently completed its dev17 receiving/image check, recorded below. The dev16 receipt alone did not establish acceptance of that later build.

## Dev17 receiving acceptance recorded

StateCivics completed its dev17 rebuild and receiving checks; see the [retained receipt](dev17-receiving.md). Matter independently checked the image ID and all 205 runtime file hashes. The reported 30 Matter/11 dispatch/35 PostgreSQL results and concurrent-load speed measurements are separate from the standalone benchmark above. KS-1148 adopted the public milestone builder. This closes the earlier receiving action for dev17, with no deployment, live-interpretation or qualification claim. The later [dev18 public classifier handoff](MAT-087.md) is an optional additive API migration.
