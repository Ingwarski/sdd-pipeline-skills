"""Invocation snapshot hashing on synthetic files; no product or archived payloads."""
import copy
from contextvars import copy_context
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from test_sdd_check import Project, SCRIPT, sdd
import test_unit_history as history_fixture
import test_attempt_history as attempt_fixture
from progress import workflow_progress


class HistoryFileCacheTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="sdd-history-hash-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.history = sdd.history_api()
        self.api = self.history.api()
        self.logical = "assets/synthetic-payload.bin"
        self.relative = "forge/unit-history/synthetic/files/" + self.logical
        self.path = self.root / self.relative
        self.path.parent.mkdir(parents=True)
        self.payload = b"Synthetic snapshot bytes.\n" * 8192
        self.path.write_bytes(self.payload)
        self.record = {"snapshot_root": "forge/unit-history/synthetic/files",
                       "files": {self.logical: {"path": self.relative,
                                                "content_hash": sdd.digest(self.payload)}}}

    def check(self, record=None):
        return self.history.validate_files(self.root, record or self.record)

    def symlink(self, path, target, directory=False):
        try:
            path.symlink_to(target, target_is_directory=directory)
        except OSError as error:
            self.skipTest("symlink creation unavailable: " + str(error))

    def changed(self):
        self.path.write_bytes(b"X" + self.payload[1:])

    @staticmethod
    def report(checker):
        return {"result": "passed", "issues": checker.issues}

    def cache_reads(self):
        return mock.patch.object(self.api, "hash_file", wraps=self.api.hash_file)

    def payload_reads(self, hashing):
        return sum(Path(call.args[0]) == self.path for call in hashing.call_args_list)

    def add_legacy(self, project):
        manifest_ref = self.history.write_new(self.root, "forge/unit-history/synthetic/manifest.json",
                                              self.history.encoded(project.manifest))
        legacy = dict(self.record, event="legacy_execution_archive", version=2,
                      acceptance="unverified_not_reusable", manifest_ref=manifest_ref)
        legacy_ref = self.history.write_new(self.root, "forge/unit-history/synthetic/legacy.json",
                                            self.history.encoded(legacy))
        project.manifest.update(checker_contract_version=2, unit_contract_version=2,
                                legacy_history=[legacy_ref], next_ready_nodes=[])
        return legacy_ref

    @staticmethod
    def legacy_validations(validation):
        return sum(call.args[1].get("event") == "legacy_execution_archive"
                   for call in validation.call_args_list)

    def legacy_checker(self):
        project = Project(self.root)
        reference = self.add_legacy(project)
        return project, reference, sdd.Checker(self.root, project.manifest)

    def resolve_legacy(self, checker):
        self.history.HistoryView(checker).resolve()

    def test_checker_legacy_memo_reuses_full_validation_but_reads_refs_each_time(self):
        project, reference, checker = self.legacy_checker()
        manifest_ref = self.history.read_ref(self.root, reference)["manifest_ref"]
        def body(*args, **kwargs):
            self.resolve_legacy(checker)
            self.resolve_legacy(checker)
            self.assertEqual({self.path}, set(checker._history_hash_owner.hashes))
            return self.report(checker)
        with mock.patch.object(checker, "_run", side_effect=body), \
                mock.patch.object(self.history, "validate_files", wraps=self.history.validate_files) as validation, \
                mock.patch.object(self.history, "read_ref", wraps=self.history.read_ref) as reads:
            self.assertEqual("passed", checker.run("product-idea")["result"])
        self.assertEqual(1, self.legacy_validations(validation))
        for ref in (reference, manifest_ref):
            self.assertEqual(2, sum(call.args[1] == ref for call in reads.call_args_list))
        self.assertEqual({}, checker._history_hash_owner.legacy_files)
        self.assertIsNone(self.history._checker_audit_lease.get())

    def test_checker_legacy_memo_is_fresh_on_each_top_level_run(self):
        project, reference, checker = self.legacy_checker()
        def body(*args, **kwargs):
            self.resolve_legacy(checker)
            self.resolve_legacy(checker)
            return self.report(checker)
        with mock.patch.object(checker, "_run", side_effect=body), \
                mock.patch.object(self.history, "validate_files", wraps=self.history.validate_files) as validation:
            self.assertEqual("passed", checker.run("product-idea")["result"])
            first = checker._history_hash_owner
            os.link(self.path, self.path.with_name("between-phases.bin"))
            self.assertEqual("passed", checker.run("product-idea")["result"])
            self.assertIsNot(first, checker._history_hash_owner)
        self.assertEqual(2, self.legacy_validations(validation))
        self.assertEqual({}, first.legacy_files)

    def test_generic_scope_and_expired_copied_checker_lease_never_reuse(self):
        project, reference, checker = self.legacy_checker()
        saved = []
        def body(*args, **kwargs):
            self.resolve_legacy(checker)
            self.resolve_legacy(checker)
            saved.append(copy_context())
            return self.report(checker)
        with mock.patch.object(self.history, "validate_files", wraps=self.history.validate_files) as validation, \
                self.history.snapshot_hash_scope(audit=False) as owner:
            with mock.patch.object(checker, "_run", side_effect=body):
                self.assertEqual("passed", checker.run("product-idea")["result"])
            self.resolve_legacy(checker)
            # A stale caller flag cannot revive the expired context-local lease.
            checker._invocation_active = True
            try:
                saved[0].run(self.resolve_legacy, checker)
            finally:
                checker._invocation_active = False
            self.assertEqual(3, self.legacy_validations(validation))
            self.assertEqual(1, len(owner.legacy_files))
        self.assertEqual({}, owner.legacy_files)

    def test_legacy_memo_semantic_record_mutation_requires_full_validation(self):
        project, reference, checker = self.legacy_checker()
        original = self.history.read_ref
        visits = 0
        def changed_record(root, ref):
            nonlocal visits
            value = original(root, ref)
            if ref == reference:
                visits += 1
                if visits == 2:
                    value["files"][self.logical]["content_hash"] = "0" * 64
            return value
        def body(*args, **kwargs):
            self.resolve_legacy(checker)
            self.resolve_legacy(checker)
            return self.report(checker)
        with mock.patch.object(checker, "_run", side_effect=body), \
                mock.patch.object(self.history, "read_ref", side_effect=changed_record), \
                mock.patch.object(self.history, "validate_files", wraps=self.history.validate_files) as validation:
            with self.assertRaisesRegex(ValueError, "historical snapshot changed"):
                checker.run("product-idea")
        self.assertEqual(2, self.legacy_validations(validation))

    def test_legacy_memo_never_skips_reference_or_original_manifest_sha(self):
        project, reference, checker = self.legacy_checker()
        legacy = self.history.read_ref(self.root, reference)
        for changed in ("legacy", "manifest"):
            with self.subTest(changed=changed):
                target = reference if changed == "legacy" else legacy["manifest_ref"]
                path = self.root / target["path"]
                original = path.read_bytes()
                def body(*args, **kwargs):
                    self.resolve_legacy(checker)
                    path.write_bytes(path.read_bytes() + b" ")
                    self.resolve_legacy(checker)
                    return self.report(checker)
                try:
                    with mock.patch.object(checker, "_run", side_effect=body), \
                            self.assertRaisesRegex(ValueError, "changed history file"):
                        checker.run("product-idea")
                finally:
                    path.write_bytes(original)

    def test_legacy_memo_keeps_current_logical_link_guards(self):
        project, reference, checker = self.legacy_checker()
        logical = self.root / self.logical
        def body(*args, **kwargs):
            self.resolve_legacy(checker)
            logical.parent.mkdir(exist_ok=True)
            self.symlink(logical, self.path)
            self.resolve_legacy(checker)
            return self.report(checker)
        with mock.patch.object(checker, "_run", side_effect=body), \
                mock.patch.object(self.history, "validate_files", wraps=self.history.validate_files) as validation:
            with self.assertRaisesRegex(ValueError, "cannot follow links"):
                checker.run("product-idea")
        self.assertEqual(1, self.legacy_validations(validation))

    def test_legacy_memo_rejects_frozen_change_before_checker_return(self):
        project, reference, checker = self.legacy_checker()
        def body(*args, **kwargs):
            self.resolve_legacy(checker)
            self.changed()
            self.resolve_legacy(checker)  # Reuse cannot escape the mandatory audit.
            return self.report(checker)
        with mock.patch.object(checker, "_run", side_effect=body), \
                mock.patch.object(self.history, "validate_files", wraps=self.history.validate_files) as validation:
            result = checker.run("product-idea")
        self.assertEqual(1, self.legacy_validations(validation))
        self.assertEqual("blocked", result["result"])
        self.assertTrue(any(issue["code"] == "changing_input" for issue in result["issues"]))

    def test_legacy_memo_registers_unused_files_and_audits_before_child_return(self):
        unused = self.path.with_name("unused.bin")
        unused.write_bytes(b"Unused synthetic snapshot.\n")
        self.record["files"]["assets/unused.bin"] = {
            "path": unused.relative_to(self.root).as_posix(), "content_hash": sdd.digest(unused.read_bytes())}
        project, reference, checker = self.legacy_checker()
        child = sdd.Checker(self.root, project.manifest)
        child_results = []
        def child_body(*args, **kwargs):
            self.resolve_legacy(child)
            self.assertEqual({self.path, unused}, set(child._history_hash_owner.hashes))
            unused.unlink()
            return self.report(child)
        def body(*args, **kwargs):
            self.resolve_legacy(checker)
            with mock.patch.object(child, "_run", side_effect=child_body):
                child_results.append(child.run("product-idea"))
            return self.report(checker)
        with mock.patch.object(checker, "_run", side_effect=body), \
                mock.patch.object(self.history, "validate_files", wraps=self.history.validate_files) as validation:
            result = checker.run("product-idea")
        self.assertEqual(1, self.legacy_validations(validation))
        self.assertEqual("blocked", child_results[0]["result"])
        self.assertEqual("blocked", result["result"])

    def test_legacy_memo_registration_loss_requires_full_validation(self):
        project, reference, checker = self.legacy_checker()
        def body(*args, **kwargs):
            self.resolve_legacy(checker)
            checker._history_hash_owner.hashes.clear()
            self.changed()
            self.resolve_legacy(checker)
            return self.report(checker)
        with mock.patch.object(checker, "_run", side_effect=body), \
                mock.patch.object(self.history, "validate_files", wraps=self.history.validate_files) as validation:
            with self.assertRaisesRegex(ValueError, "historical snapshot changed"):
                checker.run("product-idea")
        self.assertEqual(2, self.legacy_validations(validation))

    def test_legacy_memo_reference_path_is_part_of_namespace(self):
        project, reference, checker = self.legacy_checker()
        alias = dict(reference, path="forge/unit-history/synthetic/alias.json")
        (self.root / alias["path"]).write_bytes((self.root / reference["path"]).read_bytes())
        def body(*args, **kwargs):
            self.resolve_legacy(checker)
            checker.manifest["legacy_history"] = [alias]
            self.resolve_legacy(checker)
            return self.report(checker)
        with mock.patch.object(checker, "_run", side_effect=body), \
                mock.patch.object(self.history, "validate_files", wraps=self.history.validate_files) as validation:
            self.assertEqual("passed", checker.run("product-idea")["result"])
        self.assertEqual(2, self.legacy_validations(validation))

    def test_legacy_memo_project_namespace_isolated_across_nested_checkers(self):
        project, reference, checker = self.legacy_checker()
        other_root = self.root / "another-project"
        other_root.mkdir()
        legacy = self.history.read_ref(self.root, reference)
        for ref in (reference, legacy["manifest_ref"], self.record["files"][self.logical]):
            target = other_root / ref["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((self.root / ref["path"]).read_bytes())
        (other_root / self.relative).write_bytes(b"X" + self.payload[1:])
        child = sdd.Checker(other_root, copy.deepcopy(project.manifest))
        def child_body(*args, **kwargs):
            self.resolve_legacy(child)
            return self.report(child)
        def body(*args, **kwargs):
            self.resolve_legacy(checker)
            with mock.patch.object(child, "_run", side_effect=child_body), \
                    self.assertRaisesRegex(ValueError, "historical snapshot changed"):
                child.run("product-idea")
            return self.report(checker)
        with mock.patch.object(checker, "_run", side_effect=body), \
                mock.patch.object(self.history, "validate_files", wraps=self.history.validate_files) as validation:
            self.assertEqual("passed", checker.run("product-idea")["result"])
        self.assertEqual(2, self.legacy_validations(validation))

    def test_legacy_memo_error_exit_still_audits_full_union(self):
        project, reference, checker = self.legacy_checker()
        def body(*args, **kwargs):
            self.resolve_legacy(checker)
            self.resolve_legacy(checker)
            self.changed()
            raise RuntimeError("synthetic semantic failure")
        with mock.patch.object(checker, "_run", side_effect=body), \
                self.assertRaisesRegex(ValueError, "historical snapshot changed") as raised:
            checker.run("product-idea")
        self.assertIsInstance(raised.exception.__context__, RuntimeError)
        self.assertIsNone(self.history._checker_audit_lease.get())

    def test_nested_migration_stage_and_activation_keep_prewrite_hard_errors(self):
        for operation in ("stage", "activate"):
            with self.subTest(operation=operation):
                base = history_fixture.UnitHistoryTests("test_version_one_retains_original_acceptance_and_plan_binding_rules")
                base.setUp()
                self.addCleanup(base.doCleanups)
                helper = self.history
                base.p.save()
                expected = base.p.hash("forge/sdd-manifest.json")
                staged = helper.adopt_legacy(base.p.root, expected)
                staged_record = base.read(staged)
                candidate = staged_record["manifest"]
                legacy = base.read(candidate["legacy_history"][-1])
                checker = sdd.Checker(base.p.root, candidate)
                def body(*args, **kwargs):
                    self.resolve_legacy(checker)
                    self.resolve_legacy(checker)
                    return self.report(checker)
                with self.assertRaisesRegex(ValueError, "missing|unreadable|historical snapshot changed"):
                    with helper.snapshot_hash_scope():
                        with mock.patch.object(checker, "_run", side_effect=body):
                            self.assertEqual("passed", checker.run("product-idea")["result"])
                        snapshot = next(iter(legacy["files"].values()))
                        (base.p.root / snapshot["path"]).unlink()
                        with mock.patch.object(helper, "write_new", wraps=helper.write_new) as writes, \
                                mock.patch.object(helper, "store_record", wraps=helper.store_record) as records, \
                                mock.patch.object(helper.os, "replace", wraps=helper.os.replace) as replace:
                            with self.assertRaisesRegex(ValueError, "historical snapshot changed"):
                                if operation == "stage":
                                    helper.stage_candidate(base.p.root, candidate, expected)
                                else:
                                    helper.activate_candidate(base.p.root, staged, expected)
                            writes.assert_not_called()
                            records.assert_not_called()
                            replace.assert_not_called()
                            self.assertEqual(expected, base.p.hash("forge/sdd-manifest.json"))
                            self.assertFalse((base.p.root / "forge/unit-history/activation.lock").exists())

    def fixture(self, finish=True):
        base = history_fixture.UnitHistoryTests("test_version_one_retains_original_acceptance_and_plan_binding_rules")
        base.setUp()
        self.addCleanup(base.doCleanups)
        return base, base.capture_alpha(finish=finish)

    def test_one_streaming_read_across_root_historical_and_real_ready_probe(self):
        project = Project(self.root)
        self.add_legacy(project)
        root = sdd.Checker(self.root, project.manifest)
        original = root._run
        children = []
        def with_history_child(*args, **kwargs):
            result = original(*args, **kwargs)  # Includes the actual ready projection probe.
            child = self.history.historical_checker(self.root, project.manifest, self.record)
            children.append(child)
            # Stub only the child's gate body to isolate hash-lifetime behavior.
            # The root and ready-probe bodies above remain the actual checker.
            def child_body(*args, **kwargs):
                self.assertEqual(sdd.digest(self.payload), child.file_hash(self.path))
                return self.report(child)
            with mock.patch.object(child, "_run", side_effect=child_body):
                self.assertEqual("passed", child.run("product-idea")["result"])
            return result
        with self.cache_reads() as hashing, mock.patch.object(root, "_run", side_effect=with_history_child):
            result = root.run("product-idea")
        self.assertEqual("passed", result["result"], result)
        self.assertEqual(1, self.payload_reads(hashing))
        self.assertEqual(1, len(children))
        self.assertEqual(0, root._history_hash_owner.depth)
        self.assertEqual({}, root._history_hash_owner.hashes)
        self.assertEqual([], root._history_hash_owner.history_results)

    def test_expected_hash_is_compared_on_every_reuse(self):
        wrong = copy.deepcopy(self.record)
        wrong["files"][self.logical]["content_hash"] = "0" * 64
        with self.cache_reads() as hashing, self.history.snapshot_hash_scope():
            self.check()
            with self.assertRaisesRegex(ValueError, "historical snapshot changed"):
                self.check(wrong)
            self.assertEqual(1, self.payload_reads(hashing))

    def test_membership_and_logical_path_checks_repeat_on_reuse(self):
        with self.history.snapshot_hash_scope():
            self.check()
            wrong = copy.deepcopy(self.record)
            wrong["snapshot_root"] += "-other"
            with self.assertRaisesRegex(ValueError, "preserve logical identity"):
                self.check(wrong)
            logical = self.root / self.logical
            logical.parent.mkdir()
            self.symlink(logical, self.path)
            with self.assertRaisesRegex(ValueError, "cannot follow links"):
                self.check()

    def test_equal_size_rewrite_with_restored_mtime_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "changed"), self.history.snapshot_hash_scope():
            self.check()
            before = self.path.stat()
            saved = self.api._regular(self.path)
            self.changed()
            os.utime(self.path, ns=(before.st_atime_ns, before.st_mtime_ns))
            self.assertNotEqual(saved, self.api._regular(self.path))
            with self.assertRaisesRegex(ValueError, "changed"):
                self.check()

    def test_hardlink_write_between_phases_requires_a_fresh_hash(self):
        with self.cache_reads() as hashing:
            with self.history.snapshot_hash_scope() as first:
                self.check()
            before = self.api._regular(self.path)
            os.link(self.path, self.path.with_name("new-synthetic-snapshot.bin"))
            self.assertNotEqual(before, self.api._regular(self.path))
            with self.history.snapshot_hash_scope() as second:
                self.assertIsNot(first, second)
                self.check()
            self.assertEqual(2, self.payload_reads(hashing))

    def test_hardlink_write_inside_readonly_phase_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "changed"), self.history.snapshot_hash_scope():
            self.check()
            os.link(self.path, self.path.with_name("unexpected-synthetic-snapshot.bin"))

    def test_same_size_replacement_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "changed"), self.history.snapshot_hash_scope():
            self.check()
            temporary = self.path.with_suffix(".replacement")
            temporary.write_bytes(self.payload)
            temporary.replace(self.path)
            self.check()

    def test_snapshot_and_parent_links_are_rejected_after_first_use(self):
        for parent in (False, True):
            with self.subTest(parent=parent):
                if parent:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_bytes(self.payload)
                with self.assertRaisesRegex(ValueError, "link|regular"), self.history.snapshot_hash_scope():
                    self.check()
                    if parent:
                        directory = self.path.parent
                        retained = directory.with_name("retained-assets")
                        directory.rename(retained)
                        self.symlink(directory, retained, directory=True)
                    else:
                        self.path.unlink()
                        self.symlink(self.path, self.root / "missing")
                    self.check()
                if not parent:
                    self.path.unlink()

    def test_missing_snapshot_rejected_on_reuse_and_exit(self):
        with self.assertRaisesRegex(ValueError, "missing|unreadable"), self.history.snapshot_hash_scope():
            self.check()
            self.path.unlink()
            self.check()

    def test_first_read_mutation_uses_stable_streaming_guard(self):
        import evidence.io as io
        native_read = io.os.read
        mutated = False
        def read_and_change(descriptor, size):
            nonlocal mutated
            block = native_read(descriptor, size)
            if block and not mutated:
                mutated = True
                self.changed()
            return block
        with mock.patch.object(io.os, "read", side_effect=read_and_change):
            # Windows intentionally denies writable handles during this read.
            # POSIX permits the mutation and must detect it before trusting bytes.
            expected = "cannot safely read" if os.name == "nt" else "changed while reading"
            with self.assertRaisesRegex(ValueError, expected):
                self.check()
        self.assertTrue(mutated)
        if os.name == "nt":
            self.assertEqual(self.path.read_bytes(), self.payload)
            self.check()  # The failed write left the original snapshot intact.

    def test_mutation_between_signature_and_first_stream_is_rejected(self):
        native_hash = self.api.hash_file
        def change_then_hash(path):
            self.changed()
            return native_hash(path)
        with mock.patch.object(self.api, "hash_file", side_effect=change_then_hash):
            with self.assertRaisesRegex(ValueError, "changed during checker"):
                self.check()

    def test_error_path_audits_the_full_snapshot_union(self):
        with self.assertRaisesRegex(ValueError, "historical snapshot changed") as raised:
            with self.history.snapshot_hash_scope():
                self.check()
                self.changed()
                raise RuntimeError("synthetic semantic validation failure")
        self.assertIsInstance(raised.exception.__context__, RuntimeError)

    def test_child_end_mutation_and_root_end_mutation_block(self):
        root = sdd.Checker(self.root, {})
        child_reports = []
        def root_body(*args, **kwargs):
            child = self.history.historical_checker(self.root, {}, self.record)
            def child_body(*args, **kwargs):
                self.changed()
                return self.report(child)
            with mock.patch.object(child, "_run", side_effect=child_body):
                child_reports.append(child.run("product-idea"))
            return self.report(root)
        with mock.patch.object(root, "_run", side_effect=root_body):
            report = root.run("product-idea")
        self.assertEqual("blocked", child_reports[0]["result"])
        self.assertEqual("blocked", report["result"])
        self.assertTrue(any(item["code"] == "changing_input" for item in report["issues"]))

    def test_root_audits_files_after_child_has_returned(self):
        root = sdd.Checker(self.root, {})
        def root_body(*args, **kwargs):
            child = self.history.historical_checker(self.root, {}, self.record)
            with mock.patch.object(child, "_run", return_value=self.report(child)):
                self.assertEqual("passed", child.run("product-idea")["result"])
            self.changed()
            return self.report(root)
        with mock.patch.object(root, "_run", side_effect=root_body):
            report = root.run("product-idea")
        self.assertEqual("blocked", report["result"])
        self.assertTrue(any(item["code"] == "changing_input" for item in report["issues"]))

    def test_repeated_root_run_standalone_validation_and_progress_are_fresh(self):
        project = Project(self.root)
        self.add_legacy(project)
        root = sdd.Checker(self.root, project.manifest)
        with self.cache_reads() as hashing:
            self.assertEqual("passed", root.run("product-idea")["result"])
            first = root._history_hash_owner
            self.assertEqual("passed", root.run("product-idea")["result"])
            self.assertIsNot(first, root._history_hash_owner)
            self.check()
            self.check()
            workflow_progress(root)
            workflow_progress(root)
            self.assertEqual(6, self.payload_reads(hashing))
        self.changed()
        self.assertNotEqual("passed", root.run("product-idea")["result"])

    def test_root_final_audit_includes_files_only_seen_by_progress_child(self):
        project = Project(self.root)
        root = sdd.Checker(self.root, project.manifest)
        def probe_body(child, *args, **kwargs):
            self.check()
            return {"result": "passed", "issues": child.issues, "warnings": [], "checked_artifacts": []}
        def root_body(*args, **kwargs):
            with mock.patch.object(sdd.Checker, "_run", autospec=True, side_effect=probe_body):
                self.assertEqual("passed", workflow_progress(root)["result"])
            self.changed()
            return self.report(root)
        with mock.patch.object(root, "_run", side_effect=root_body):
            result = root.run("product-idea")
        self.assertEqual("blocked", result["result"])
        self.assertTrue(any(item["code"] == "changing_input" for item in result["issues"]))

    def test_historical_checker_stack_does_not_reuse_prior_invocation_semantic_trust(self):
        base, (helper, inventory, context, _) = self.fixture(finish=False)
        checker = sdd.Checker(base.p.root, base.m)
        checker._history_stack, checker._history_cache = (), {}
        def body(*args, **kwargs):
            self.history.validate_context(base.p.root, context, "U-1", cache=checker._history_cache)
            return self.report(checker)
        with mock.patch.object(checker, "_run", side_effect=body):
            self.assertEqual("passed", checker.run("product-idea")["result"])
            record = base.read(context)
            (base.p.root / record["files"]["docs/prd.md"]["path"]).write_text("Changed prior invocation.")
            with self.assertRaises(ValueError):
                checker.run("product-idea")

    def test_standalone_historical_checker_rehashes_all_files_on_later_runs(self):
        child = self.history.historical_checker(self.root, {}, self.record)
        # This gate deliberately reads none of the overlay: the full original
        # snapshot closure must still be registered on each run.
        with mock.patch.object(child, "_run", side_effect=lambda *args, **kwargs: self.report(child)):
            with self.cache_reads() as hashing:
                self.assertEqual("passed", child.run("product-idea")["result"])
                self.assertEqual("passed", child.run("product-idea")["result"])
                self.assertEqual(2, self.payload_reads(hashing))
            self.changed()
            with self.assertRaisesRegex(ValueError, "historical snapshot changed"):
                child.run("product-idea")

    def test_registered_snapshot_inventory_hashes_reuse_bytes_but_repeat_tree_listing(self):
        with self.cache_reads() as hashing, self.history.snapshot_hash_scope():
            child = self.history.historical_checker(self.root, {}, self.record)
            child.specs = {"synthetic": {"path": self.logical}}
            self.assertEqual({self.logical: sdd.digest(self.payload)}, self.history.canonical_hashes(child))
            self.assertEqual(sdd.digest(self.payload), self.history.execution_fingerprints(
                child, {self.logical: {"mode": "file"}})[self.logical]["content_hash"])
            with mock.patch.object(self.history.os, "walk", wraps=self.history.os.walk) as listing:
                first = self.history.execution_fingerprints(child, {"assets": {"mode": "tree"}})
                second = self.history.execution_fingerprints(child, {"assets": {"mode": "tree"}})
                self.assertEqual(first, second)
                self.assertEqual(2, listing.call_count)
            self.assertEqual(1, self.payload_reads(hashing))

    def test_ordinary_files_do_not_enter_shared_snapshot_cache(self):
        checker = sdd.Checker(self.root, {})
        with checker.history_hash_scope() as owner:
            checker._history_hash_owner = owner
            self.assertEqual(sdd.digest(self.payload), checker.file_hash(self.path))
            self.assertEqual({}, owner.hashes)
            self.assertIn(self.path, checker.hash_cache)

    def test_semantic_cache_eligibility_binds_cache_result_identity_and_content(self):
        with self.history.snapshot_hash_scope() as owner:
            cache, other = {"key": {"nested": [1]}}, {"key": {"nested": [1]}}
            self.assertFalse(owner.history_result(cache, "key"))
            owner.history_result(cache, "key", remember=True)
            self.assertTrue(owner.history_result(cache, "key"))
            self.assertFalse(owner.history_result(other, "key"))
            cache["key"]["nested"].append(2)
            self.assertFalse(owner.history_result(cache, "key"))
            owner.history_result(cache, "key", remember=True)
            cache["key"] = copy.deepcopy(cache["key"])
            self.assertFalse(owner.history_result(cache, "key"))
        with self.history.snapshot_hash_scope() as fresh:
            self.assertFalse(fresh.history_result(cache, "key"))

    def test_retained_context_semantic_cache_revalidates_fresh_snapshot_union(self):
        base, (helper, inventory, context, _) = self.fixture(finish=False)
        cache = {}
        helper.validate_context(base.p.root, context, "U-1", cache=cache)
        record = base.read(context)
        snapshot = base.p.root / record["files"]["docs/prd.md"]["path"]
        snapshot.write_text("Changed synthetic prior context snapshot.")
        with self.assertRaises(ValueError):
            helper.validate_context(base.p.root, context, "U-1", cache=cache)

    def test_retained_completion_semantic_cache_revalidates_fresh_snapshot_union(self):
        base, (helper, inventory, context, completion) = self.fixture()
        cache = {}
        helper.validate_completion(base.p.root, completion, cache=cache)
        record = base.read(completion)
        snapshot = base.p.root / record["files"]["docs/prd.md"]["path"]
        snapshot.write_text("Changed synthetic completion snapshot.")
        with self.assertRaises(ValueError):
            helper.validate_completion(base.p.root, completion, cache=cache)

    def test_retained_attempt_semantic_cache_revalidates_fresh_snapshot_union(self):
        fixture = attempt_fixture.AttemptHistoryTests("test_failed_and_interrupted_status_edits_preserve_actual_results_and_block_completion")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.start()
        attempt = fixture.capture()
        cache = {}
        fixture.helper.validate_attempt(fixture.p.root, attempt, cache=cache)
        record = fixture.base.read(attempt)
        snapshot = fixture.p.root / record["files"]["docs/prd.md"]["path"]
        snapshot.write_text("Changed synthetic attempt snapshot.")
        with self.assertRaises(ValueError):
            fixture.helper.validate_attempt(fixture.p.root, attempt, cache=cache)

    def test_history_cli_independent_process_rechecks_historical_snapshots(self):
        base, (helper, inventory, context, completion) = self.fixture()
        for path, value in (("forge/cli-completion.json", completion), ("forge/cli-inventory.json", base.inventory()),
                            ("forge/cli-pending.json", base.pending_map())):
            base.p.write(path, json.dumps(value))
        command = [sys.executable, "-B", str(SCRIPT.with_name("sdd_history.py")),
                   "--project", str(base.p.root), "assess", "--completion-ref", "forge/cli-completion.json",
                   "--inventory", "forge/cli-inventory.json", "--pending-map", "forge/cli-pending.json"]
        first = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(0, first.returncode, first.stdout + first.stderr)
        record = base.read(completion)
        (base.p.root / record["files"]["docs/prd.md"]["path"]).write_text("Changed CLI synthetic snapshot.")
        second = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(1, second.returncode, second.stdout + second.stderr)
        self.assertEqual("blocked", json.loads(second.stdout)["result"])


if __name__ == "__main__":
    unittest.main()
