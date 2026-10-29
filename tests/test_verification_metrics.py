"""Bounded opt-in diagnostics cannot supply or change acceptance outcomes."""
from contextlib import ExitStack
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/to-sdd-pipeline/scripts"))
import verification_metrics as metrics


class VerificationMetricsTests(unittest.TestCase):
    def test_disabled_collection_does_not_consult_clock_or_retain_data(self):
        with mock.patch.object(metrics, "perf_counter_ns", side_effect=AssertionError("disabled clock")):
            with metrics.collect(False) as observation:
                with metrics.phase("root_gate"):
                    metrics.count("path_checks", 5)
            result = observation.snapshot()
        self.assertEqual({}, result["counters"])
        self.assertEqual({}, result["phases"])
        self.assertEqual(0, result["elapsed_seconds"])

    def test_nested_time_is_attributed_without_double_counting_exclusive_work(self):
        with mock.patch.object(metrics, "perf_counter_ns", side_effect=[0, 10, 20, 50, 100, 120]):
            with metrics.collect() as observation:
                with metrics.phase("root_gate"):
                    with metrics.phase("historical_gate"):
                        metrics.count("history_context_requests", 2)
                        metrics.count("history_context_cache_hits")
        result = observation.snapshot()
        root, child = result["phases"]["root_gate"], result["phases"]["historical_gate"]
        self.assertEqual(90e-9, root["inclusive_seconds"])
        self.assertEqual(60e-9, root["exclusive_seconds"])
        self.assertEqual(30e-9, child["exclusive_seconds"])
        self.assertEqual(2, result["counters"]["history_context_requests"])
        self.assertEqual(1, result["counters"]["history_context_cache_hits"])

    def test_exceptions_propagate_and_nested_collections_restore_prior_scope(self):
        @metrics.timed("history_context")
        def invalid():
            raise ValueError("original validation failure")
        with metrics.collect() as outer:
            metrics.count("path_checks")
            with metrics.collect() as inner:
                with self.assertRaisesRegex(ValueError, "original validation failure"):
                    invalid()
            metrics.count("path_checks")
        self.assertEqual(2, outer.snapshot()["counters"]["path_checks"])
        self.assertEqual({}, inner.snapshot()["counters"])
        self.assertEqual(1, inner.snapshot()["phases"]["history_context"]["errors"])
        self.assertEqual({}, outer.snapshot()["phases"])

    def test_fixed_labels_and_depth_bound_prevent_unbounded_reports(self):
        with metrics.collect() as observation:
            with self.assertRaises(ValueError):
                metrics.count("a/path/that/must/not/be/retained")
            with self.assertRaises(ValueError):
                with metrics.phase("dynamic-label"):
                    pass
            with ExitStack() as stack:
                for _ in range(metrics.MAX_DEPTH + 10):
                    stack.enter_context(metrics.phase("history_context"))
            metrics.count("path_checks", metrics.MAX_COUNT)
            metrics.count("path_checks")
        result = observation.snapshot()
        self.assertEqual(10, result["counters"]["timing_depth_limited"])
        self.assertTrue(result["saturated"])
        self.assertLess(len(json.dumps(result)), 1200)
        self.assertNotIn("a/path", json.dumps(result))
        result["counters"]["path_checks"] = 0
        self.assertEqual(metrics.MAX_COUNT, observation.snapshot()["counters"]["path_checks"])

    def test_real_context_cache_hits_are_counted_without_changing_validation(self):
        import test_unit_history as fixtures
        fixture = fixtures.UnitHistoryTests("runTest")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        helper, _, context, _ = fixture.capture_alpha(finish=False)
        cache = {}
        with metrics.collect() as observation, helper.snapshot_hash_scope():
            first = helper.validate_context(fixture.p.root, context, "U-1", cache=cache)
            second = helper.validate_context(fixture.p.root, context, "U-1", cache=cache)
        self.assertEqual(first, second)
        counters = observation.snapshot()["counters"]
        self.assertEqual(2, counters["history_context_requests"])
        self.assertEqual(1, counters["history_context_cache_hits"])

    def test_cli_performance_is_opt_in_and_keeps_the_gate_result(self):
        import test_unit_history as fixtures
        from test_sdd_check import SCRIPT
        fixture = fixtures.UnitHistoryTests("runTest")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.capture_alpha(finish=False)
        fixture.p.save()
        args = [sys.executable, "-B", str(SCRIPT), "--project", str(fixture.p.root), "--start-unit", "U-1"]
        ordinary = subprocess.run(args, capture_output=True, text=True, check=False)
        measured = subprocess.run(args + ["--performance"], capture_output=True, text=True, check=False)
        plain, detailed = json.loads(ordinary.stdout), json.loads(measured.stdout)
        self.assertEqual(0, ordinary.returncode, ordinary.stdout + ordinary.stderr)
        self.assertEqual(ordinary.returncode, measured.returncode, measured.stdout + measured.stderr)
        self.assertNotIn("performance", plain)
        performance = detailed.pop("performance")
        self.assertEqual(plain, detailed)
        self.assertTrue(performance["enabled"])
        self.assertGreaterEqual(performance["phases"]["root_gate"]["calls"], 1)
        self.assertGreater(performance["counters"]["history_context_requests"], 0)
        self.assertNotIn(str(fixture.p.root), json.dumps(performance))

    def test_io_counters_measure_work_without_weakening_mutation_checks(self):
        from test_sdd_check import sdd
        with tempfile.TemporaryDirectory(prefix="sdd-metrics-") as name:
            root = Path(name).resolve()
            source = root / "source.txt"
            source.write_bytes(b"abc")
            document = root / "observation.json"
            payload = b'{"result":"observed"}'
            document.write_bytes(payload)
            checker = sdd.Checker(root, {})
            with metrics.collect() as observation:
                first = checker.file_hash(source)
                self.assertEqual(first, checker.file_hash(source))
                self.assertEqual(checker.document(document), checker.document(document))
                source.write_bytes(b"changed")
                with self.assertRaisesRegex(ValueError, "input changed"):
                    checker.file_hash(source)
            counters = observation.snapshot()["counters"]
            self.assertEqual(3, counters["source_hash_requests"])
            self.assertEqual(3, counters["source_hash_bytes"])
            self.assertEqual(1, counters["json_parse_requests"])
            self.assertEqual(1, counters["json_cache_hits"])
            self.assertEqual(len(payload), counters["json_parse_bytes"])


if __name__ == "__main__":
    unittest.main()
