"""Transition-local reuse on real synthetic retry history; never product acceptance."""
from collections import Counter
from contextlib import ExitStack, contextmanager, nullcontext
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import test_attempt_history as attempt_fixture
from test_sdd_check import SCRIPT, sdd


class TransitionCacheTests(unittest.TestCase):
    def setUp(self):
        self.fixture = attempt_fixture.AttemptHistoryTests("runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.start()
        self.base = self.fixture.base
        self.p, self.m, self.h = self.fixture.p, self.fixture.m, self.fixture.helper
        # This frozen file is registered by the first context but never read by
        # the checker or copied into later contexts. Its union audit is mandatory.
        context = self.base.read(self.fixture.context)
        logical = "synthetic-unused-ancestor.txt"
        relative = context["snapshot_root"] + "/" + logical
        self.p.write(relative, "Only the oldest context owns this synthetic byte.\n")
        context["files"][logical] = {"path": relative, "content_hash": self.p.hash(relative)}
        self.base.rewrite(self.fixture.context, context)
        self.unused = self.p.root / relative
        self.m["execution_contexts"]["U-1"] = copy.deepcopy(self.fixture.context)
        self.attempts = []
        for number in range(1, 4):
            context_ref = self.m["execution_contexts"]["U-1"]
            reference = self.h.capture_attempt(self.p.root, self.m, "U-1", context_ref,
                "synthetic-attempt-" + str(number), "failed" if number == 1 else "interrupted",
                self.base.read(context_ref)["input_inventory"])
            self.m["unit_runs"]["U-1"]["attempt_ref"] = reference
            self.attempts.append(reference)
            candidate = self.h.capture_continuation(self.p.root, self.m, "U-1", reference,
                "synthetic-attempt-" + str(number + 1), self.fixture.continuation_inventory())["manifest"]
            if number == 3:
                self.previous, self.candidate = copy.deepcopy(self.m), candidate
            else:
                self.m.clear()
                self.m.update(candidate)
                self.m["unit_runs"]["U-1"].update(status="running", started_at=self.base.now(),
                    development_plan_hash=self.p.hash("docs/development-plan.md"), approved_baseline_id="B-1")

    @contextmanager
    def checkers(self, helper=None):
        helper = helper or self.h
        calls, original = [], helper.api().Checker.run
        def run(checker, *args, **kwargs):
            records = getattr(checker, "_history_snapshot_records", ())
            calls.append((records[-1]["snapshot_root"] if records else None,
                          bool(getattr(checker, "_history_observation_overlay", None))))
            return original(checker, *args, **kwargs)
        with mock.patch.object(helper.api().Checker, "run", autospec=True, side_effect=run):
            yield calls

    @contextmanager
    def original_transition_cache_behavior(self):
        # Drop only the new top-level keyword. Existing recursive positional
        # cache propagation stays real, reproducing the pre-change call sites.
        with ExitStack() as stack:
            for name in ("validate_attempt", "validate_context", "validate_completion"):
                original = getattr(self.h, name)
                def call(*args, _original=original, **kwargs):
                    kwargs.pop("cache", None)
                    return _original(*args, **kwargs)
                stack.enter_context(mock.patch.object(self.h, name, side_effect=call))
            yield

    def transition(self, helper=None, project=None):
        return (helper or self.h).validate_transition(project or self.p.root,
                                                     self.previous, self.candidate, {})

    def tree(self):
        return {p.relative_to(self.p.root).as_posix(): self.h.sha(p.read_bytes())
                for p in self.p.root.rglob("*") if p.is_file()}

    def test_real_nested_runs_reused_only_within_one_transition_and_results_unchanged(self):
        before = self.tree()
        manifests = copy.deepcopy((self.previous, self.candidate))
        reports = [self.base.report("implementation", "start", "U-1"),
                   self.base.report("implementation", "complete", "U-1")]
        with self.original_transition_cache_behavior(), self.checkers() as uncached:
            self.assertIsNone(self.transition())
        with self.checkers() as cached:
            self.assertIsNone(self.transition())
        with self.checkers() as cold:
            self.assertIsNone(self.transition())
        self.assertGreater(len(uncached), len(cached), (uncached, cached))
        self.assertEqual(10, len(cached), cached)  # Four contexts plus two views of three attempts.
        self.assertTrue(all(count == 1 for count in Counter(cached).values()), cached)
        self.assertEqual(cached, cold)
        self.assertEqual(manifests, (self.previous, self.candidate))
        self.assertEqual(before, self.tree())
        self.assertEqual(reports, [self.base.report("implementation", "start", "U-1"),
                                   self.base.report("implementation", "complete", "U-1")])
        oldest = self.base.read(self.attempts[0])
        self.assertEqual("failed", oldest["outcome"])
        self.assertEqual("not_completed", oldest["acceptance"])
        self.assertEqual("failed", oldest["checks"][0]["execution_status"])
        fresh = next(x for x in self.candidate["verification"]["checks"] if x["check_id"] == "QA-02")
        self.assertEqual("not_run", fresh["execution_status"])
        self.assertNotIn("evidence", fresh)
        self.assertIsNone(self.h._snapshot_hash_owner.get())
        self.assertIsNone(self.h._checker_audit_lease.get())

    @contextmanager
    def after_first_attempt(self, mutation):
        original, seen = self.h.validate_attempt, []
        def validate(project, reference, *args, **kwargs):
            result = original(project, reference, *args, **kwargs)
            if reference == self.attempts[0] and "cache" in kwargs and not seen:
                seen.append(True)
                mutation(kwargs["cache"])
            return result
        with mock.patch.object(self.h, "validate_attempt", side_effect=validate):
            yield seen
        self.assertEqual([True], seen)

    def test_warmed_unused_ancestor_corruption_rejects_before_stage_or_activation_writes(self):
        self.m.clear()
        self.m.update(self.previous)
        self.p.save()
        expected = self.p.hash("forge/sdd-manifest.json")
        staged = self.h.stage_candidate(self.p.root, self.candidate, expected)
        payload = self.unused.read_bytes()
        for operation in ("stage", "activate"):
            with self.subTest(operation=operation):
                self.unused.write_bytes(payload)
                def corrupt(cache):
                    self.assertIn(("attempt", self.attempts[0]["content_hash"]), cache)
                    self.unused.write_bytes(b"Corrupted after ancestor semantic validation.\n")
                with self.after_first_attempt(corrupt), \
                        mock.patch.object(self.h, "write_new", wraps=self.h.write_new) as writes, \
                        mock.patch.object(self.h, "store_record", wraps=self.h.store_record) as records, \
                        mock.patch.object(self.h.os, "replace", wraps=self.h.os.replace) as replace:
                    with self.assertRaisesRegex(ValueError, "changed"):
                        if operation == "stage":
                            self.h.stage_candidate(self.p.root, self.candidate, expected)
                        else:
                            self.h.activate_candidate(self.p.root, staged, expected)
                    writes.assert_not_called()
                    records.assert_not_called()
                    replace.assert_not_called()
                self.assertEqual(expected, self.p.hash("forge/sdd-manifest.json"))
                self.assertFalse((self.p.root / "forge/unit-history/activation.lock").exists())
                self.assertIsNone(self.h._snapshot_hash_owner.get())

    def test_warmed_reference_is_read_again_and_changed_bytes_rejected(self):
        path = self.p.root / self.attempts[0]["path"]
        def corrupt(cache):
            path.write_bytes(path.read_bytes() + b" ")
        with self.after_first_attempt(corrupt), \
                mock.patch.object(self.h, "read_ref", wraps=self.h.read_ref) as reads:
            with self.assertRaises(ValueError) as rejected:
                self.transition()
            self.assertIn(self.attempts[0]["path"], str(rejected.exception))
        self.assertGreater(sum(call.args[1] == self.attempts[0] for call in reads.call_args_list), 1)
        self.assertIsNone(self.h._snapshot_hash_owner.get())

    def test_warmed_attempt_cannot_hide_changed_ancestor_context_envelope(self):
        reference = self.base.read(self.attempts[0])["context_ref"]
        path = self.p.root / reference["path"]
        original = path.read_bytes()
        for uncached in (True, False):
            with self.subTest(pre_change_cache_behavior=uncached):
                path.write_bytes(original)
                behavior = self.original_transition_cache_behavior() if uncached else nullcontext()
                def corrupt(cache):
                    path.write_bytes(original + b" ")
                with behavior, self.after_first_attempt(corrupt):
                    before = self.p.hash("forge/sdd-manifest.json") if (self.p.root / "forge/sdd-manifest.json").exists() else None
                    with self.assertRaises(ValueError) as rejected:
                        self.transition()
                    self.assertIn(reference["path"], str(rejected.exception))
                    if before is not None:
                        self.assertEqual(before, self.p.hash("forge/sdd-manifest.json"))

    def test_warmed_ancestor_envelope_blocks_stage_and_activation_before_writes(self):
        self.m.clear()
        self.m.update(self.previous)
        self.p.save()
        expected = self.p.hash("forge/sdd-manifest.json")
        staged = self.h.stage_candidate(self.p.root, self.candidate, expected)
        reference = self.base.read(self.attempts[0])["context_ref"]
        path = self.p.root / reference["path"]
        original = path.read_bytes()
        for operation in ("stage", "activate"):
            with self.subTest(operation=operation):
                path.write_bytes(original)
                def corrupt(cache):
                    path.write_bytes(original + b" ")
                with self.after_first_attempt(corrupt), \
                        mock.patch.object(self.h, "write_new", wraps=self.h.write_new) as writes, \
                        mock.patch.object(self.h, "store_record", wraps=self.h.store_record) as records, \
                        mock.patch.object(self.h.os, "replace", wraps=self.h.os.replace) as replace:
                    with self.assertRaises(ValueError) as rejected:
                        if operation == "stage":
                            self.h.stage_candidate(self.p.root, self.candidate, expected)
                        else:
                            self.h.activate_candidate(self.p.root, staged, expected)
                    self.assertIn(reference["path"], str(rejected.exception))
                    writes.assert_not_called()
                    records.assert_not_called()
                    replace.assert_not_called()
                self.assertEqual(expected, self.p.hash("forge/sdd-manifest.json"))
                self.assertFalse((self.p.root / "forge/unit-history/activation.lock").exists())

    def test_warmed_attempt_keeps_cycle_depth_guards_and_detects_run_collision(self):
        def reject(cache):
            for stack in ((self.attempts[0]["content_hash"],), ("unrelated",) * 128):
                with self.assertRaisesRegex(ValueError, "cyclic/excessive attempt"):
                    self.h.validate_attempt(self.p.root, self.attempts[0], stack, cache)
            record = self.base.read(self.attempts[0])
            record["captured_at"] = self.base.now()
            collision = self.h.write_new(self.p.root, "forge/unit-history/synthetic-collision.json",
                                         self.h.encoded(record))
            with self.assertRaisesRegex(ValueError, "attempt run identity was reused"):
                self.h.validate_attempt(self.p.root, collision, cache=cache)
        with self.after_first_attempt(reject):
            self.transition()

    def test_warmed_cache_preserves_context_authority_chronology_history_and_fresh_checks(self):
        reference = self.candidate["execution_contexts"]["U-1"]
        original_ref, original = copy.deepcopy(reference), self.base.read(reference)
        for mutation, message in (("authority", "authority"), ("chronology", "future execution context"),
                                  ("history", "dropped an earlier attempt"), ("run", "old run identity"),
                                  ("checks", "cannot reuse old acceptance results"),
                                  ("unit", "belongs to another unit")):
            with self.subTest(mutation=mutation):
                changed = copy.deepcopy(original)
                if mutation == "authority":
                    changed["manifest"]["implementation_gate"]["prompt_id"] = "substituted-authority"
                elif mutation == "chronology":
                    changed["captured_at"] = "2999-01-01T00:00:00+00:00"
                elif mutation == "history":
                    changed["manifest"]["attempt_history"]["U-1"] = [self.attempts[-1]]
                elif mutation == "run":
                    changed["manifest"]["unit_runs"]["U-1"]["run_id"] = "synthetic-attempt-1"
                elif mutation == "checks":
                    next(x for x in changed["manifest"]["verification"]["checks"]
                         if x["check_id"] == "QA-02")["execution_status"] = "passed"
                else:
                    changed["unit_id"] = "U-2"
                self.base.rewrite(reference, changed)
                with self.after_first_attempt(lambda cache: None):
                    with self.assertRaisesRegex(ValueError, message):
                        self.transition()
                self.assertIsNone(self.h._snapshot_hash_owner.get())
                reference.clear()
                reference.update(original_ref)
                self.p.write(reference["path"], json.dumps(original, ensure_ascii=False) + "\n")

    def test_new_project_and_separate_helper_receive_cold_semantic_caches(self):
        with self.checkers() as first:
            self.transition()
        caches = []
        original = self.h.validate_attempt
        def capture(*args, **kwargs):
            if "cache" in kwargs:
                if not caches or kwargs["cache"] is not caches[-1]:
                    caches.append(kwargs["cache"])
                    self.assertEqual({}, caches[-1])
            return original(*args, **kwargs)
        with mock.patch.object(self.h, "validate_attempt", side_effect=capture), self.checkers() as second:
            self.transition()
        self.assertEqual(first, second)
        self.assertEqual(1, len(caches))
        # Another physical project must revalidate even identical reference keys.
        with tempfile.TemporaryDirectory(prefix="sdd-transition-other-project-") as other:
            project = Path(other) / "project"
            shutil.copytree(self.p.root, project)
            with self.checkers() as third:
                self.transition(project=project)
            self.assertEqual(first, third)
            (project / self.unused.relative_to(self.p.root)).write_text("Other project corruption.\n")
            with self.assertRaisesRegex(ValueError, "snapshot changed"):
                self.transition(project=project)
        # A separately loaded helper cannot inherit this helper's ContextVars.
        spec = importlib.util.spec_from_file_location("transition_independent_history", self.h.__file__)
        other_helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(other_helper)
        with self.checkers(other_helper) as fourth:
            self.transition(helper=other_helper)
        self.assertEqual(first, fourth)
        self.assertIsNone(other_helper._snapshot_hash_owner.get())


class RawReferenceClosureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sdd-raw-reference-closure-")
        self.addCleanup(self.temp.cleanup)
        self.root, self.h = Path(self.temp.name), sdd.history_api()

    def reference(self, name="contexts/synthetic.json", payload=b'{"value":1}'):
        relative = "forge/unit-history/" + name
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return {"path": relative, "content_hash": self.h.sha(payload)}

    def test_context_attempt_completion_runtime_and_legacy_controls_join_full_union(self):
        for name in ("contexts", "attempts", "completions", "runtime", "legacy"):
            with self.subTest(control=name):
                reference = self.reference(name + "/synthetic.json")
                target = self.root / reference["path"]
                with self.assertRaises(ValueError) as rejected:
                    with self.h.snapshot_hash_scope() as owner:
                        with self.h.snapshot_hash_scope(audit=True):
                            self.assertEqual({"value": 1}, self.h.read_ref(self.root, reference))
                        self.assertIn(target, owner.hashes)
                        target.write_bytes(target.read_bytes() + b" ")
                self.assertIn(str(target), str(rejected.exception))
                self.assertEqual({}, owner.hashes)
                self.assertIsNone(self.h._snapshot_hash_owner.get())

    def test_real_completion_cache_retains_skipped_context_envelope_until_outer_audit(self):
        base = attempt_fixture.history_fixture.UnitHistoryTests("runTest")
        base.setUp()
        self.addCleanup(base.doCleanups)
        helper, _, context, completion = base.capture_alpha()
        target = base.p.root / context["path"]
        cache = {}
        original = helper.api().Checker.run
        with self.assertRaises(ValueError) as rejected:
            with helper.snapshot_hash_scope():
                with mock.patch.object(helper.api().Checker, "run", autospec=True, side_effect=original) as checks:
                    helper.validate_completion(base.p.root, completion, cache=cache)
                    first = checks.call_count
                    self.assertGreater(first, 0)
                    helper.validate_completion(base.p.root, completion, cache=cache)
                    self.assertEqual(first, checks.call_count)
                    target.write_bytes(target.read_bytes() + b" ")
                    helper.validate_completion(base.p.root, completion, cache=cache)
                    self.assertEqual(first, checks.call_count)
        self.assertIn(str(target), str(rejected.exception))

    def test_real_runtime_observation_and_legacy_manifest_remain_in_outer_audit(self):
        runtime = self.h.observe_runtime(self.root, {"runtime": [sys.executable, "--version"]})
        target = self.root / runtime["path"]
        with self.assertRaises(ValueError) as rejected:
            with self.h.snapshot_hash_scope():
                self.h.validate_runtime_observation(self.root, runtime)
                target.write_bytes(target.read_bytes() + b" ")
        self.assertIn(str(target), str(rejected.exception))
        base = attempt_fixture.history_fixture.UnitHistoryTests("runTest")
        base.setUp()
        self.addCleanup(base.doCleanups)
        base.p.save()
        helper = base.history()
        staged = helper.adopt_legacy(base.p.root, base.p.hash("forge/sdd-manifest.json"))
        candidate = base.read(staged)["manifest"]
        legacy = base.read(candidate["legacy_history"][-1])
        target = base.p.root / legacy["manifest_ref"]["path"]
        with self.assertRaises(ValueError) as rejected:
            with helper.snapshot_hash_scope():
                helper.validate_transition(base.p.root, base.m, candidate, {})
                target.write_bytes(target.read_bytes() + b" ")
        self.assertIn(str(target), str(rejected.exception))

    def test_direct_warm_reference_still_reads_raw_hash_and_bounded_parser_every_time(self):
        reference = self.reference()
        parser = self.h.api().read_json
        with self.h.snapshot_hash_scope(), \
                mock.patch.object(self.h, "sha", wraps=self.h.sha) as hashes, \
                mock.patch.object(self.h.api(), "read_json", wraps=parser) as parses:
            self.assertEqual({"value": 1}, self.h.read_ref(self.root, reference))
            self.assertEqual({"value": 1}, self.h.read_ref(self.root, reference))
            self.assertEqual(2, hashes.call_count)
            self.assertEqual(2, parses.call_count)
            wrong = dict(reference, content_hash="0" * 64)
            with self.assertRaisesRegex(ValueError, "changed history file"):
                self.h.read_ref(self.root, wrong)
        target = self.root / reference["path"]
        target.write_bytes(b'{"value":2}')
        with self.assertRaisesRegex(ValueError, "changed history file"):
            self.h.read_ref(self.root, reference)

    def test_raw_read_to_parse_and_postparse_mutations_reject_exact_target(self):
        parser = self.h.api().read_json
        for timing in ("before_parse", "after_parse"):
            for mutation in ("equal_size_restored_mtime", "replace", "hardlink", "delete", "symlink"):
                with self.subTest(timing=timing, mutation=mutation):
                    reference = self.reference(timing + "/" + mutation + ".json")
                    target = self.root / reference["path"]
                    def change():
                        info = target.stat()
                        if mutation == "delete":
                            target.unlink()
                        elif mutation == "replace":
                            successor = target.with_suffix(".replacement")
                            successor.write_bytes(b'{"value":2}')
                            os.replace(successor, target)
                        elif mutation == "symlink":
                            successor = target.with_suffix(".symlink-target")
                            successor.write_bytes(b'{"value":2}')
                            target.unlink()
                            target.symlink_to(successor)
                        else:
                            alias = target
                            if mutation == "hardlink":
                                alias = target.with_suffix(".alias")
                                os.link(target, alias)
                            alias.write_bytes(b'{"value":2}')
                            os.utime(target, ns=(info.st_atime_ns, info.st_mtime_ns))
                    def parse(path):
                        if timing == "before_parse":
                            change()
                        value = parser(path)
                        if timing == "after_parse":
                            change()
                        return value
                    try:
                        with self.assertRaises((ValueError, OSError)) as rejected:
                            with self.h.snapshot_hash_scope(), mock.patch.object(self.h.api(), "read_json", side_effect=parse):
                                self.h.read_ref(self.root, reference)
                        self.assertIn(str(target), str(rejected.exception))
                    finally:
                        if target.is_symlink():
                            target.unlink()

    def test_exception_exit_audits_controls_after_nested_child_return(self):
        reference = self.reference()
        target = self.root / reference["path"]
        with self.assertRaises(ValueError) as rejected:
            with self.h.snapshot_hash_scope() as owner:
                with self.h.snapshot_hash_scope(audit=True):
                    self.h.read_ref(self.root, reference)
                target.write_bytes(target.read_bytes() + b" ")
                raise RuntimeError("synthetic failure after child return")
        self.assertIn(str(target), str(rejected.exception))
        self.assertIsInstance(rejected.exception.__context__, RuntimeError)
        self.assertEqual({}, owner.hashes)
        self.assertIsNone(self.h._snapshot_hash_owner.get())

    def test_invalid_json_never_publishes_results_and_scope_clears(self):
        for payload in (b'{"duplicate":1,"duplicate":2}', b'{"number":NaN}', b'\xff', b'{'):
            reference = self.reference(payload=payload)
            with self.assertRaises((ValueError, UnicodeError)):
                with self.h.snapshot_hash_scope() as owner:
                    self.h.read_ref(self.root, reference)
            self.assertEqual({}, owner.hashes)
            self.assertEqual([], owner.history_results)
            self.assertIsNone(self.h._snapshot_hash_owner.get())

    def test_outside_owner_depth_zero_and_cold_next_scope_do_not_reuse_eligibility(self):
        reference = self.reference()
        stale = self.h.api().SnapshotFileHashes()
        token = self.h._snapshot_hash_owner.set(stale)
        try:
            with mock.patch.object(stale, "file_hash", side_effect=AssertionError("depth-zero owner used")):
                self.assertEqual({"value": 1}, self.h.read_ref(self.root, reference))
        finally:
            self.h._snapshot_hash_owner.reset(token)
        self.assertEqual({}, stale.hashes)
        self.assertEqual({"value": 1}, self.h.read_ref(self.root, reference))
        with self.h.snapshot_hash_scope() as first:
            self.h.read_ref(self.root, reference)
        self.assertEqual({}, first.hashes)
        target = self.root / reference["path"]
        target.write_bytes(b'{"value":2}')
        with self.assertRaisesRegex(ValueError, "changed history file"):
            with self.h.snapshot_hash_scope() as second:
                self.assertIsNot(first, second)
                self.h.read_ref(self.root, reference)
        self.assertEqual({}, second.hashes)

    def test_separate_sdk_root_and_fresh_process_revalidate_raw_controls(self):
        reference = self.reference()
        with self.h.snapshot_hash_scope():
            self.h.read_ref(self.root, reference)
        scripts = self.root / "separate-sdk/scripts"
        shutil.copytree(SCRIPT.parent, scripts, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        body = """
import json, pathlib, sys
sys.path.insert(0, sys.argv[1])
import sdd_check
h = sdd_check.history_api()
assert pathlib.Path(h.__file__).resolve().parent == pathlib.Path(sys.argv[1]).resolve()
assert h._snapshot_hash_owner.get() is None
with h.snapshot_hash_scope() as owner:
    try:
        h.read_ref(pathlib.Path(sys.argv[2]), json.loads(sys.argv[3]))
    except ValueError as error:
        assert sys.argv[4] == 'reject' and 'changed history file' in str(error), str(error)
    else:
        assert sys.argv[4] == 'accept'
assert not owner.hashes and owner.depth == 0
"""
        arguments = [sys.executable, "-B", "-c", body, str(scripts), str(self.root), json.dumps(reference)]
        accepted = subprocess.run(arguments + ["accept"], capture_output=True, text=True)
        self.assertEqual(0, accepted.returncode, accepted.stdout + accepted.stderr)
        (self.root / reference["path"]).write_bytes(b'{"value":2}')
        rejected = subprocess.run(arguments + ["reject"], capture_output=True, text=True)
        self.assertEqual(0, rejected.returncode, rejected.stdout + rejected.stderr)


if __name__ == "__main__":
    unittest.main()
