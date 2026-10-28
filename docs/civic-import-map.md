# Crawler source-claim adapter — bounded MAT-048 work

`matter.civic_exports` consumes the existing `civic-matter-source-claims.v1`
container, not the parked single-meeting package format. The host reads copied
packages, verifies their outer digest and exact source text hashes, and declares
the jurisdiction, issuing-body scope, identity year and actual availability.
No crawler run, processing pass, receiver table mutation or DIAT work is required.

`prepare_export` produces a frozen mapping before writes. Original claim rows,
quotes, source PDF hashes and independent text hashes remain distinct. PDF page
markers are removed only for an explicitly declared citation view, following the
existing receiver's LF-line convention; quote comparison folds whitespace/bullets,
while the stored cited passage preserves its exact bytes. Unavailable text,
unsupported fields/families and out-of-range/mismatched citations are explicit
refusals. Raw native aliases and conflicts stay proposals, never automatic merges.

`CivicImportService` reuses MatterService, ObservationIngestor, OccurrenceService
and ClaimService. It retains the original exported extraction and a separately
hashed derived citation view. A source appearance uses a host-supplied exact
publisher event key, not a title or every historical action mentioned in a file.
A new appearance can remain on the same subject. Repeated package wrappers reuse
existing records; no package omission withdraws prior source claims. Core commands
are individually atomic and resumable; this is not an atomic replacement import.

Fields mapped: native matter kind/opaque number + explicit jurisdiction/issuer/year
→ continuing subject key; explicit publisher appearance key → occurrence;
raw quoted family/value/disposition → proposed source assertion. Native recommendation
labels become `recommendation_reported`, not an adopted or legally effective state.
Authority and semantic qualification remain unresolved. Source metadata does not
act as an authenticated host authority instruction.

## MAT-047 handoff checkpoint

Read-only inspection at crawler `c357ad1` found unrelated working changes; none
were touched. Existing T-087/T-090 source claims and T-104 relationship work remain
the owners. Retained latest dropoffs inspected: Shawnee `20261022-r2q`, Topeka
`20261022-t`, Wyandotte `20261015-a`. They already contain exact source claims,
quotes and independent text/PDF hash metadata. A compatible MAT-046 pinned
jurisdiction/authority profile bundle and host-reviewed authority handoff were not
established. Missing structured authority is not a reason to repeat extraction.
Full MAT-048 completion, source withdrawal/correction adaptation and full MAT-049
acceptance remain open; this work enables explicit source assertions and bounded
capture-only experiments without granting authority.

Tests use invented sources/names. Real copied data and provider artifacts stay in
`~/.local/share/matter-validation/civic-source-integration-20261028/`. Storage
preflight: 54 GiB available, 50 GiB reserve, 10 GiB additional task ceiling;
expected retained output under 200 MiB. Reuse existing environments/images and
rehearsal PostgreSQL; no extra worktrees or infrastructure.
