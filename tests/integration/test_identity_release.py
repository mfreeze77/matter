"""Explicit correction of identity barriers preserves their complete history."""

from matter.identity_corrections import IdentityCorrectionService
from matter.storage import entity_ref, pin

from identity_helpers import IdentityTestCase, merge_command, merge_policy, release_command


class IdentityReleaseTests(IdentityTestCase):
    def separated_pair(self):
        a, b = self.matter("a"), self.matter("b")
        _, merged = self.merge(a, [b])
        _, corrected = self.correct(merged["body"]["merge_receipt"])
        barriers = self.identities.view(a)["protections"]
        self.assertEqual(len(barriers), 1)
        barrier = self.storage.get(barriers[0])
        self.assertEqual(barrier["value"]["value"]["status"], "protected")
        return a, b, barrier, corrected

    def assert_merge_blocked(self, first, second, *, command_id):
        command = merge_command(command_id, self.authority, self.merge_policy,
                                self.current(first), [self.current(second)], [self.subject])
        self.assert_refused(self.identities.prepare, self.identities.merge, command, "E_MERGE_CONFLICT")

    def test_release_remerge_and_undo_preserve_protected_released_protected_history(self):
        a, b, barrier, _ = self.separated_pair()
        attachment = self.attach(self.current(b), label="retained-through-release")
        before = [self.current(item) for item in (a, b)]
        indexes = [self.storage.get(ref) for item in (a, b)
                   for ref in self.identities.view(item)["indexes"]]
        command, result = self.release([barrier])
        released = self.storage.get(result["body"]["separations"][0])
        self.assertEqual(released["revision"], 2)
        self.assertEqual(released["creation_receipt"], barrier["creation_receipt"])
        self.assertEqual(released["value"]["value"]["status"], "released")
        self.assertEqual([self.current(item) for item in (a, b)], before)
        for record in [*indexes, attachment, self.subject]:
            self.assertEqual(self.storage.get(entity_ref(record)), record)
        receipt = self.storage.get(result["body"]["release_receipt"])
        self.assertEqual(receipt["creation_receipt"], result["receipt"])
        self.assertEqual(self.storage.receipt_for(pin(released))["id"], result["receipt"]["id"])
        self.assertEqual(self.identities.separation_history(entity_ref(barrier)), [barrier, released])

        _, remerged = self.merge(self.current(a), [self.current(b)], command_id="remerge")
        self.correct(remerged["body"]["merge_receipt"], command_id="undo-remerge")
        protected_again = self.storage.get(entity_ref(barrier))
        self.assertEqual(protected_again["revision"], 3)
        self.assertEqual(protected_again["value"]["value"]["status"], "protected")
        self.assertEqual(self.identities.separation_history(entity_ref(barrier)),
                         [barrier, released, protected_again])
        self.assertEqual(self.identities.release_separations(command), result)
        self.assertEqual(self.storage.get(entity_ref(barrier)), protected_again)
        self.assertEqual(self.storage.get(pin(receipt)), receipt)
        self.assert_merge_blocked(a, b, command_id="historical-release-must-not-repeat")

    def test_selective_release_cannot_bypass_remaining_hidden_group_barriers(self):
        a, b, c = self.matter("a"), self.matter("b"), self.matter("c")
        _, merged = self.merge(a, [b, c])
        self.correct(merged["body"]["merge_receipt"])
        barriers = [self.storage.get(ref) for ref in self.identities.view(a)["protections"]]
        selected = [record for record in barriers
                    if {ref["id"] for ref in record["value"]["value"]["members"]} == {"a", "b"}]
        self.assertEqual(len(selected), 1)
        self.release(selected)
        self.merge(self.current(b), [self.current(a)], command_id="released-a-into-b")
        self.assertEqual(self.member_ids(b), {"a", "b"})
        self.assert_merge_blocked(b, c, command_id="cannot-bypass-a-c-or-b-c")
        current = {record["id"]: self.storage.get(entity_ref(record)) for record in barriers}
        for original in barriers:
            if original["id"] != selected[0]["id"]:
                self.assertEqual(current[original["id"]], original)
                self.assertEqual(original["value"]["value"]["status"], "protected")

    def test_release_requires_admitted_actor_authority_and_correction_capability(self):
        a, _, barrier, _ = self.separated_pair()
        for field in ("actor", "authority"):
            with self.subTest(field=field):
                command = self.prepare_release([barrier], command_id=f"unadmitted-{field}")
                command[field]["id"] = "source-asserted-permission"
                result = self.identities.release_separations(command)
                self.assert_failure(result, "E_AUTHORITY_REQUIRED")
                self.assertEqual(self.storage.get(entity_ref(barrier)), barrier)
        policy = merge_policy(self.authority, allow_correction=False)
        service = IdentityCorrectionService(self.storage, policy=policy)
        command = release_command("no-correction-capability", self.authority, policy,
                                  [barrier], [self.subject])
        self.assert_refused(service.prepare, service.release_separations, command, "E_AUTHORITY_REQUIRED")
        self.assertEqual(self.storage.get(entity_ref(barrier)), barrier)
        self.assertEqual(self.member_ids(a), {"a"})

    def test_foreign_scope_separation_is_refused_without_local_writes(self):
        a, b, barrier, _ = self.separated_pair()
        foreign = pin(barrier)
        foreign["scope_id"] = "synthetic:foreign"
        command = release_command("foreign-release", self.authority, self.merge_policy,
                                  [foreign], [self.subject])
        before = [self.current(item) for item in (a, b)]
        self.assert_refused(self.identities.prepare, self.identities.release_separations,
                            command, "E_SCOPE_FORBIDDEN")
        self.assertEqual([self.current(item) for item in (a, b)], before)
        self.assertEqual(self.storage.get(entity_ref(barrier)), barrier)

    def test_prepared_release_is_stale_after_competing_release(self):
        a, b, barrier, _ = self.separated_pair()
        prepared = self.prepare_release([barrier], command_id="losing-release")
        _, winner = self.release([barrier], command_id="winning-release")
        result = self.identities.release_separations(prepared)
        self.assert_failure(result, "E_REVISION_CONFLICT")
        self.assertEqual(self.identities.release_separations(prepared), result)
        self.assertEqual(self.storage.get(entity_ref(barrier)),
                         self.storage.get(winner["body"]["separations"][0]))
        self.assertEqual(self.member_ids(a), {"a"})
        self.assertEqual(self.member_ids(b), {"b"})

    def test_fresh_release_of_already_released_barrier_refuses_and_retains_history(self):
        _, _, barrier, _ = self.separated_pair()
        _, first = self.release([barrier])
        released = self.storage.get(first["body"]["separations"][0])
        command = release_command("already-released", self.authority, self.merge_policy,
                                  [released], [self.subject])
        self.assert_refused(self.identities.prepare, self.identities.release_separations,
                            command, "E_MERGE_CONFLICT")
        self.assertEqual(self.identities.separation_history(entity_ref(barrier)), [barrier, released])

    def test_release_does_not_remove_independent_association_protection(self):
        a, b, barrier, _ = self.separated_pair()
        independent = self.protect(self.current(a), self.current(b))
        self.release([barrier])
        self.assertEqual(self.storage.get(entity_ref(independent)), independent)
        self.assert_merge_blocked(a, b, command_id="independent-protection-remains")

    def test_process_interruption_recovers_all_selected_barriers_and_release_receipt(self):
        for stage in ("before_commit", "after_commit"):
            with self.subTest(stage=stage):
                a, b, c = [self.matter(f"{name}-{stage}") for name in ("a", "b", "c")]
                _, merged = self.merge(a, [b, c], command_id=f"merge-{stage}")
                self.correct(merged["body"]["merge_receipt"], command_id=f"correct-{stage}")
                barriers = [self.storage.get(ref) for ref in self.identities.view(a)["protections"]]
                self.assertEqual(len(barriers), 2)
                command = self.prepare_release(barriers, command_id=f"release-{stage}")
                originals = [self.current(item) for item in (a, b, c)]
                self.crash(command, stage)
                if stage == "before_commit":
                    self.assert_no_journal(command)
                    self.assertEqual([self.storage.get(entity_ref(item)) for item in barriers], barriers)
                    result = self.identities.release_separations(command)
                else:
                    result = self.storage.command_receipt(command["idempotency_key"])["result"]
                self.assertEqual(result["status"], "success", result)
                receipt = self.storage.get(result["body"]["release_receipt"])
                self.assertEqual(receipt["creation_receipt"], result["receipt"])
                self.assertEqual([self.current(item) for item in (a, b, c)], originals)
                for original in barriers:
                    released = self.storage.get(entity_ref(original))
                    self.assertEqual(released["revision"], original["revision"] + 1)
                    self.assertEqual(released["value"]["value"]["status"], "released")
                    self.assertEqual(self.storage.receipt_for(pin(released))["id"], result["receipt"]["id"])
                    self.assertEqual(self.identities.separation_history(entity_ref(original)), [original, released])
                self.assertEqual(self.identities.release_separations(command), result)
