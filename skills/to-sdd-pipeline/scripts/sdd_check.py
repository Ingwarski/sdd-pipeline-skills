#!/usr/bin/env python3
"""Read-only, stage-aware SDD consistency checks. Python 3.12+, standard library."""

import argparse
import copy
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
from datetime import datetime
from urllib.parse import unquote, urlsplit


CONTRACT = Path(__file__).resolve().parent.parent / "references/pipeline-contract.json"
ASVS_CATALOG = Path(__file__).resolve().parents[2] / "to-sdd-prd/references/owasp/ASVS-5.0.0.json"
ASVS_CATALOG_SHA256 = "bcdbec214d70abcfad9284a31d4f9e5134305831d628aad3aa85d7e26626cb35"
SECURITY_GATE = "product_security_requirements"
SECURITY_OWNERS = {"architecture", "dod-evals", "qa-checklist", "development-plan"}
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


class RenderReferences(HTMLParser):
    """Static render resources, not navigation links. Never execute source content."""
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "base":
            raise ValueError("freeze without a base URL override")
        for name in ("src", "poster") + (("data",) if tag == "object" else ()):
            if attrs.get(name):
                self.urls.append(attrs[name])
        if tag in ("link", "use", "image"):
            self.urls.extend(attrs[name] for name in ("href", "xlink:href") if attrs.get(name))
        if attrs.get("srcset"):
            # URL tokens can contain commas (notably inline data). Descriptors
            # follow whitespace; a trailing comma separates URL-only candidates.
            remaining = attrs["srcset"].lstrip(" ,\t\r\n")
            while remaining:
                match = re.match(r"\S+", remaining)
                url = match[0]
                self.urls.append(url.rstrip(","))
                remaining = remaining[len(url):]
                if not url.endswith(","):
                    remaining = remaining.partition(",")[2]
                remaining = remaining.lstrip(" ,\t\r\n")


def validate_render_files(root, files):
    """Reject detectable unbound resources; runtime dependency discovery remains browser work."""
    for path in files:
        if path.suffix.lower() not in (".html", ".htm", ".css", ".js", ".mjs", ".svg"):
            continue
        text = path.read_text(encoding="utf-8-sig")
        urls = []
        if path.suffix.lower() in (".html", ".htm", ".svg"):
            parser = RenderReferences()
            parser.feed(text)
            urls.extend(parser.urls)
        urls.extend(re.findall(r"url\(\s*['\"]?([^'\"\s)]+)", text, re.I))
        urls.extend(re.findall(r"@import\s+['\"]([^'\"]+)", text, re.I))
        urls.extend(re.findall(r"(?:\bfrom\s*|\bimport\s*(?:\(\s*)?|new\s+URL\(\s*)['\"]([^'\"]+)['\"]", text))
        for url in urls:
            parsed = urlsplit(url)
            if url.startswith("#") or parsed.scheme == "data":
                continue
            if parsed.scheme or parsed.netloc:
                raise ValueError("vendor mutable render dependency before freezing: " + url)
            local = unquote(parsed.path)
            target = (root / local.lstrip("/") if local.startswith("/") else path.parent / local).resolve()
            if target not in files:
                raise ValueError("unbound render dependency: " + str(path) + " -> " + url)


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


def contains_id(text, value):
    return isinstance(value, str) and bool(value) and bool(
        re.search(r"(?<![\w.-])" + re.escape(value) + r"(?![\w-]|\.[\w])", text))


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
        self.contract = copy.deepcopy(contract or read_contract())
        validate_contract(self.contract)
        scope = manifest.get("product_scope", {})
        self.ui = scope.get("capabilities", {}).get("ui") is not False
        self.skipped = set() if self.ui else set(self.contract.get("ui_only_artifacts", []))
        if self.skipped:
            for spec in list(self.contract["artifacts"].values()) + list(self.contract["nodes"].values()):
                spec["required_before"] = [key for key in spec["required_before"] if key not in self.skipped]
                if "outputs" in spec:
                    spec["outputs"] = [key for key in spec["outputs"] if key not in self.skipped]
                spec["baseline_required"] = False
        self.specs = self.contract["artifacts"]
        self.artifacts = manifest.get("artifacts", {})
        if not isinstance(self.artifacts, dict):
            raise ValueError("artifacts must be an object")
        self.issues, self.warnings = [], []
        self.checked, self.affected = set(), set()
        self.security_requirements = {}

    def issue(self, code, target, detail):
        item = {"code": code, "target": target, "detail": detail}
        if item not in self.issues:
            self.issues.append(item)
        if target in self.specs:
            self.affected.add(target)

    def product_scope(self):
        scope = self.manifest.get("product_scope")
        if scope is None:
            return  # Legacy projects retain the full UI workflow; no silent opt-out.
        try:
            profile, capabilities = scope["profile"], scope["capabilities"]
            if profile not in self.contract["profiles"] or not isinstance(capabilities, dict):
                raise ValueError("unknown product profile/capabilities")
            if "ui" not in capabilities or any(type(value) is not bool for value in capabilities.values()):
                raise ValueError("capabilities need explicit booleans including ui")
            if (profile == "headless") != (capabilities["ui"] is False):
                raise ValueError("headless profile and ui capability disagree")
            reference = scope["definition_ref"]
            text = self.reference(reference, "product-idea")
            if self.reference_path(reference) != "docs/product-idea.md":
                raise ValueError("product scope belongs to product idea")
            blocks = re.findall(r"```json\s*\n(.*?)\n```", text, re.S)
            expected = {"profile": profile, "capabilities": capabilities}
            if len(blocks) != 1 or json.loads(blocks[0], object_pairs_hook=unique_object) != expected:
                raise ValueError("scope projection differs from the canonical scope JSON")
        except (KeyError, TypeError, ValueError) as error:
            self.issue("product_scope", "product-idea", str(error))

    def path(self, relative, no_links=False):
        if not isinstance(relative, str) or not relative or "\\" in relative:
            raise ValueError("use a nonempty repository-relative POSIX path")
        parsed = PurePosixPath(relative)
        if not parsed.parts or parsed.is_absolute() or ".." in parsed.parts or ":" in parsed.parts[0]:
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
        dispatch = self.manifest.get("dispatches", {}).get(key)
        if dispatch is not None:
            if dispatch.get("invocation_id") != entry.get("owner_invocation_id") or set(dispatch.get("outputs", [])) != set(entry.get("declared_output_set", [])):
                self.issue("stale_owner_return", key, "return does not match the current dispatch identity/output set")
            self.sources(dispatch, key)
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

        if key == "prd":
            self.security_review(entry)
        elif key in SECURITY_OWNERS:
            self.security_coverage(entry, key)

    def security_reference(self, reference, owner, identifier=None):
        text = self.reference(reference, owner)
        if self.reference_path(reference) != self.specs[owner]["path"] or (identifier and not contains_id(text, identifier)):
            self.issue("security_reference", owner, "security reference must resolve its ID in the owner's document")
        return text

    def security_review(self, entry):
        review = entry.get("security_review")
        if not isinstance(review, dict):
            self.issue("security_review_missing", "prd", "PRD owner must assess OWASP requirements; do not invent a historical review")
            return
        if type(review.get("version")) is not int or review["version"] != 1 or review.get("asvs_version") != "5.0.0":
            self.issue("security_profile", "prd", "expected security record version 1 and ASVS 5.0.0")
        scope, level = review.get("scope"), review.get("level")
        if (scope == "web-api" and (type(level) is not int or level not in (1, 2, 3))) or (scope == "adapted" and level is not None) or scope not in ("web-api", "adapted"):
            self.issue("security_profile", "prd", "web-api needs level 1-3; adapted scope must not claim an ASVS level")
        text = self.security_reference(review.get("definition_ref"), "prd")
        rationale = review.get("rationale")
        if not isinstance(rationale, str) or not rationale.strip() or rationale not in text or "5.0.0" not in text:
            self.issue("security_profile", "prd", "canonical security section needs the recorded rationale and standard version")
        if review.get("status") != "complete":
            self.issue("security_review_incomplete", "prd", "resolve material security specification gaps before advancement")
        try:
            if digest(ASVS_CATALOG.read_bytes()) != ASVS_CATALOG_SHA256:
                raise ValueError("ASVS catalog does not match the reviewed pin; repair the skill resources")
            catalog = read_json(ASVS_CATALOG)
            if catalog.get("Version") != "5.0.0":
                raise ValueError("expected bundled ASVS 5.0.0")
            known = {"v5.0.0-" + item["Shortcode"][1:]
                     for chapter in catalog["Requirements"] for section in chapter["Items"] for item in section["Items"]}
        except (ValueError, OSError, KeyError, TypeError) as error:
            self.issue("security_catalog", "prd", str(error))
            return
        requirements = review.get("requirements")
        if not isinstance(requirements, list) or not requirements:
            self.issue("security_requirements", "prd", "explicit protective requirements are required")
            return
        for requirement in requirements:
            if not isinstance(requirement, dict):
                self.issue("security_requirements", "prd", "security requirement record must be an object")
                continue
            key = requirement.get("requirement_id")
            if not isinstance(key, str) or not re.fullmatch(r"(?:FR|NFR)-[A-Za-z0-9][A-Za-z0-9_.-]*", key) or key in self.security_requirements:
                self.issue("security_requirements", "prd", "unique existing FR/NFR obligation IDs required")
                continue
            self.security_requirements[key] = requirement
            text = self.security_reference(requirement.get("definition_ref"), "prd", key)
            ids = requirement.get("asvs_ids")
            if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
                self.issue("security_asvs_id", "prd", key + ": ASVS IDs must be a list of strings")
                continue
            if len(set(ids)) != len(ids) or any(item not in known or not contains_id(text, item) for item in ids):
                self.issue("security_asvs_id", "prd", key + ": cite unique, real versioned controls in the canonical requirement")
            if not ids:
                rationale = requirement.get("rationale")
                if not isinstance(rationale, str) or not rationale.strip() or rationale not in text:
                    self.issue("security_supplement", "prd", key + ": supplemental controls need a canonical rationale")

    def security_coverage(self, entry, owner):
        if not self.security_requirements:
            return
        coverage = entry.get("security_coverage")
        if not isinstance(coverage, dict) or set(coverage) != set(self.security_requirements):
            self.issue("security_coverage", owner, "map every current PRD security obligation to this owner's local consequence")
            return
        for key, reference in coverage.items():
            self.security_reference(reference, owner, key)

    def security_verification(self, checks, gates):
        if not self.security_requirements:
            return
        expected = set(self.security_requirements)
        matches = [gate for gate in gates if gate.get("gate_id") == SECURITY_GATE]
        if len(matches) != 1:
            self.issue("security_gate", "dod-evals", "one required product_security_requirements gate must cover the PRD security obligations")
            return
        gate = matches[0]
        ids = gate.get("security_requirement_ids")
        if gate.get("active") is not True or gate.get("required") is not True or gate.get("applicability") != "applicable":
            self.issue("security_gate", "dod-evals", "applicable security obligations cannot be inactive, advisory or excluded")
        if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids) or len(set(ids)) != len(ids) or set(ids) != expected:
            self.issue("security_gate_coverage", "dod-evals", "security gate must cover every current PRD security obligation")
        text = self.reference(gate.get("definition_ref"), "dod-evals")
        if any(not contains_id(text, key) for key in expected):
            self.issue("security_gate_coverage", "dod-evals", "canonical security gate must cite its requirement IDs")
        covered = set()
        for check in checks:
            if check.get("gate_id") != SECURITY_GATE:
                continue
            ids = check.get("security_requirement_ids")
            if not isinstance(ids, list) or not ids or not all(isinstance(item, str) for item in ids):
                self.issue("security_check_coverage", "qa-checklist", "each security check needs PRD security obligation IDs")
                continue
            if len(set(ids)) != len(ids) or set(ids) - expected:
                self.issue("security_check_coverage", "qa-checklist", "unknown or duplicate security obligation IDs")
            if check.get("check_id") not in gate.get("check_ids", []):
                self.issue("security_check_coverage", "qa-checklist", "security check must be bound to the required gate")
                continue
            text = self.reference(check.get("definition_ref"), "qa-checklist")
            if any(not contains_id(text, key) for key in ids):
                self.issue("security_check_coverage", "qa-checklist", "canonical checks must cite their security obligation IDs")
            if check.get("phase") not in ("implementation", "both") or check.get("execution_status") == "not_applicable":
                self.issue("security_check_scope", "qa-checklist", "applicable product security needs implementation-level checks")
            covered.update(ids)
        if covered != expected:
            self.issue("security_check_coverage", "qa-checklist", "concrete checks must cover every PRD security obligation")

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

    def traceability(self):
        owners = {"job": "product-idea", "use_case": "prd", "requirement": "prd", "surface": "screen-map",
                  "state": "screen-map", "unit": "development-plan", "check": "qa-checklist"}
        active = set(owners.values()) & self.checked
        if not active:
            return
        if type(self.manifest.get("traceability_version")) is not int or self.manifest["traceability_version"] != 1:
            self.issue("migration_required", "manifest", "owners must return verified traceability version 1; preserve IDs and history")
            return
        definitions, links = {}, []
        for owner in sorted(active):
            trace = self.artifacts.get(owner, {}).get("traceability")
            if not isinstance(trace, dict) or not isinstance(trace.get("definitions"), list) or not isinstance(trace.get("links"), list):
                self.issue("trace_definition", owner, "owner needs definitions and links")
                continue
            for item in trace["definitions"]:
                key, kind = item.get("id"), item.get("kind")
                if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*", key) or key in definitions or owners.get(kind) != owner:
                    self.issue("trace_definition", owner, "unique ID with its canonical kind/owner required")
                    continue
                definitions[key] = item
                text = self.reference(item.get("definition_ref"), owner)
                if self.reference_path(item.get("definition_ref")) != self.specs[owner]["path"] or not contains_id(text, key):
                    self.issue("trace_definition", owner, key + ": missing canonical definition")
                if type(item.get("required")) is not bool or (not item.get("required") and not item.get("rationale")):
                    self.issue("trace_definition", owner, key + ": required flag or exclusion rationale missing")
            links.extend((owner, link) for link in trace["links"])
            # Declared primary IDs in canonical source cannot silently fall out of its index.
            prefix = r"JOB" if owner == "product-idea" else r"UC|FR|NFR" if owner == "prd" else None
            if prefix:
                text = self.path(self.specs[owner]["path"]).read_text(encoding="utf-8")
                mentioned = {value.rstrip(".") for value in re.findall(r"(?<![\w.-])(?:" + prefix + r")-[A-Za-z0-9][A-Za-z0-9_.-]*", text)}
                for key in mentioned - set(definitions):
                    self.issue("trace_definition", owner, key + ": canonical ID is not indexed")
        kinds = {key: value["kind"] for key, value in definitions.items()}
        allowed = {"realizes_job": ({"use_case"}, {"job"}), "specifies": ({"requirement"}, {"use_case"}),
                   "supports": ({"surface"}, {"use_case"}), "state_of": ({"state"}, {"surface"}),
                   "implements": ({"unit"}, {"requirement", "state"}), "verifies": ({"check"}, {"requirement", "state"})}
        checks = {check.get("check_id"): check for check in self.manifest.get("verification", {}).get("checks", [])}
        valid = set()
        for owner, link in links:
            source, target, relation = link.get("from"), link.get("to"), link.get("relation")
            types = allowed.get(relation)
            text = self.reference(link.get("definition_ref"), owner)
            if not types or kinds.get(source) not in types[0] or kinds.get(target) not in types[1] or owners.get(kinds.get(source)) != owner:
                self.issue("trace_link", owner, str(source) + " -> " + str(target) + ": unresolved or wrongly typed link")
            elif self.reference_path(link.get("definition_ref")) != self.specs[owner]["path"] or not all(contains_id(text, key) for key in (source, target)):
                self.issue("trace_link", owner, "relationship must be cited in its owner's document")
            elif relation != "verifies" or (source in checks and checks[source].get("execution_status") != "not_applicable"):
                valid.add((source, target, relation))
        for key, item in definitions.items():
            if not item.get("required"):
                continue
            kind = item["kind"]
            incoming = {relation for _, target, relation in valid if target == key}
            outgoing = {relation for source, _, relation in valid if source == key}
            expected = set()
            if kind == "job" and "prd" in active:
                expected.add("realizes_job")
            if kind == "use_case":
                expected.add("specifies")
                if "realizes_job" not in outgoing:
                    self.issue("trace_coverage", "prd", key + ": use case must realize a job")
            if kind == "requirement" and not item.get("cross_cutting") and "specifies" not in outgoing:
                self.issue("trace_coverage", "prd", key + ": map a use case or explicitly declare cross-cutting scope")
            if kind == "surface" and "supports" not in outgoing or kind == "state" and "state_of" not in outgoing:
                self.issue("trace_coverage", "screen-map", key + ": missing structural relationship")
            if kind in ("requirement", "state"):
                if "qa-checklist" in active:
                    expected.add("verifies")
                if "development-plan" in active:
                    expected.add("implements")
            for relation in expected - incoming:
                owner = "qa-checklist" if relation == "verifies" else "development-plan" if relation == "implements" else "prd"
                self.issue("trace_coverage", owner, key + ": missing " + relation)
        if "qa-checklist" in active:
            declared = {key for key, kind in kinds.items() if kind == "check"}
            for key in declared.symmetric_difference(checks):
                self.issue("trace_link", "qa-checklist", str(key) + ": trace and verification indexes must agree")
            for check in checks.values():
                for field, kind in (("job_ids", "job"), ("use_case_ids", "use_case")):
                    ids = check.get(field, [])
                    if not isinstance(ids, list) or any(not isinstance(key, str) or kinds.get(key) != kind for key in ids):
                        self.issue("trace_link", "qa-checklist", str(check.get("check_id")) + ": unresolved " + field)

    def render_hash(self, record):
        root_name = record.get("prototype_source_root")
        root = self.path(root_name, no_links=True)
        if not root.is_dir():
            raise ValueError("prototype source root must be a directory")
        algorithm = record.get("hash_algorithm")
        dependencies = record.get("render_dependencies", [])
        if not isinstance(dependencies, list) or not all(isinstance(p, str) for p in dependencies):
            raise ValueError("render dependencies must be project-relative paths")
        if algorithm not in ("sdd-tree-sha256-v1", "sdd-render-sha256-v2") or (algorithm == "sdd-tree-sha256-v1" and dependencies):
            raise ValueError("shared assets require sdd-render-sha256-v2")
        names = [root_name] + dependencies
        paths = [self.path(name, no_links=True) for name in names]
        if any(a == b or a in b.parents or b in a.parents for i, a in enumerate(paths) for b in paths[i + 1:]):
            raise ValueError("duplicate or overlapping render roots")
        entries, files = [], set()
        for name, path in zip(names, paths):
            if not path.is_dir() and not path.is_file():
                raise ValueError("render input must be a regular file or directory")
            value = tree_hash(path) if path.is_dir() else digest(path.read_bytes())
            entries.append((name, value))
            files.update(p.resolve() for p in path.rglob("*") if p.is_file()) if path.is_dir() else files.add(path)
        validate_render_files(root, files)
        if algorithm == "sdd-tree-sha256-v1":
            return entries[0][1]
        entries.sort(key=lambda item: item[0].encode("utf-8"))
        return digest(json.dumps(entries, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))

    def frozen(self, record, target):
        try:
            observed = self.render_hash(record)
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
                    surface = self.manifest.get("design_execution", {}).get("review_surface", "external_default")
                    if field == "browser_receipt" and (surface not in ("external_default", "external_named", "in_app") or actual.get("browser_kind") != surface):
                        raise ValueError("browser receipt must match the selected visible review surface")
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
                expected_kind = "security" if check.get("gate_id") == SECURITY_GATE else GATE_KINDS.get(check.get("gate_id"))
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
            if not self.ui and key in GATE_KINDS and gate.get("applicability") != "not_applicable":
                self.issue("contradictory_applicability", "dod-evals", "UI gate in headless scope: " + key)
            text = self.reference(gate.get("definition_ref"), "dod-evals")
            if key not in text or self.reference_path(gate.get("definition_ref")) != "docs/dod-evals.md":
                self.issue("unresolved_gate", "dod-evals", key)
            ids = gate.get("check_ids", [])
            if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
                self.issue("unbound_gate", "dod-evals", key)
                ids = []
            if len(ids) != len(set(ids)) or any(item not in check_map or check_map[item].get("gate_id") != key for item in ids):
                self.issue("unbound_gate", "dod-evals", key)
            for check in checks:
                if check.get("gate_id") == key and check.get("check_id") not in ids:
                    self.issue("unbound_check", "qa-checklist", str(check.get("check_id")))
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
            if not ids:
                self.issue("unbound_gate", "dod-evals", key)
            applicable_checks = [check_map[item] for item in ids if item in check_map
                                 and check_map[item].get("execution_status") != "not_applicable"]
            if not applicable_checks:
                self.issue("empty_applicable_gate", "dod-evals", key + ": resolve applicability; excluded checks cannot satisfy it")
            if key == "heuristic_usability_review":
                applicable = {h for check in applicable_checks for h in check.get("heuristic_ids", [])}
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
        self.security_verification(checks, gates)

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
                self.promotion_provenance(record, actual, release)
            except (OSError, ValueError, KeyError, TypeError) as error:
                self.issue("promotion_receipt", "implementation", str(error))

    def promotion_provenance(self, record, actual, release):
        units = self.artifacts.get("development-plan", {}).get("traceability", {}).get("definitions", [])
        if not any(item.get("id") == record.get("unit_id") and item.get("kind") == "unit" for item in units):
            raise ValueError("promotion unit is not defined in the current plan")
        if type(actual.get("schema_version")) is not int or actual["schema_version"] != 1:
            raise ValueError("promotion schema_version 1 required")
        for key in ("promotion_id", "run_id", "candidate_id", "version"):
            if not isinstance(actual.get(key), str) or not actual[key].strip():
                raise ValueError("missing promotion field: " + key)
        baseline = self.manifest.get("active_baseline", {})
        for key in ("visual_target_hash", "candidate_id", "version", "prototype_source_root", "prototype_tree_hash"):
            if not baseline.get(key) or actual.get(key) != baseline[key]:
                raise ValueError("promotion baseline mismatch: " + key)
        if actual.get("development_plan_ref") != self.specs["development-plan"]["path"]:
            raise ValueError("promotion needs canonical plan reference")
        if timestamp(actual.get("completed_at")) < timestamp(record.get("started_at")):
            raise ValueError("promotion completion precedes execution")
        for key in ("adaptations", "variances"):
            if not isinstance(actual.get(key), list):
                raise ValueError("promotion needs explicit " + key)
        if actual.get("verification_status") not in ("passed", "failed", "blocked") or (release and actual["verification_status"] != "passed"):
            raise ValueError("promotion verification is not complete")
        qa = {item["check_id"]: item for item in self.manifest.get("verification", {}).get("checks", [])}
        ids = actual.get("qa_ids")
        if not isinstance(ids, list) or not ids or any(key not in qa for key in ids):
            raise ValueError("promotion needs real QA IDs")
        if release and any(qa[key].get("execution_status") != "passed" for key in ids):
            raise ValueError("promotion QA has not passed")
        evidence = actual.get("visual_evidence")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError("promotion needs actual visual evidence")
        for item in evidence:
            if item.get("kind") != "visual" or not hash_matches(item.get("content_hash"), digest(self.path(item.get("path")).read_bytes())):
                raise ValueError("invalid promotion visual evidence")
        base, head = actual.get("base_commit"), actual.get("head_commit")
        if any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value) for value in (base, head)) or base != record.get("base_commit"):
            raise ValueError("promotion needs planned base and actual full commit IDs")
        def git(*args):
            try:
                return subprocess.run(["git", "--literal-pathspecs", *args], cwd=self.project,
                                      capture_output=True, check=True, timeout=30).stdout
            except (subprocess.SubprocessError, OSError) as error:
                raise ValueError("promotion Git provenance unavailable: " + str(error)) from error
        git("merge-base", "--is-ancestor", base, head)
        git("merge-base", "--is-ancestor", head, "HEAD")
        destinations = []
        source_roots = [self.path(baseline["prototype_source_root"])] + [self.path(p) for p in baseline.get("render_dependencies", [])]
        for item in actual["path_mappings"]:
            source = self.path(item["source"], no_links=True)
            destination = self.path(item["destination"], no_links=True)
            if not any(source == root or root in source.parents for root in source_roots):
                raise ValueError("promotion source is not in the frozen render bundle")
            if not source.is_file() or not destination.is_file():
                raise ValueError("promotion mappings must enumerate regular files")
            if not hash_matches(item.get("source_hash"), digest(source.read_bytes())) or not hash_matches(item.get("destination_hash"), digest(destination.read_bytes())):
                raise ValueError("promotion source/destination bytes changed")
            if digest(git("show", head + ":" + item["destination"])) != digest(destination.read_bytes()):
                raise ValueError("destination differs from promoted commit")
            if item["strategy"] == "copy" and source.read_bytes() != destination.read_bytes():
                raise ValueError("copy strategy changed source bytes")
            destinations.append(item["destination"])
        if len(destinations) != len(set(destinations)):
            raise ValueError("duplicate promotion destination")
        paths = sorted(destinations)
        changed = git("diff", "--name-only", "-z", "--no-renames", base, head, "--", *paths).decode().strip("\0").split("\0")
        if sorted(actual.get("changed_paths", [])) != sorted(p for p in changed if p):
            raise ValueError("promotion changed paths mismatch")
        patch = git("diff", "--binary", "--no-ext-diff", "--no-textconv", base, head, "--", *paths)
        if not hash_matches(actual.get("patch_hash"), digest(patch)):
            raise ValueError("promotion patch hash mismatch")

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
            scope = self.manifest.get("product_scope")
            if scope is not None:
                scope_hash = digest(json.dumps({key: scope[key] for key in ("profile", "capabilities")}, sort_keys=True, separators=(",", ":")).encode())
                if not hash_matches(gate.get("product_scope_hash"), scope_hash) or prompt.get("product_scope_hash") != gate.get("product_scope_hash"):
                    raise ValueError("implementation prompt must bind the current product_scope_hash")
            for field in ("prompt_id", "development_plan_hash", "approved_baseline_id"):
                missing = field not in gate or (not gate.get(field) and (field != "approved_baseline_id" or self.ui))
                if missing or field not in prompt or prompt.get(field) != gate.get(field):
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
        self.product_scope()
        if type(self.manifest.get("checker_contract_version")) is not int or self.manifest["checker_contract_version"] != 1:
            self.issue("migration_required", "manifest", "retain existing documents/history; add verified metadata using manifest-contract.md")
        language = self.manifest.get("language", {})
        if not language.get("working_language") or language.get("artifact_language") != language.get("working_language"):
            self.issue("language_record", "manifest", "working and artifact language must agree; UI locales are separate")
        spec = self.contract["nodes"][node] if not audit else {
            "required_before": [key for key in self.artifacts if key not in self.skipped], "outputs": [],
            "baseline_required": self.ui and bool(self.manifest.get("approved_baseline_id")),
            "authorization_required": self.manifest.get("implementation_gate", {}).get("state") == "authorized_for_phase3",
        }
        if not self.ui and (node in self.skipped or node in ("prototype-candidates", "design-approval", "architecture-approved", "dod-evals-approved", "qa-checklist-approved")):
            self.issue("inapplicable_node", "manifest", "headless scope skips UI nodes and uses ordinary owner nodes")
        for key in spec["required_before"] + (spec["outputs"] if after else []):
            if key in self.specs:
                self.artifact(key)
            else:
                self.issue("unknown_artifact", "manifest", key)
        self.bundle()
        self.traceability()
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
                "skipped_artifacts": sorted(self.skipped),
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
    group.add_argument("--hash-render", metavar="RECORD", help="hash a candidate/baseline JSON record and its declared render resources")
    group.add_argument("--snapshot", metavar="NODE", help="emit unvalidated owner/source metadata without writing files or claiming review")
    parser.add_argument("--heading", help="with --hash: exact Markdown heading for a fragment")
    args = parser.parse_args()
    if sys.version_info < (3, 12):
        parser.error("Python 3.12+ is required")
    try:
        contract = read_contract()
        validate_contract(contract)
        if args.hash_render:
            checker = Checker(args.project, {}, contract)
            print(checker.render_hash(read_json(checker.path(args.hash_render))))
            return 0
        if args.hash_path:
            checker = Checker(args.project, {}, contract)
            path = checker.path(args.hash_path)
            value = digest(section_bytes(path, args.heading)) if args.heading else tree_hash(checker.path(args.hash_path, no_links=True)) if path.is_dir() else digest(path.read_bytes())
            print(value)
            return 0
        node = args.before or args.after or args.snapshot or "audit"
        if not args.audit and node not in contract["nodes"]:
            raise ValueError("unknown node; choose: " + ", ".join(contract["nodes"]))
        manifest = read_json(args.project / "forge/sdd-manifest.json")
        if not isinstance(manifest, dict):
            raise ValueError("manifest must be an object")
        if args.snapshot:
            checker = Checker(args.project, manifest, contract)
            checker.product_scope()
            if checker.issues:
                raise ValueError("resolve product scope before snapshotting")
            node_spec = checker.contract["nodes"][node]
            print(json.dumps({"node": node, "status": "unvalidated", "outputs": node_spec["outputs"],
                              "source_hashes": {checker.specs[key]["path"]: digest(checker.path(checker.specs[key]["path"]).read_bytes())
                                                for key in node_spec["required_before"] if key not in checker.contract["context_bundle"]},
                              "limits": "Hash proposal only. Owner must select consumed fragments, validate meaning and return its actual invocation/result."}, ensure_ascii=False, indent=2))
            return 0
        report = Checker(args.project, manifest, contract).run(node, bool(args.after), args.audit)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["result"] == "passed" else 2 if report["result"] == "migration_required" else 1
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as error:
        print(json.dumps({"result": "blocked", "issues": [{"code": "invalid_input", "detail": str(error)}]}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
