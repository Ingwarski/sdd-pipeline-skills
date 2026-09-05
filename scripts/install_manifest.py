#!/usr/bin/env python3
"""Validate installation inputs once for both platforms; print name|path|legacy rows."""

import argparse
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit


NAMES = {
    "to-product-idea", "to-sdd-prd", "to-project-context", "to-guardrails",
    "to-user-journey", "to-screen-map", "to-wireframes", "to-design-brief",
    "to-architecture", "to-dod-evals", "to-qa-checklist", "to-development-plan",
    "to-sdd-pipeline",
}


def validate_references(root, source, seen):
    """Follow local Markdown reference chains, once per file, within the collection."""
    source = source.resolve()
    if source in seen:
        return
    seen.add(source)
    text = source.read_text(encoding="utf-8-sig")
    text = re.sub(r"(?ms)^```[^\n]*\n.*?^```\s*$", "", text)
    for link in re.findall(r"\[[^\]\n]+\]\(([^)\n]+)\)", text):
        link = link.strip("<>")
        if urlsplit(link).scheme or link.startswith("#"):
            continue
        target = (source.parent / unquote(link.split("#", 1)[0])).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            raise ValueError("missing/out-of-clone resource: " + str(source) + " -> " + link)
        if target.suffix == ".md":
            validate_references(root, target, seen)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key: " + key)
        result[key] = value
    return result


def validate_manifest(root, metadata_only=False):
    root = Path(root).resolve()
    manifest = json.loads((root / "skills-manifest.json").read_text(encoding="utf-8-sig"),
                          object_pairs_hook=unique_object,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError("invalid JSON: " + value)))
    if not isinstance(manifest, dict) or type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1:
        raise ValueError("unsupported manifest schema; expected integer 1")
    if manifest.get("skill_set") != "sdd-pipeline" or type(manifest.get("skill_count")) is not int or manifest["skill_count"] != 13:
        raise ValueError("manifest must identify the 13-skill sdd-pipeline collection")
    skills = manifest.get("skills")
    if not isinstance(skills, list) or len(skills) != 13:
        raise ValueError("manifest count mismatch: expected 13 skill records")
    seen, rows, resources = set(), [], set()
    for skill in skills:
        if not isinstance(skill, dict):
            raise ValueError("skill record must be an object")
        name, path, legacy = skill.get("name"), skill.get("path"), skill.get("legacy_name")
        if not isinstance(name, str) or name not in NAMES or name in seen:
            raise ValueError("unknown or duplicate SDD skill name: " + str(name))
        seen.add(name)
        if path != "skills/" + name:
            raise ValueError("invalid source path for " + name)
        if legacy != ("to-prd" if name == "to-sdd-prd" else None):
            raise ValueError("invalid legacy mapping for " + name)
        rows.append((name, path, legacy or ""))
        if metadata_only:
            continue
        directory = (root / path).resolve()
        if not directory.is_relative_to(root):
            raise ValueError("skill source escapes clone: " + name)
        source = directory / "SKILL.md"
        text = source.read_text(encoding="utf-8-sig")
        frontmatter = re.match(r"\A---\n(.*?)\n---(?:\n|$)", text, re.S)
        if not frontmatter:
            raise ValueError("missing closed YAML frontmatter: " + name)
        values = dict(re.findall(r"^(name|description):\s*(.+)$", frontmatter[1], re.M))
        if values.get("name", "").strip("\"'") != name or not values.get("description", "").strip(" \"'"):
            raise ValueError("invalid frontmatter name/description: " + name)
        validate_references(root, source, resources)
    if not metadata_only:
        for relative in ("scripts/retired-skills.sh", "scripts/retired-skills.ps1",
                         "retired-skills.txt", "skills/to-sdd-pipeline/scripts/sdd_check.py",
                         "skills/to-sdd-pipeline/references/pipeline-contract.json",
                         "skills/to-sdd-pipeline/references/security-contract.md",
                         "skills/to-sdd-prd/references/security-authoring.md",
                         "skills/to-sdd-prd/scripts/asvs.py",
                         "skills/to-sdd-prd/references/owasp/ASVS-5.0.0.json",
                         "skills/to-sdd-prd/references/owasp/NOTICE.md",
                         "skills/to-sdd-prd/references/owasp/LICENSE-ASVS.txt"):
            with (root / relative).open("rb") as stream:
                stream.read(1)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--metadata-only", action="store_true")
    args = parser.parse_args()
    if sys.version_info < (3, 12):
        parser.error("Python 3.12+ is required; no installation changes made")
    try:
        rows = validate_manifest(args.root, args.metadata_only)
        print("\n".join("|".join(row) for row in rows))
        return 0
    except (OSError, ValueError, TypeError) as error:
        print("Installation preflight failed: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
