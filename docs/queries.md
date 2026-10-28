# Recorded inspection and explanations

`QueryService.project` composes the existing identity, assessment, attention and
outbox readers in one SQLite snapshot under the caller's **current** READ rights.
It returns records and recorded reasons, never generated justification or action
permission. Pass exact assessment/attention/authorization references, or an exact
profile/purpose/audience lane. A quiet decision retains its recorded reason:
already delivered differs from insufficient evidence. An authorized send remains
`delivery_unknown` until a transport observation establishes its outcome.

The `as_of` parameter selects metadata committed by the storage knowledge clock;
the explanation retains the assessment's original policy and evidence cut.
History does not confer current access. A missing historical identity mirror is
an untouched singleton at that cut. Historical full child discovery is explicitly
incomplete because current reverse indexes do not retain a historical catalog.
Select an original assessment to reconstruct its exact evidence and disagreements.

A cursor binds scope, principal, selection and every read pin. A changed identity
partition, lane or delivery attempt invalidates it; the caller restarts pagination.
Each page is internally consistent, including a split committed by another store
during the read. Missing blobs yield unavailable reconstruction and incomplete
flags. Payload reads are opt-in and checked against their original source digest.
No dashboard, native transport or language-model explanation writer is added.

Explanations use only the selected assessment's recorded references. Other current
children remain in the inventory and do not become that assessment's evidence.
Source/judgment/citation details follow the records page; `records_complete`
identifies a partial explanation page. A future storage-history cut is refused.
