# Civic profile and reviewed-authority contract

MAT-046 is an optional `matter.civic` adapter over the common profile contract.
The existing `matter.profiles` module remains neutral. Legal categories, body IDs,
source stages and capability names are opaque profile data; Matter does not
decide which real body has legal power.

`CivicProfile(value, profile=installed_common_profile)` validates the packaged
schema digest, exact common profile, producer/code digests, scope, periods and
source/review references. Its reference hashes all manifest content. An assertion
reference binds its declaration, source hashes, parent references and common
profile while excluding its review fields, avoiding a circular review digest.
Parent chains are exact and bounded. Overrides must explicitly name an ancestor
assertion and narrow its selector; unresolved equally applicable disagreements
return conflict rather than the most permissive value.

`CivicRegistry.resolve(..., selector, capability, at, as_of, view, controls, token)`
uses one existing storage snapshot and a current READ token. It checks actual
observation hashes and availability. A reviewed assertion needs an actual registered
host control with a `civic-review` payload bound to that assertion, common profile,
scope and review time. The granting control must target exactly its source records. Currentness is
checked per assertion through bounded registered source-fence history (256
revisions newer than the oldest selected review per fence, 4096 distinct controls maximum). Unrelated reviews cannot
displace one another. Later matching withdrawals on overlapping or scope-wide
targets remain effective after unrelated dispositions. Older unrelated scope-wide history is skipped. Exceeding the scan bound
refuses the result with `review_history_scan_limit_re_review_required`; a fresh
host review recovers the boundary without deleting history or reusing an old grant. A
parser `final` tag, supported source or copied host-looking JSON cannot substitute
for a registered current host review. Withdrawn, superseded, future or disputed
review cannot enable the host-proposal gate. The caller owns access/egress and
the final action, budget and freshness boundaries.

The result distinguishes unknown, resolved and conflict; it retains exact
dependencies. `eligible_for_host_proposal` is only a domain-evidence condition.
`consequential_use` stays false and no action is emitted. No source, model answer
or manifest grants a user instruction or action permission.

The invented templates in `examples/profiles/civic/` are unreviewed on purpose.
Their synthetic source references require actual storage/source provisioning
before resolution. Tests install real synthetic source records and reviewed
controls to exercise both denial and the positive applicable case.

StateCivics already has the KS-1105 monitoring bridge on the no-login KS-841
rehearsal replay. Use those existing runtime inputs, fast-forward controls and
capture sinks when supplying these profiles. This ticket neither replaces that
stack nor changes its receiver registry. Crawler MAT-047 still owns the actual
jurisdiction/authority export; MAT-048/049 own source adaptation and audience use.
Unsupported real-world procedural rules remain explicit missing/unknown inputs.

StateCivics uses Matter as its contextual monitoring and alert membrane. The
[monitoring profile and synthetic scenarios](statecivics-monitoring.md) describe
purpose/audience inputs and the existing no-login rehearsal evidence. StateCivics'
existing civic matter records/pages are a separate implementation; a shared name
does not imply a shared code path.
