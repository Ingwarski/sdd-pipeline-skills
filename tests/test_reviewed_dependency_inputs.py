"""Synthetic dependency changes invalidate consumers even with complete coverage."""
import copy
from pathlib import Path
from types import SimpleNamespace
import unittest

from test_sdd_check import sdd  # Loads the scripts directory for focused module tests.
import check_inputs


class ReviewedDependencyInputTests(unittest.TestCase):
    def checker_and_inventory(self):
        paths = ["src/base.py", "src/foundation.py", "src/component.py", "src/consumer.py"]
        units = {name: {"implementation_paths": [path], "construction_dependencies": dependencies,
                        "required_check_ids": [check]}
                 for name, path, dependencies, check in (
                     ("BASE", paths[0], [], "QA-B"),
                     ("FOUNDATION", paths[1], ["BASE"], "QA-F"),
                     ("COMPONENT", paths[2], ["FOUNDATION"], "QA-P"),
                     ("CONSUMER", paths[3], [], "QA-C"))}
        units["CONSUMER"]["required_check_ids"].append("QA-S")
        allocations = {check: {"owner_unit": unit, "prerequisite_checks": [], "prerequisite_units": []}
                       for check, unit in (("QA-B", "BASE"), ("QA-F", "FOUNDATION"),
                                           ("QA-P", "COMPONENT"), ("QA-C", "CONSUMER"), ("QA-S", "CONSUMER"))}
        allocations["QA-C"]["prerequisite_checks"] = ["QA-P"]
        checks = [{"check_id": key, "acceptance": {"required_source_paths": required,
                   "dependency_review": {"complete": True, "reviewer": "synthetic owner",
                                         "rationale": "Explicit synthetic dependency graph."}}}
                  for key, required in (("QA-B", paths[:1]), ("QA-F", paths[1:2]),
                                        ("QA-P", paths[2:3]), ("QA-C", paths[3:]), ("QA-S", paths[:2]))]
        manifest = {"checker_contract_version": 4, "unit_contract_version": 4,
                    "unit_plan": {"units": units, "acceptance": allocations},
                    "verification": {"checks": checks}}
        checker = SimpleNamespace(manifest=manifest, path=lambda path, **kwargs: Path(path))
        inventory = {"inputs": {}, "environment": {}, "bindings": {},
                     "execution_inputs": {path: {"mode": "file"} for path in paths},
                     "execution_fingerprints": {path: {"mode": "file", "exists": True,
                                                       "content_hash": "a" * 64} for path in paths}}
        return checker, inventory

    def assert_dependency_change_invalidates_consumer(self, checker, inventory):
        # QA-S explicitly owns both foundation selections, so conservative
        # unassigned-input fallback cannot accidentally make QA-C pass this test.
        inventory["check_execution_fingerprints"] = check_inputs.fingerprints(checker, "CONSUMER", inventory)
        for path in ("src/foundation.py", "src/base.py"):
            with self.subTest(path=path):
                changed = copy.deepcopy(inventory)
                changed["execution_fingerprints"][path]["content_hash"] = "b" * 64
                changed["check_execution_fingerprints"] = check_inputs.fingerprints(checker, "CONSUMER", changed)
                self.assertEqual(check_inputs.changed_checks(inventory, changed, ["QA-C", "QA-S"]), ["QA-C", "QA-S"])
                selected = check_inputs.fingerprints(checker, "CONSUMER", changed, check_id="QA-C")
                self.assertEqual(selected, {"QA-C": changed["check_execution_fingerprints"]["QA-C"]})

    def test_prerequisite_owner_construction_dependencies_include_transitive_inputs(self):
        checker, inventory = self.checker_and_inventory()
        self.assert_dependency_change_invalidates_consumer(checker, inventory)

    def test_prerequisite_checks_unit_dependencies_include_transitive_inputs(self):
        checker, inventory = self.checker_and_inventory()
        checker.manifest["unit_plan"]["units"]["COMPONENT"]["construction_dependencies"] = []
        checker.manifest["unit_plan"]["acceptance"]["QA-P"]["prerequisite_units"] = ["FOUNDATION"]
        self.assert_dependency_change_invalidates_consumer(checker, inventory)


if __name__ == "__main__":
    unittest.main()
