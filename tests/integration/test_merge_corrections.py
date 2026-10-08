"""Identity correction preserves evidence and rejects stale or protected plans."""

from copy import deepcopy

from matter.identity_corrections import IdentityCorrectionService
from matter.storage import SQLiteStore, StorageError, entity_ref, pin, snapshot_digest

from association_helpers import SCOPE
from identity_helpers import IdentityTestCase, merge_command, competing_identity_results
from matter_helpers import metadata_command


class MergeCorrectionTests(IdentityTestCase):
    def test_merge_resolves_all_members_and_preserves_original_snapshots(self):
        a, b = self.matter("a"), self.matter("b")
        command, result = self.merge(a, [b])
        survivor = self.storage.get(result["body"]["survivor"])
        self.assertEqual(survivor["id"], "a")
        self.assertEqual(result["body"]["redirects"], [entity_ref(b)])
        self.assertEqual(self.identities.resolve(entity_ref(a)), survivor)
        self.assertEqual(self.identities.resolve(entity_ref(b)), survivor)
        self.assertEqual(self.member_ids(b), {"a", "b"})
        for original in (a, b):
            self.assertEqual(self.storage.get(pin(original)), original)
            current = self.current(original)
            self.assertEqual(current["revision"], original["revision"] + 1)
            self.assertEqual(current["creation_receipt"], original["creation_receipt"])
            self.assertEqual(current["body"]["identity_keys"], original["body"]["identity_keys"])
        self.assertEqual(self.identities.merge(command), result)

    def test_shared_evidence_conflicting_claims_and_original_associations_are_retained(self):
        a, b = self.matter("a"), self.matter("b")
        attachment_a, attachment_b = self.attach(a, label="a"), self.attach(b, label="b")
        claim_a, citation_a = self.assertion(a, "claim-a", "allocation asserted approved")
        claim_b, citation_b = self.assertion(b, "claim-b", "allocation asserted not approved")
        records = [self.subject, attachment_a, attachment_b, claim_a, claim_b, citation_a, citation_b]
        _, result = self.merge(a, [b])
        children = {tuple((item["reference"]["record_type"], item["reference"]["id"])): item
                    for item in self.identities.view(a)["children"]}
        for record in records:
            self.assertEqual(self.storage.get(pin(record)), record)
            self.assertIn((record["record_type"], record["id"]), children)
        shared = children[("observation", self.subject["id"])]
        self.assertEqual({ref["id"] for ref in shared["original_matters"]}, {"a", "b"})
        details = self.identities.historical_view(result["body"]["merge_receipt"])
        movement = [item for item in details["children"] if item["reference"] == pin(self.subject)]
        self.assertEqual(len(movement), 1)
        self.assertEqual(movement[0]["action"], "shared")
        self.assertEqual(movement[0]["record_action"], "retained")
        self.assertTrue(details["conflicts"], "Shared child ownership must be explained in the receipt.")
        self.assertEqual(self.claims.for_subject(entity_ref(a)), [claim_a])
        self.assertEqual(self.claims.for_subject(entity_ref(b)), [claim_b])
        self.assertEqual({row["id"] for row in self.service.for_subject(self.subject)},
                         {attachment_a["id"], attachment_b["id"]})
        self.assertNotIn("assessment", self.record_counts())

    def test_undo_restores_partitions_without_rewriting_shared_children(self):
        a, b = self.matter("a"), self.matter("b")
        first, second = self.attach(a, label="a"), self.attach(b, label="b")
        merged_command, merged = self.merge(a, [b])
        old_view = self.identities.historical_view(merged["body"]["merge_receipt"])
        correction, corrected = self.correct(merged["body"]["merge_receipt"])
        self.assertEqual(self.identities.resolve(a)["id"], "a")
        self.assertEqual(self.identities.resolve(b)["id"], "b")
        self.assertEqual(self.member_ids(a), {"a"})
        self.assertEqual(self.member_ids(b), {"b"})
        for original in (first, second, self.subject):
            self.assertEqual(self.storage.get(pin(original)), original)
        self.assertEqual(self.identities.historical_view(merged["body"]["merge_receipt"]), old_view)
        self.assertEqual(self.identities.merge(merged_command), merged)
        self.assertEqual(self.identities.correct(correction), corrected)
        self.assertEqual(self.identities.resolve(b)["id"], "b")
        self.assertEqual(self.current(a)["revision"], 3)
        self.assertEqual(self.current(b)["revision"], 3)
        retry = merge_command("fresh-remerge", self.authority, self.merge_policy,
                              self.current(a), [self.current(b)], [self.subject])
        self.assert_refused(self.identities.prepare, self.identities.merge, retry, "E_MERGE_CONFLICT")

    def test_split_can_choose_exhaustive_partitions_with_shared_evidence(self):
        a, b, c = self.matter("a"), self.matter("b"), self.matter("c")
        self.attach(a, label="a")
        self.attach(c, label="c")
        _, merged = self.merge(a, [b, c])
        _, result = self.correct(merged["body"]["merge_receipt"], kind="split",
                                 partitions=[[entity_ref(b), entity_ref(a)], [entity_ref(c)]])
        self.assertEqual({ref["id"] for ref in result["body"]["matters"]}, {"a", "b", "c"})
        self.assertEqual(self.identities.resolve(a)["id"], "b")
        self.assertEqual(self.identities.resolve(b)["id"], "b")
        self.assertEqual(self.identities.resolve(c)["id"], "c")
        self.assertEqual(self.member_ids(a), {"a", "b"})
        self.assertEqual(self.member_ids(c), {"c"})
        for reference in (a, c):
            children = self.identities.view(reference)["children"]
            self.assertIn(pin(self.subject), [item["reference"] for item in children])

    def test_undo_latest_merge_restores_prior_complete_groups(self):
        a, b, c = self.matter("a"), self.matter("b"), self.matter("c")
        _, first = self.merge(a, [b], command_id="merge-ab")
        _, second = self.merge(self.current(a), [c], command_id="merge-ab-c")
        self.assertEqual(self.member_ids(c), {"a", "b", "c"})
        self.correct(second["body"]["merge_receipt"])
        self.assertEqual(self.member_ids(a), {"a", "b"})
        self.assertEqual(self.identities.resolve(b)["id"], "a")
        self.assertEqual(self.member_ids(c), {"c"})
        self.assertEqual(self.identities.resolve(c)["id"], "c")
        self.assertEqual(len(self.identities.historical_view(first["body"]["merge_receipt"])["after"]), 1)

    def test_full_merged_groups_preserve_protection_between_hidden_original_members(self):
        a, b, c, d = [self.matter(value) for value in ("a", "b", "c", "d")]
        self.protect(a, c)
        self.merge(b, [a], command_id="a-into-b")
        self.merge(d, [c], command_id="c-into-d")
        before = [self.identities.view(item) for item in (b, d)]
        command = merge_command("join-protected-groups", self.authority, self.merge_policy,
                                self.current(b), [self.current(d)], [self.subject])
        self.assert_refused(self.identities.prepare, self.identities.merge, command, "E_MERGE_CONFLICT")
        self.assertEqual([self.identities.view(item) for item in (b, d)], before)
        self.assertEqual(self.identities.resolve(a)["id"], "b")
        self.assertEqual(self.identities.resolve(c)["id"], "d")

    def test_correction_protection_blocks_indirect_remerge_via_new_survivor(self):
        a, b, d = self.matter("a"), self.matter("b"), self.matter("d")
        _, merged = self.merge(a, [b])
        self.correct(merged["body"]["merge_receipt"])
        self.merge(d, [self.current(a)], command_id="a-into-d")
        command = merge_command("indirect-remerge", self.authority, self.merge_policy,
                                self.current(d), [self.current(b)], [self.subject])
        self.assert_refused(self.identities.prepare, self.identities.merge, command, "E_MERGE_CONFLICT")
        self.assertEqual(self.member_ids(d), {"a", "d"})
        self.assertEqual(self.member_ids(b), {"b"})

    def test_member_metadata_change_invalidates_prepared_merge_without_redirects(self):
        a, b = self.matter("a"), self.matter("b")
        prepared = self.prepare_merge(a, [b])
        update = metadata_command("new-metadata", b, {"title": "Updated between plan and commit"})
        changed = self.matters.update_metadata(self.matters.prepare(update))
        refusal = self.identities.merge(prepared)
        self.assert_failure(refusal, "E_REVISION_CONFLICT")
        self.assertEqual(self.identities.merge(prepared), refusal)
        self.assertEqual(self.identities.resolve(a)["id"], "a")
        self.assertEqual(self.identities.resolve(b)["id"], "b")
        self.assertEqual(pin(self.current(b)), changed["body"]["matter"])

    def test_new_child_after_prepare_invalidates_complete_child_manifest(self):
        a, b = self.matter("a"), self.matter("b")
        prepared = self.prepare_merge(a, [b])
        attachment = self.attach(b, label="late")
        refusal = self.identities.merge(prepared)
        self.assert_failure(refusal, "E_REVISION_CONFLICT")
        self.assertEqual(self.identities.resolve(b)["id"], "b")
        self.assertEqual(self.storage.get(pin(attachment)), attachment)
        self.assertEqual(self.storage.command_receipt(prepared["idempotency_key"])["result"], refusal)

    def test_first_protection_after_prepare_invalidates_absent_disposition_guard(self):
        a, b = self.matter("a"), self.matter("b")
        prepared = self.prepare_merge(a, [b])
        self.protect(a, b)
        self.assert_failure(self.identities.merge(prepared), "E_REVISION_CONFLICT")
        fresh = merge_command("fresh-protected", self.authority, self.merge_policy,
                              self.current(a), [self.current(b)], [self.subject])
        self.assert_refused(self.identities.prepare, self.identities.merge, fresh, "E_MERGE_CONFLICT")
        self.assertEqual(self.member_ids(a), {"a"})
        self.assertEqual(self.member_ids(b), {"b"})

    def test_premerge_association_acceptance_is_stale_after_identity_change(self):
        a, b = self.matter("a"), self.matter("b")
        catalog, entries, _, _ = self.publish([b])
        proposal, _, _ = self.propose(catalog, entries)
        prepared = self.accept_command(proposal, catalog, [b])
        self.merge(a, [b])
        self.assert_failure(self.service.accept(prepared), "E_REVISION_CONFLICT")
        self.assertEqual(self.service.for_subject(self.subject), [])

    def test_cross_scope_merge_and_unadmitted_actor_refuse_atomically(self):
        a, b = self.matter("a"), self.matter("b")
        before = [self.current(item) for item in (a, b)]
        foreign = pin(b)
        foreign["scope_id"] = "synthetic:foreign"
        command = merge_command("foreign", self.authority, self.merge_policy, a, [foreign], [self.subject])
        self.assert_refused(self.identities.prepare, self.identities.merge, command, "E_SCOPE_FORBIDDEN")
        prepared = self.prepare_merge(a, [b], command_id="unadmitted")
        prepared["actor"]["id"] = "source-asserted-authority"
        self.assert_failure(self.identities.merge(prepared), "E_AUTHORITY_REQUIRED")
        self.assertEqual([self.current(item) for item in (a, b)], before)
        self.assertEqual(self.member_ids(a), {"a"})
        self.assertEqual(self.member_ids(b), {"b"})

    def test_mutable_digest_pins_are_accepted_without_silently_refreshing_them(self):
        a, b = self.matter("a"), self.matter("b")
        digest_a = {**entity_ref(a), "digest": snapshot_digest(a)}
        digest_b = {**entity_ref(b), "digest": snapshot_digest(b)}
        command = merge_command("digest-merge", self.authority, self.merge_policy,
                                digest_a, [digest_b], [self.subject])
        command["expected_revisions"] = [digest_a, digest_b]
        prepared = self.identities.prepare(command)
        self.assertIn(digest_a, prepared["expected_revisions"])
        self.assertIn(digest_b, prepared["expected_revisions"])
        result = self.identities.merge(prepared)
        self.assertEqual(result.get("outcome"), "committed", result)
        self.assertEqual(self.identities.resolve(b)["id"], "a")

    def test_competing_opposite_merges_cannot_form_redirect_cycle(self):
        a, b = self.matter("a"), self.matter("b")
        commands = [self.prepare_merge(a, [b], command_id="a-survives"),
                    self.prepare_merge(b, [a], command_id="b-survives")]
        results = competing_identity_results(self, self.database, self.authority, commands)
        self.assertEqual(sum(result.get("outcome") == "committed" for result in results.values()), 1, results)
        failed = [result for result in results.values() if result["status"] == "failure"]
        self.assertEqual(len(failed), 1)
        self.assert_failure(failed[0], "E_REVISION_CONFLICT")
        self.assertEqual(self.identities.resolve(a), self.identities.resolve(b))
        self.assertIn(self.identities.resolve(a)["id"], {"a", "b"})
        self.assertEqual(self.member_ids(a), {"a", "b"})
        for command in commands:
            self.assertEqual(self.identities.merge(command), results[command["command_id"]])

    def test_backup_restores_corrected_groups_and_replays_old_merge_without_reattaching(self):
        a, b = self.matter("a"), self.matter("b")
        original, merged = self.merge(a, [b])
        self.correct(merged["body"]["merge_receipt"])
        views = [self.identities.view(item) for item in (a, b)]
        backup = self.storage.backup_to(self.directory / "identity-backup.sqlite")
        with SQLiteStore.restore_from(backup, self.directory / "restored.sqlite", scope_id=SCOPE) as restored:
            service = IdentityCorrectionService(restored, policy=self.merge_policy)
            self.assertEqual([service.view(item) for item in (a, b)], views)
            self.assertEqual(service.merge(original), merged)
            self.assertEqual(service.resolve(b)["id"], "b")
            fresh = merge_command("restored-remerge", self.authority, self.merge_policy,
                                  restored.get(entity_ref(a)), [restored.get(entity_ref(b))], [self.subject])
            self.assert_refused(service.prepare, service.merge, fresh, "E_MERGE_CONFLICT")

    def test_historical_assessment_keeps_merged_view_while_validity_is_invalidated(self):
        from matter.identity_dependencies import require_current_identity_dependency
        a, b = self.matter("a"), self.matter("b")
        _, result = self.merge(a, [b])
        merged_view = self.identities.view(a)
        historical = self.identities.historical_view(result["body"]["merge_receipt"])
        assessment, registration = self.registered_assessment(
            a, merge_receipt=result["body"]["merge_receipt"])
        with self.storage.snapshot() as snapshot:
            self.assertEqual(require_current_identity_dependency(snapshot, SCOPE, pin(registration)), registration)
        _, corrected = self.correct(result["body"]["merge_receipt"])
        invalidated = self.storage.get(entity_ref(registration))
        self.assertEqual(invalidated["revision"], registration["revision"] + 1)
        self.assertEqual(invalidated["value"]["value"]["status"], "invalidated")
        self.assertEqual(invalidated["value"]["value"]["invalidation"], corrected["body"]["correction_receipt"])
        self.assertEqual(self.storage.get(pin(assessment)), assessment)
        self.assertEqual(assessment["extensions"]["example:identity-view"]["value"], merged_view)
        self.assertEqual(self.identities.historical_view(result["body"]["merge_receipt"]), historical)
        self.assertEqual(self.storage.history(entity_ref(registration)), [registration, invalidated])
        for reference in (entity_ref(registration), pin(registration)):
            with self.storage.snapshot() as snapshot:
                with self.assertRaises(StorageError) as error:
                    require_current_identity_dependency(snapshot, SCOPE, reference)
                self.assertEqual(error.exception.code, "E_DEPENDENCY_STALE")
        self.assertEqual(self.identities.resolve(a)["id"], "a")
        self.assertEqual(self.identities.resolve(b)["id"], "b")

    def test_incomplete_or_duplicate_identity_partitions_refuse_atomically(self):
        a, b, c = self.matter("a"), self.matter("b"), self.matter("c")
        _, merged = self.merge(a, [b, c])
        before = self.identities.view(a)
        for label in ("missing-partition", "duplicate-member"):
            with self.subTest(label=label):
                prepared = self.prepare_correction(merged["body"]["merge_receipt"], command_id=label)
                partitions = prepared["body"]["partitions"]
                if label == "missing-partition":
                    partitions.pop()
                else:
                    partitions[0]["identity_members"].append(deepcopy(partitions[1]["identity_members"][0]))
                refused = self.identities.correct(prepared)
                self.assert_failure(refused, "E_MERGE_CONFLICT")
                self.assertEqual(self.identities.view(a), before)

    def test_omitted_child_cannot_silently_disappear_from_correction_manifest(self):
        a, b = self.matter("a"), self.matter("b")
        attachment = self.attach(a, label="must-retain")
        _, merged = self.merge(a, [b])
        before = self.identities.view(a)
        prepared = self.prepare_correction(merged["body"]["merge_receipt"])
        for partition in prepared["body"]["partitions"]:
            partition["members"] = [ref for ref in partition["members"] if ref != pin(attachment)]
        refused = self.identities.correct(prepared)
        self.assert_failure(refused, "E_MERGE_CONFLICT")
        self.assertEqual(self.identities.view(a), before)
        self.assertEqual(self.storage.get(pin(attachment)), attachment)

    def test_new_claim_after_prepared_correction_makes_partition_plan_stale(self):
        a, b = self.matter("a"), self.matter("b")
        _, merged = self.merge(a, [b])
        prepared = self.prepare_correction(merged["body"]["merge_receipt"])
        claim, citation = self.assertion(self.current(b), "late-claim", "new assertion after merge")
        refused = self.identities.correct(prepared)
        self.assert_failure(refused, "E_REVISION_CONFLICT")
        self.assertEqual(self.member_ids(a), {"a", "b"})
        self.assertEqual(self.storage.get(pin(claim)), claim)
        self.assertEqual(self.storage.get(pin(citation)), citation)
        self.correct(merged["body"]["merge_receipt"], command_id="fresh-correction")
        children = [entry["reference"] for entry in self.identities.view(b)["children"]]
        self.assertIn(pin(claim), children)
        self.assertIn(pin(citation), children)

    def test_old_merge_receipt_cannot_undo_an_intervening_identity_operation(self):
        a, b, c = self.matter("a"), self.matter("b"), self.matter("c")
        _, first = self.merge(a, [b], command_id="first-merge")
        _, second = self.merge(self.current(a), [c], command_id="second-merge")
        before = self.identities.view(a)
        with self.assertRaises(StorageError) as error:
            self.identities.plan_correction(first["body"]["merge_receipt"])
        self.assertEqual(error.exception.code, "E_MERGE_CONFLICT")
        self.assertEqual(self.identities.view(a), before)
        self.assertEqual(len(self.identities.historical_view(second["body"]["merge_receipt"])["after"][0]["members"]), 3)

    def test_losing_identity_keys_resolve_survivor_but_metadata_cannot_rewrite_redirect(self):
        from matter_helpers import identity_key, matter_command
        a, b = self.matter("a"), self.matter("b")
        _, merged = self.merge(a, [b])
        survivor = self.storage.get(merged["body"]["survivor"])
        self.assertEqual(self.matters.resolve([identity_key("a")]), survivor)
        self.assertEqual(self.matters.resolve([identity_key("b")]), survivor)
        repeated = matter_command("redelivered-b-key", matter_id="unused-new-id", keys=[identity_key("b")], scope_id=SCOPE)
        result = self.matters.create(self.matters.prepare(repeated))
        self.assertEqual(result.get("outcome"), "existing", result)
        self.assertEqual(result["body"]["matter"], pin(survivor))
        update = metadata_command("forbidden-redirect-edit", self.current(b), {"title": "Overwrite survivor indirectly"})
        self.assert_refused(self.matters.prepare, self.matters.update_metadata, update, "E_MERGE_CONFLICT")
        self.assertEqual(self.identities.resolve(b), survivor)
