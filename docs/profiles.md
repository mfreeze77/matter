# Immutable policy profiles

MAT-013 adds `matter.profiles.ProfileDefinition` and `ProfileRegistry` on top of
the exact MAT-012 rule and schema registries. The [governing rule contract](contracts/rules.md)
defines their meaning. Profiles are host-installed declarations: they do not
execute source text, run a rule graph, publish assessments, issue certificates,
or grant source access or action authority.

## Construct an exact profile

A profile has a namespace, stable profile ID, semantic version, description,
separate `evidence`, `lifecycle`, `purpose`, and `audience` components as needed,
required output names, an incomplete-evaluation policy, and resource limits.
The packaged [profile schema](../schemas/policy-profile.schema.json) defines
its closed wire shape. No component family is mandatory.

The following helper assembles a profile for an already constructed MAT-012
`RuleDefinition` and its `SchemaRegistry`. Its explicit output selector must be
one of that rule's declared labels. There is no provider or storage dependency.

```python
from matter.profiles import ProfileDefinition, ProfileRegistry
from matter.rules import RuleRegistry


def profile_for_rule(rule, schemas, *, accepted_label, accepted_status):
    meaning = rule.value
    limits = {key: meaning["resource_limits"][key] for key in (
        "max_calls", "max_input_bytes", "max_output_bytes",
        "max_evidence", "max_elapsed_ms")}
    component = {
        "semantic_version": "1.0", "description": "Exact declared evidence rule.",
        "rules": [rule.reference], "parameters": {}, "dependencies": [],
        "outputs": [{"name": "example:conclusion", "rule": rule.reference,
            "schema": meaning["output_schema"],
            "accepted_labels": [accepted_label],
            "accepted_statuses": [accepted_status]}],
        "data_scopes": ["synthetic"], "capabilities": meaning["consequence_permissions"],
        "conflict_resolvers": [meaning["conflict_policy"]],
        "resource_limits": limits, "lifecycle_extensions": [],
        "conformance_cases": [{"name": "explicit", "invariant": "No implicit conflict fallback."}],
    }
    profile = ProfileDefinition({
        "schema_version": "1.0", "namespace": "example",
        "profile_id": "comparison-policy", "semantic_version": "1.0",
        "description": "A synthetic rule assembly.",
        "components": {"evidence": component},
        "required_outputs": ["example:conclusion"],
        "resource_limits": limits, "incomplete_evaluation": "retain_unresolved",
    }, rules=RuleRegistry([rule]), schemas=schemas,
       allowed_data_scopes=["synthetic"],
       allowed_capabilities=meaning["consequence_permissions"],
       conflict_resolvers=[meaning["conflict_policy"]])
    return ProfileRegistry([profile]), profile
```

The host supplies the allowlists in this example; deriving them from an
untrusted profile would defeat admission. A capability here identifies a
permitted **proposal schema**, not permission to execute that proposal. The
installed resolver references declare which exact conflict meanings are
available; this milestone does not invoke a resolver. Source text and parameter
values are canonical JSON data.

## Validation and explicit dependencies

Construction returns `ProfileValidationError`, an `E_POLICY_INVALID` error,
with a safe JSON Pointer `path` and a fixed explanation when a declaration
cannot be used. It rejects missing exact rule/schema versions, duplicate output
names or selected rules, absent required outputs, undefined labels, mismatched
output schemas or outcome statuses, missing predecessor rules, component cycles,
unadmitted scopes/proposals/resolvers, undeclared cross-component rule reads,
and impossible resource envelopes. Errors do not echo rejected source payloads.

Each component explicitly names its component dependencies. The selected rules'
immutable prerequisite references and accepted-label/status conditions define
the rule edges. Every predecessor must be selected, and cross-component reads
must be covered by the declared component dependency closure. Rule preconditions
remain part of the exact rule meaning. Execution planning and additional
conditional paths belong to MAT-014; this API does not evaluate their source
text or infer hidden dependencies from arbitrary parameters.

A rule is selected once in a profile; other components declare dependencies
rather than duplicate its call. Outputs select labels and statuses from a local
rule's exact output schema. Listed `required_outputs` must have producer paths;
other output declarations are optional results. Selecting a rule still reserves
its declared single bounded attempt regardless of whether its output is required.

Resource envelopes cover all selected nodes once: calls and input/output byte
caps are summed, evidence is a per-packet maximum, and elapsed time covers the
worst-case declared critical path. Component dependencies impose component
ordering, while independent components can share an elapsed envelope. Component
caps cannot exceed profile caps. These are feasibility checks of declarations,
not observed resource usage, scheduling, reservations, or a preemptive deadline.
The existing MAT-012 rule contract allows one call and no retries per rule.

## Semantic compatibility and independent components

`profile.reference` binds the full profile bytes, including exact rules,
parameters, ordered labels/options, rendering and evidence-preparation references.
`profile.component_references` binds each component separately, including its
transitive declared component semantics. `profile.dependencies` exposes detached
exact component and rule references. Component bindings omit the parent profile
ID so identical declared components can be shared by different profiles.

Changing an independent audience cadence changes its audience fingerprint and
the whole-profile reference while preserving the evidence fingerprint/read set.
If evidence explicitly depends on audience context, its fingerprint changes too.
The host must truthfully declare dependencies and bind every change to actual
rule meaning/preparation; a hash cannot discover undeclared runtime behavior.

`compare_profiles(before, after)` reports output-schema compatibility,
semantic equivalence, changed components, and profile-level changes separately.
Changing required outputs, incomplete-evaluation behavior, descriptions, or the
overall resource envelope prevents semantic-equivalence claims even if component
fingerprints stay the same. Matching schemas alone do not imply matching meaning.
The function always reports `qualification_transfer: False`: it grants no
certificate portability or authority. Existing MAT-012 admission continues to
check the exact rule/binding/preparation/task certificate; profile-driven changes
to those meanings need new exact rule references and separate admission. No
profile-level certificate issuance or graph admission engine is implemented.

## Historical profiles and assessment inputs

`registry.resolve(profile.reference)` requires the full exact namespace, ID,
version, and digest. There is no `latest` fallback. A profile identity/version
can be installed only once. Both profiles and registries keep canonical bytes or
immutable values internally and return detached public JSON copies.

`updated_registry, notice = registry.supersede(old_ref, replacement)` requires
the same profile identity with a new version. It retains both exact definitions
and returns a detached `policy_change` notice with compatibility details. It
rewrites no historical result, applies no transitive invalidation, and emits no
new source event. The host must persist or apply the notice through later APIs.

`profile.assessment_binding(matter_pin, purpose=purpose_ref, audience=audience_ref)`
returns exact input fields for a future assessment. An audience component
requires an audience reference. The same matter can be bound concurrently to
several profiles without mutating its identity. These are input bindings only:
MAT-015 still owns atomic assessment publication and currentness/authority
checks, and MAT-016 owns general transitive invalidation.

See [MAT-013 validation evidence](validation/MAT-013.md) for executed synthetic
checks and their limits.
