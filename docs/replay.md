# Chronological core replay

`ReplayManifest` binds a frozen MAT-036 corpus, explicit metadata clock cuts,
profiles, controls, source requirements, operation recipes and golden frames.
`run_replay` gives a registered trusted core driver only the admitted byte-verified
prefix. It never supplies case labels, expected frames or future source artifacts.
The driver reuses existing service ports on a fresh store. No new rehearsal stack,
provider client or notification transport is selected by these manifests.

The portable golden format compares conclusions, logical receipt IDs/outcomes,
quiet reasons, allowed transitions and delivery counts. Exact native records stay
in the local store; storage execution timestamps/digests are not portable semantic
expectations. A driver must explicitly list source usage; the runner refuses use
outside the prefix. The synthetic core driver also checks actual ingested hashes.
Golden expectations are conformance examples, not independent semantic labels.

Recorded judgments retain unknown/unqualified status. Replay never issues a
qualification certificate. Race and transport fault schedules are separately
referenced and are not executed by a sequential replay. An early effective date
cannot make a late-published source available in an earlier prefix. Input gating
does not establish that a pretrained model lacks outside knowledge.
