#!/usr/bin/env python3
"""Read-only, stage-aware SDD consistency checks. Python 3.9+, standard library."""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
from datetime import datetime


CONTRACT = Path(__file__).resolve().parent.parent / "references/pipeline-contract.json"
HASH_RE = re.compile(r"^(?:sha256:)?([0-9a-fA-F]{64})$")
EXECUTION_STATES = {"not_run", "passed", "failed", "blocked", "deferred", "not_applicable"}
GATE_KINDS = {
    "approved_visual_baseline_fidelity": "visual",
    "heuristic_usability_review": "heuristic",
    "representative_user_task_validation": "representative_user",
}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key: " + key)
        result[key] = value
    return result


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=unique_object,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("invalid JSON: " + value)))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def hash_matches(recorded, observed):
    match = HASH_RE.fullmatch(recorded) if isinstance(recorded, str) else None
    return bool(match and match.group(1).lower() == observed)


def is_link(path):
    info = path.lstat()
    return path.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def tree_hash(root):
    """sdd-tree-sha256-v1: byte-sorted POSIX paths; every regular file, no exclusions."""
    root = Path(root)
    if not root.is_dir() or is_link(root):
        raise ValueError("prototype root must be a frozen real directory")
    entries = []
    def walk_error(error):
        raise error

    for directory, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
        for name in dirs + files:
            path = Path(directory) / name
            if is_link(path):
                raise ValueError("freeze link/reparse target as regular files: " + str(path))
        for name in files:
            path = Path(directory) / name
            if not path.is_file():
                raise ValueError("not a regular prototype file: " + str(path))
            relative = path.relative_to(root).as_posix()
            if "\n" in relative or "\r" in relative:
                raise ValueError("newline in prototype path")
            entries.append((relative, digest(path.read_bytes())))
    if not entries:
        raise ValueError("empty prototype source tree")
    entries.sort(key=lambda item: item[0].encode("utf-8"))
    return digest("".join(path + "\n" + value + "\n" for path, value in entries).encode("utf-8"))


def section_bytes(path, heading):
    """Exact unique Markdown ATX heading, through the next equal/higher heading."""
    if not isinstance(heading, str) or not re.match(r"^#{1,6} \S", heading):
        raise ValueError("fragment requires an exact Markdown heading, including #")
    lines = Path(path).read_bytes().splitlines(keepends=True)
    headings, fence = [], None
    for index, line in enumerate(lines):
        text = line.decode("utf-8").rstrip("\r\n").lstrip("\ufeff")
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})", text)
        if marker:
            run = marker[1]
            if fence is None:
                fence = run
            elif run[0] == fence[0] and len(run) >= len(fence):
                fence = None
            continue
        match = re.match(r"^(#{1,6})[ \t]+", text) if fence is None else None
        if match:
            headings.append((index, len(match[1]), text))
    matches = [index for index, _, text in headings if text == heading]
    if len(matches) != 1:
        raise ValueError("fragment heading must occur exactly once: " + heading)
    start = matches[0]
    level = len(heading.split(" ", 1)[0])
    end = len(lines)
    for index, depth, _ in headings:
        if index > start and depth <= level:
            end = index
            break
    return b"".join(lines[start:end])


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("timestamp missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp needs a timezone")
    return parsed


def read_contract():
    contract = read_json(CONTRACT)
    nodes = {key: {"required_before": list(spec["required_before"]), "outputs": [key]}
             for key, spec in contract["artifacts"].items()}
    for key, spec in contract["nodes"].items():
        owner = spec.get("owner_artifact")
        if owner and owner not in nodes:
            raise ValueError("unknown node owner artifact: " + owner)
        nodes[key] = {**(nodes[owner] if owner else {}), **spec}
    contract["nodes"] = nodes
    return contract


def validate_contract(contract):
    if contract.get("schema_version") != 1:
        raise ValueError("unsupported pipeline contract")
    artifacts = contract["artifacts"]
    visiting, visited = set(), set()

    def visit(key):
        if key in visiting:
            raise ValueError("required-before dependency cycle: " + key)
        if key not in artifacts:
            raise ValueError("unknown prerequisite: " + key)
        if key in visited:
            return
        visiting.add(key)
        for dependency in artifacts[key]["required_before"]:
            visit(dependency)
        visiting.remove(key)
        visited.add(key)

    for key in artifacts:
        visit(key)
    for node in contract["nodes"].values():
        for key in node["required_before"] + node["outputs"]:
            if key not in artifacts:
                raise ValueError("unknown node artifact: " + key)


class Checker:
    def __init__(self, project, manifest, contract=None):
        self.project = Path(project).resolve()
        self.manifest = manifest
        self.contract = contract or read_contract()
        validate_contract(self.contract)
        self.specs = self.contract["artifacts"]
        self.artifacts = manifest.get("artifacts", {})
        if not isinstance(self.artifacts, dict):
            raise ValueError("artifacts must be an object")
        self.issues, self.warnings = [], []
        self.checked, self.affected = set(), set()

    def issue(self, code, target, detail):
        item = {"code": code, "target": target, "detail": detail}
        if item not in self.issues:
            self.issues.append(item)
        if target in self.specs:
            self.affected.add(target)

    def path(self, relative, no_links=False):
        if not isinstance(relative, str) or not relative or "\\" in relative:
            raise ValueError("use a nonempty repository-relative POSIX path")
        parsed = PurePosixPath(relative)
        if parsed.is_absolute() or ".." in parsed.parts or ":" in parsed.parts[0]:
            raise ValueError("path escapes project: " + relative)
        resolved = (self.project / relative).resolve()
        if not resolved.is_relative_to(self.project):
            raise ValueError("link escapes project: " + relative)
        if no_links:
            current = self.project
            for part in parsed.parts:
                current = current / part
                if is_link(current):
                    raise ValueError("frozen source path contains a link/reparse point: " + relative)
        return resolved

    def snapshot(self, relative, recorded, target, code="stale_source"):
        try:
            observed = digest(self.path(relative).read_bytes())
            if not hash_matches(recorded, observed):
                self.issue(code, target, "missing/changed hash: " + relative)
                return False
            return True
        except (ValueError, OSError) as error:
            self.issue(code, target, str(error))
            return False

    @staticmethod
    def reference_path(reference):
        return reference.get("path", "") if isinstance(reference, dict) else str(reference).split("#", 1)[0]

    def reference(self, reference, target):
        try:
            if isinstance(reference, dict):
                path, heading = reference["path"], reference["heading"]
            else:
                path, heading = reference.split("#", 1)
            return section_bytes(self.path(path), heading).decode("utf-8")
        except (AttributeError, KeyError, ValueError, OSError) as error:
            self.issue("invalid_reference", target, str(error))
            return ""

    def sources(self, entry, target, required=()):
        hashes = entry.get("source_hashes", {})
        fragments = entry.get("consumed_source_fragments", {})
        if not isinstance(hashes, dict) or not isinstance(fragments, dict):
            self.issue("invalid_provenance", target, "source hashes/fragments must be objects")
            return
        for path, value in hashes.items():
            self.snapshot(path, value, target)
        for path, records in fragments.items():
            if path in hashes:
                self.issue("duplicate_provenance", target, "use a full hash OR fragments: " + path)
            if not isinstance(records, list) or not records:
                self.issue("invalid_fragment", target, "expected a nonempty fragment list: " + path)
                continue
            for record in records:
                try:
                    current = digest(section_bytes(self.path(path), record["heading"]))
                    if not hash_matches(record.get("content_hash"), current):
                        self.issue("stale_fragment", target, path + "#" + record["heading"])
                except (TypeError, KeyError, ValueError, OSError) as error:
                    self.issue("invalid_fragment", target, str(error))
        for dependency in required:
            # Context is relevance-scoped; its presence never requires invented consumption.
            if dependency in self.contract["context_bundle"]:
                continue
            path = self.specs[dependency]["path"]
            if path not in hashes and path not in fragments:
                self.issue("missing_source_snapshot", target, path)

    def artifact(self, key):
        if key in self.checked:
            return
        self.checked.add(key)
        spec = self.specs[key]
        for dependency in spec["required_before"]:
            self.artifact(dependency)
        entry = self.artifacts.get(key)
        if not isinstance(entry, dict):
            self.issue("missing_artifact", key, spec["path"])
            return
        if entry.get("path") != spec["path"] or entry.get("owner_skill") != spec["owner_skill"]:
            self.issue("wrong_owner_or_path", key, "expected " + spec["owner_skill"] + " -> " + spec["path"])
        self.snapshot(spec["path"], entry.get("content_hash"), key, "stale_artifact")
        if entry.get("status") != "validated":
            self.issue("not_validated", key, "artifact status is not validated")
        validation = entry.get("validation", {})
        if not isinstance(validation, dict) or validation.get("result", validation.get("status")) not in ("passed", "validated"):
            self.issue("missing_validation", key, "owner must record document-validation result")
        if not entry.get("owner_invocation_id"):
            self.issue("missing_invocation", key, "owner invocation is required")
        language = self.manifest.get("language", {}).get("working_language")
        if language and validation.get("working_language") != language:
            self.issue("language_revalidation", key, "validate prose against current working_language")
        declared = entry.get("dependencies", [])
        if not isinstance(declared, list) or not all(isinstance(item, str) for item in declared):
            self.issue("invalid_dependencies", key, "dependencies must be artifact IDs")
        else:
            expanded = set()
            for item in declared:
                if item in self.contract["nodes"]:
                    expanded.update(self.contract["nodes"][item]["outputs"])
                else:
                    expanded.add(item)
            for item in expanded - set(spec["required_before"]):
                if item in spec["consulted_later"]:
                    self.warnings.append(key + ": later reference is not a prerequisite: " + item)
                else:
                    self.issue("unexpected_dependency", key, item)
            for item in set(spec["required_before"]) - expanded:
                self.issue("missing_dependency", key, item)
        self.sources(entry, key, spec["required_before"])
        observation = entry.get("repository_observation_id")
        if observation:
            record = self.manifest.get("repository_observations", {}).get(observation, {})
            if not record.get("commands") or not record.get("observed_at") or not record.get("paths"):
                self.issue("missing_observation", key, str(observation))
            else:
                for path, value in record["paths"].items():
                    if value is None:
                        try:
                            if self.path(path).exists():
                                self.issue("stale_observation", key, "formerly absent: " + path)
                        except ValueError as error:
                            self.issue("stale_observation", key, str(error))
                    else:
                        self.snapshot(path, value, key, "stale_observation")

    def bundle(self):
        keys = self.contract["context_bundle"]
        if not self.checked.intersection(keys):
            return
        for key in keys:
            self.artifact(key)
        records = [self.artifacts.get(key, {}) for key in keys]
        invocations = {record.get("owner_invocation_id") for record in records}
        outputs = {self.specs[key]["path"] for key in keys}
        if len(invocations) != 1 or None in invocations or any(set(record.get("declared_output_set", [])) != outputs for record in records):
            for key in keys:
                self.issue("incomplete_context_bundle", key, "both outputs need one invocation and the same two-file output set")

    def frozen(self, record, target):
        try:
            if record.get("hash_algorithm") != "sdd-tree-sha256-v1":
                raise ValueError("unknown prototype hash algorithm")
            observed = tree_hash(self.path(record.get("prototype_source_root"), no_links=True))
            if not hash_matches(record.get("prototype_tree_hash"), observed):
                self.issue("baseline_integrity", target, "prototype source tree changed")
            self.snapshot(record.get("visual_target_path"), record.get("visual_target_hash"), target, "visual_target_integrity")
        except (ValueError, OSError) as error:
            self.issue("baseline_integrity", target, str(error))

    def baseline(self):
        record = self.manifest.get("active_baseline", {})
        baseline_id = record.get("baseline_id")
        if not baseline_id or baseline_id != self.manifest.get("approved_baseline_id"):
            self.issue("missing_baseline", "design-brief", "current approved Baseline ID required")
            return
        self.frozen(record, "design-brief")
        text = self.reference(record.get("canonical_ref"), "design-brief")
        if self.reference_path(record.get("canonical_ref")) != "docs/design-brief.md":
            self.issue("baseline_projection_mismatch", "design-brief", "canonical baseline must be in the design brief")
        for value in (baseline_id, record.get("visual_target_hash"), record.get("prototype_tree_hash")):
            if not isinstance(value, str) or value not in text:
                self.issue("baseline_projection_mismatch", "design-brief", "canonical section must contain current ID and hashes")
        receipt = record.get("approval_receipt", {})
        if not isinstance(receipt, dict) or not self.snapshot(receipt.get("path"), receipt.get("content_hash"), "design-brief", "approval_receipt"):
            return
        try:
            approval = read_json(self.path(receipt["path"]))
            if approval.get("event") not in ("approve_design_baseline", "accepted_scoped_baseline_override") or not approval.get("actor"):
                raise ValueError("explicit operator approval/accepted override event required")
            for field in ("baseline_id", "visual_target_hash", "prototype_tree_hash"):
                if approval.get(field) != record.get(field):
                    raise ValueError("approval does not match current " + field)
            timestamp(approval.get("approved_at"))
            if receipt["path"] not in text:
                raise ValueError("approval receipt must be referenced by the canonical design section")
        except (ValueError, OSError, KeyError) as error:
            self.issue("approval_receipt", "design-brief", str(error))

    def source_access(self):
        handoff = self.manifest.get("design_execution", {})
        if handoff.get("mode") != "claude_design":
            return
        records = {}
        for key in ("source_manifest", "codex_access_receipt", "claude_source_read_receipt"):
            if not self.snapshot(handoff.get(key + "_path"), handoff.get(key + "_hash"), "design", "source_access_receipt"):
                return
            try:
                records[key] = read_json(self.path(handoff[key + "_path"]))
            except (OSError, ValueError) as error:
                self.issue("source_access_receipt", "design", str(error))
                return
        try:
            inventory = records["source_manifest"]
            materials = inventory["materials"]
            indexed = {item["material_id"]: item for item in materials}
            if not materials or len(indexed) != len(materials) or any(not key for key in indexed):
                raise ValueError("complete unique material IDs required")
            if inventory.get("language") != self.manifest.get("language"):
                raise ValueError("source manifest language must match the current handoff")
            if any(type(item.get("required")) is not bool for item in materials):
                raise ValueError("every material needs an explicit required flag")
            required = {key for key, item in indexed.items() if item["required"]}
            if not required or handoff.get("unresolved_required_source_ids") or any(
                type(handoff.get(key)) is not int or handoff[key] != len(required)
                for key in ("required_source_count", "codex_accessible_required_source_count", "claude_read_required_source_count")
            ):
                raise ValueError("required source counts must match the actual material IDs")
            manifest_hash = digest(self.path(handoff["source_manifest_path"]).read_bytes())
            for key, success in (("codex_access_receipt", "accessible"), ("claude_source_read_receipt", "read")):
                receipt = records[key]
                results = receipt["results"]
                by_id = {item["material_id"]: item for item in results}
                if len(by_id) != len(results) or set(by_id) != set(indexed) or required.intersection(receipt.get("unresolved_material_ids", [])):
                    raise ValueError(key + ": missing, duplicate or unresolved material IDs")
                if not hash_matches(receipt.get("manifest_hash"), manifest_hash):
                    raise ValueError(key + ": stale source manifest")
                for material_id in required:
                    observed, source = by_id[material_id], indexed[material_id]
                    field = "content_hash" if source.get("content_hash") else "capture_id"
                    if observed.get("status") != success or not source.get(field) or observed.get(field) != source[field]:
                        raise ValueError(key + ": unread or mismatched source " + material_id)
        except (KeyError, TypeError, AttributeError, ValueError) as error:
            self.issue("source_access_incomplete", "design", str(error))

    def candidates(self):
        records = [item for item in self.manifest.get("prototype_candidates", [])
                   if item.get("status") != "superseded" and not item.get("superseded_by")]
        active_set = self.manifest.get("design_execution", {}).get("active_candidate_set_id")
        if active_set:
            records = [item for item in records if item.get("candidate_set_id") == active_set]
        mode = self.manifest.get("design_execution", {}).get("mode")
        if mode == "claude_design":
            handoff = self.manifest["design_execution"]
            references = handoff.get("claude_candidate_references", [])
            selected = handoff.get("selected_candidate_version")
            if len(references) != 3 or len(set(references)) != 3 or len(records) != 1:
                self.issue("candidate_coverage", "design", "three Claude references and one selected normalized import required")
            if selected not in references or any(item.get("origin_reference") != selected for item in records):
                self.issue("candidate_selection", "design", "normalized import must match the exact selected Claude reference")
            self.source_access()
        elif mode != "codex" or len(records) != 3:
            self.issue("candidate_coverage", "design", "exactly three Codex candidates required")
        identities = set()
        for record in records:
            identity = (record.get("candidate_id"), record.get("version"))
            if not all(identity) or identity in identities:
                self.issue("candidate_identity", "design", "missing or duplicate candidate/version")
            identities.add(identity)
            self.frozen(record, "design")
            self.sources(record, "design", self.contract["nodes"]["prototype-candidates"]["required_before"])
            if not record.get("route") or not str(record.get("preview_url", "")).startswith(("http://", "https://")):
                self.issue("candidate_scope", "design", "stable live URL and route required")
            for field in ("browser_receipt", "visual_qa_evidence"):
                receipt = record.get(field, {})
                if not self.snapshot(receipt.get("path"), receipt.get("content_hash"), "design", field):
                    continue
                try:
                    actual = read_json(self.path(receipt["path"]))
                    for key in ("candidate_id", "version", "visual_target_hash", "prototype_tree_hash", "preview_url"):
                        if not record.get(key) or actual.get(key) != record[key]:
                            raise ValueError("receipt does not match current " + key)
                    timestamp(actual.get("observed_at"))
                    if actual.get("result") != "passed":
                        raise ValueError("candidate observation has not passed")
                    if field == "browser_receipt" and actual.get("browser_kind") != "external_default":
                        raise ValueError("external default browser receipt required")
                    if any(item.get("release_effect") == "blocking" and item.get("status") != "closed" for item in actual.get("findings", [])):
                        raise ValueError("candidate has an open blocking finding")
                except (OSError, ValueError, KeyError, TypeError) as error:
                    self.issue(field, "design", str(error))

    def verification(self, release=False, baseline_required=True):
        record = self.manifest.get("verification", {})
        release_claim = record.get("release_readiness") == "passed"
        if record.get("release_readiness") not in ("not_evaluated", "passed", "blocked"):
            self.issue("release_status", "qa-checklist", "release readiness must be not_evaluated, passed or blocked")
        if record.get("definition_status") != "prepared":
            self.issue("checks_not_prepared", "qa-checklist", "checks must be prepared, not assumed executed")
        self.sources(record, "qa-checklist", ("qa-checklist", "dod-evals"))
        checks, gates = record.get("checks", []), record.get("gates", [])
        if not isinstance(checks, list) or not isinstance(gates, list) or not checks or not gates:
            self.issue("missing_check_index", "qa-checklist", "nonempty hash-bound gate/check index required")
            return
        check_map = {}
        baseline_id = self.manifest.get("approved_baseline_id")
        for check in checks:
            key = check.get("check_id")
            if not key or key in check_map:
                self.issue("check_id", "qa-checklist", "missing or duplicate check ID")
                continue
            check_map[key] = check
            text = self.reference(check.get("definition_ref"), "qa-checklist")
            if key not in text or self.reference_path(check.get("definition_ref")) != "docs/qa-checklist.md":
                self.issue("unresolved_check", "qa-checklist", key)
            status = check.get("execution_status")
            if status not in EXECUTION_STATES or check.get("definition_status") != "prepared":
                self.issue("check_status", "qa-checklist", key)
            if check.get("phase") not in ("prototype", "implementation", "both"):
                self.issue("check_phase", "qa-checklist", key)
            if status in ("blocked", "deferred", "not_applicable") and not check.get("rationale"):
                self.issue("missing_rationale", "qa-checklist", key)
            if check.get("gate_id") in GATE_KINDS and status != "not_applicable":
                if baseline_required and (check.get("baseline_id") != baseline_id or check.get("target_hash") != self.manifest.get("active_baseline", {}).get("visual_target_hash")):
                    self.issue("stale_check_binding", "qa-checklist", key)
                if not all(check.get(field) for field in ("task", "user_group", "route", "state", "viewport")):
                    self.issue("missing_check_scope", "qa-checklist", key)
            if status in ("passed", "failed"):
                evidence = check.get("evidence", [])
                if not evidence or not check.get("executor"):
                    self.issue("unsupported_result", "qa-checklist", key + ": execution evidence/executor required")
                try:
                    timestamp(check.get("executed_at"))
                except ValueError as error:
                    self.issue("unsupported_result", "qa-checklist", key + ": " + str(error))
                kinds = set()
                for item in evidence:
                    self.snapshot(item.get("path"), item.get("content_hash"), "qa-checklist", "invalid_evidence")
                    kinds.add(item.get("kind"))
                expected_kind = GATE_KINDS.get(check.get("gate_id"))
                if expected_kind and expected_kind not in kinds:
                    self.issue("wrong_evidence_class", "qa-checklist", key + ": expected " + expected_kind)
                evaluated = check.get("evaluated_source_hashes", {})
                if check.get("phase") in ("implementation", "both") and not evaluated:
                    self.issue("missing_evaluated_revision", "qa-checklist", key)
                self.sources({"source_hashes": evaluated}, "qa-checklist")
            elif status == "not_run" and check.get("evidence"):
                self.issue("ambiguous_execution", "qa-checklist", key + ": not_run cannot claim executed evidence")
            for finding in check.get("findings", []):
                severity, effect = finding.get("severity"), finding.get("release_effect")
                if severity not in ("P0", "P1", "P2", "P3") or effect not in ("blocking", "advisory"):
                    self.issue("finding_classification", "qa-checklist", key)
                if severity in ("P0", "P1") and effect != "blocking":
                    self.issue("finding_classification", "qa-checklist", key + ": P0/P1 must block")
                if severity == "P3" and effect != "advisory":
                    self.issue("finding_classification", "qa-checklist", key + ": P3 is advisory")
                if (release or release_claim) and effect == "blocking" and finding.get("status") != "closed":
                    self.issue("open_blocking_finding", "qa-checklist", key)
        gate_ids = set()
        for gate in gates:
            key = gate.get("gate_id")
            if not key or key in gate_ids:
                self.issue("gate_id", "dod-evals", "missing or duplicate gate ID")
                continue
            gate_ids.add(key)
            text = self.reference(gate.get("definition_ref"), "dod-evals")
            if key not in text or self.reference_path(gate.get("definition_ref")) != "docs/dod-evals.md":
                self.issue("unresolved_gate", "dod-evals", key)
            if gate.get("applicability") == "not_applicable":
                if not gate.get("rationale"):
                    self.issue("missing_rationale", "dod-evals", key)
                if any(check.get("gate_id") == key and check.get("execution_status") != "not_applicable" for check in checks):
                    self.issue("contradictory_applicability", "dod-evals", key)
                continue
            if gate.get("applicability") != "applicable" or type(gate.get("required")) is not bool:
                self.issue("gate_applicability", "dod-evals", key)
            if gate.get("active") is False:
                self.issue("inactive_load_bearing_gate", "dod-evals", key)
            ids = gate.get("check_ids", [])
            if not ids or any(item not in check_map or check_map[item].get("gate_id") != key for item in ids):
                self.issue("unbound_gate", "dod-evals", key)
            if key == "heuristic_usability_review":
                applicable = {h for item in ids for h in check_map.get(item, {}).get("heuristic_ids", [])}
                excluded = gate.get("not_applicable_heuristics", {})
                if not isinstance(excluded, dict) or any(not reason for reason in excluded.values()):
                    self.issue("heuristic_coverage", "qa-checklist", "excluded heuristics need reasons")
                    excluded = {}
                expected = {"H" + str(i) for i in range(1, 11)}
                if applicable.intersection(excluded) or applicable.union(excluded) != expected:
                    self.issue("heuristic_coverage", "qa-checklist", "account for H1-H10 without contradictory applicability")
            if (release or release_claim) and gate.get("required"):
                for item in ids:
                    check = check_map.get(item, {})
                    if check.get("execution_status") not in ("passed", "not_applicable"):
                        self.issue("required_check_incomplete" if release else "unsupported_release_claim", "qa-checklist", str(item))
        for check in checks:
            if check.get("gate_id") not in gate_ids:
                self.issue("unknown_gate", "qa-checklist", str(check.get("check_id")))
        for key in GATE_KINDS:
            if key not in gate_ids:
                self.issue("missing_ui_gate", "dod-evals", key + ": declare applicable or source-backed not_applicable")
    def promotions(self, release=False):
        for record in self.manifest.get("prototype_promotions", []):
            if not release and not record.get("started_at"):
                continue
            mappings = record.get("path_mappings", [])
            if not mappings:
                self.issue("promotion_mapping", "implementation", "declared reuse requires path mappings")
                continue
            try:
                destinations = [self.path(item["destination"]).exists() for item in mappings]
                if release and not all(destinations):
                    self.issue("promotion_destination", "implementation", str(record.get("unit_id")))
                if not any(destinations):
                    continue
                receipt = record.get("receipt", {})
                if not self.snapshot(receipt.get("path"), receipt.get("content_hash"), "implementation", "promotion_receipt"):
                    continue
                actual = read_json(self.path(receipt["path"]))
                if not record.get("unit_id") or actual.get("unit_id") != record["unit_id"] or actual.get("baseline_id") != self.manifest.get("approved_baseline_id") or actual.get("development_plan_hash") != self.artifacts.get("development-plan", {}).get("content_hash"):
                    raise ValueError("promotion receipt does not match current unit/plan/baseline")
                observed = actual.get("path_mappings", [])
                mapping_key = lambda item: tuple(item.get(key) for key in ("source", "destination", "strategy"))
                if sorted(mapping_key(item) for item in observed) != sorted(mapping_key(item) for item in mappings):
                    raise ValueError("promotion strategy/path mismatch")
                for item in mappings:
                    self.path(item["source"])
                    if item.get("strategy") not in ("copy", "adapt", "reimplement"):
                        raise ValueError("unknown promotion strategy")
            except (OSError, ValueError, KeyError, TypeError) as error:
                self.issue("promotion_receipt", "implementation", str(error))

    def authorization(self):
        gate = self.manifest.get("implementation_gate", {})
        plan = self.artifacts.get("development-plan", {})
        if gate.get("state") != "authorized_for_phase3" or gate.get("development_plan_hash") != plan.get("content_hash") or gate.get("approved_baseline_id") != self.manifest.get("approved_baseline_id"):
            self.issue("implementation_not_authorized", "implementation", "separate prompt must match current plan and baseline")
            return
        receipt = gate.get("prompt_receipt", {})
        if not self.snapshot(receipt.get("path"), receipt.get("content_hash"), "implementation", "prompt_receipt"):
            return
        try:
            prompt = read_json(self.path(receipt["path"]))
            if prompt.get("event") != "implementation_prompt" or prompt.get("intent") != "start_production_implementation" or prompt.get("role") != "user":
                raise ValueError("explicit user implementation event required")
            for field in ("prompt_id", "development_plan_hash", "approved_baseline_id"):
                if not gate.get(field) or prompt.get(field) != gate.get(field):
                    raise ValueError("prompt receipt mismatch: " + field)
            if str(prompt.get("message", "")).strip().lower().rstrip(".! ") in ("", "continue", "продовжуй", "продовжити"):
                raise ValueError("generic continuation does not authorize implementation")
            if not (timestamp(gate.get("awaiting_at")) < timestamp(gate.get("prompt_received_at")) <= timestamp(gate.get("released_at"))):
                raise ValueError("implementation prompt must be later than the completed-plan pause")
            if timestamp(prompt.get("received_at")) != timestamp(gate.get("prompt_received_at")):
                raise ValueError("prompt timestamp mismatch")
        except (ValueError, OSError, KeyError) as error:
            self.issue("prompt_receipt", "implementation", str(error))

    def run(self, node, after=False, audit=False):
        if type(self.manifest.get("checker_contract_version")) is not int or self.manifest["checker_contract_version"] != 1:
            self.issue("migration_required", "manifest", "retain existing documents/history; add verified metadata using manifest-contract.md")
        language = self.manifest.get("language", {})
        if not language.get("working_language") or language.get("artifact_language") != language.get("working_language"):
            self.issue("language_record", "manifest", "working and artifact language must agree; UI locales are separate")
        spec = self.contract["nodes"][node] if not audit else {
            "required_before": list(self.artifacts), "outputs": [],
            "baseline_required": bool(self.manifest.get("approved_baseline_id")),
            "authorization_required": self.manifest.get("implementation_gate", {}).get("state") == "authorized_for_phase3",
        }
        for key in spec["required_before"] + (spec["outputs"] if after else []):
            if key in self.specs:
                self.artifact(key)
            else:
                self.issue("unknown_artifact", "manifest", key)
        self.bundle()
        if spec.get("baseline_required"):
            self.baseline()
            for key in ("architecture", "dod-evals", "qa-checklist", "development-plan"):
                if key in self.checked and self.artifacts.get(key, {}).get("validated_baseline_id") != self.manifest.get("approved_baseline_id"):
                    self.issue("baseline_reconciliation_required", key, "owner must revalidate against the active baseline")
        if spec.get("source_access_required"):
            if self.manifest.get("design_execution", {}).get("mode") not in ("codex", "claude_design"):
                self.issue("design_executor_required", "design", "record the explicit executor choice before generation")
            self.source_access()
        if spec.get("candidates_required") or (after and spec.get("candidates_after")):
            self.candidates()
        if spec.get("verification_required") or "qa-checklist" in self.checked:
            self.verification(release=spec.get("release_required", False), baseline_required=spec.get("baseline_required", False))
        if spec.get("authorization_required"):
            self.authorization()
            self.promotions(release=spec.get("release_required", False))
        result = "blocked" if self.issues else "passed"
        if self.issues and all(item["code"] == "migration_required" for item in self.issues):
            result = "migration_required"
        return {"result": result, "node": node, "mode": "audit" if audit else "after" if after else "before",
                "checked_artifacts": sorted(self.checked), "affected_artifacts": sorted(self.affected),
                "issues": self.issues, "warnings": sorted(set(self.warnings)),
                "limits": "Checks declared metadata, file integrity, stages and evidence references; not semantic quality, research authenticity or runner enforcement."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path.cwd())
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--before")
    group.add_argument("--after")
    group.add_argument("--audit", action="store_true")
    group.add_argument("--hash", dest="hash_path")
    parser.add_argument("--heading", help="with --hash: exact Markdown heading for a fragment")
    args = parser.parse_args()
    try:
        contract = read_contract()
        validate_contract(contract)
        if args.hash_path:
            checker = Checker(args.project, {}, contract)
            path = checker.path(args.hash_path)
            value = digest(section_bytes(path, args.heading)) if args.heading else tree_hash(checker.path(args.hash_path, no_links=True)) if path.is_dir() else digest(path.read_bytes())
            print(value)
            return 0
        node = args.before or args.after or "audit"
        if not args.audit and node not in contract["nodes"]:
            raise ValueError("unknown node; choose: " + ", ".join(contract["nodes"]))
        manifest = read_json(args.project / "forge/sdd-manifest.json")
        if not isinstance(manifest, dict):
            raise ValueError("manifest must be an object")
        report = Checker(args.project, manifest, contract).run(node, bool(args.after), args.audit)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["result"] == "passed" else 2 if report["result"] == "migration_required" else 1
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as error:
        print(json.dumps({"result": "blocked", "issues": [{"code": "invalid_input", "detail": str(error)}]}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
