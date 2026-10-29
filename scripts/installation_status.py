#!/usr/bin/env python3
"""Read-only installed-target/resource check. Caller resolves its actual managed roots."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
from install_manifest import validate_manifest
from evidence_setup import inspect as inspect_evidence


def inspect(root, skill_roots, cleanup_roots=(), project=None, evidence_home=None):
    root = Path(root).resolve()
    rows = validate_manifest(root)
    invalid, retired = [], []
    for folder in skill_roots:
        for name, relative, _ in rows:
            installed, source = Path(folder) / name, root / relative
            if not installed.is_dir() or installed.resolve() != source.resolve():
                invalid.append(str(installed))
    names = (root / "retired-skills.txt").read_text().splitlines()
    for folder in set(map(str, [*skill_roots, *cleanup_roots, root / "skills"])):
        for name in names:
            path = Path(folder) / name
            if os.path.lexists(path):
                retired.append(str(path))
    links_result = "cleanup_required" if retired else "repair_required" if invalid else "current"
    evidence = inspect_evidence(project, evidence_home)
    return {"scope": "local_installation", "release_provenance": "not_checked",
            "result": links_result if links_result != "current" else "setup_required" if evidence["result"] != "configured" else "current",
            "links_result": links_result, "evidence_storage": evidence,
            "invalid_targets": invalid, "retired_paths": retired, "checked_roots": list(map(str, skill_roots)),
            "limits": "Local source/links and storage configuration only; current does not establish published release or tested candidate provenance. Verify the selected revision, clean source, required CI and Python support separately."}


def installer_roots(arguments):
    """Resolve the installer's declared roots for a read-only update no-op check."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--codex", action="store_true")
    parser.add_argument("--claude", action="store_true")
    parser.add_argument("--codex-dir", type=Path)
    parser.add_argument("--claude-dir", type=Path)
    parser.add_argument("--cleanup-dir", type=Path, action="append", default=[])
    parser.add_argument("--retired-source", type=Path, action="append", default=[])
    parser.add_argument("--evidence-project", type=Path)
    parser.add_argument("--evidence-non-interactive", action="store_true")
    parser.add_argument("--evidence-reconfigure", action="store_true")
    parser.add_argument("--repair", action="store_true")
    args = parser.parse_args(arguments)
    both = args.all or not (args.codex or args.claude)
    roots = []
    if both or args.codex:
        destination = args.codex_dir or os.environ.get("CODEX_SKILLS_DIR")
        if not destination:
            if os.environ.get("CODEX_HOME"):
                destination = Path(os.environ["CODEX_HOME"]) / "skills"
            else:
                legacy, official = Path.home() / ".codex/skills", Path.home() / ".agents/skills"
                destination = legacy if legacy.is_dir() and not official.is_dir() else official
        roots.append(Path(destination))
    if both or args.claude:
        roots.append(args.claude_dir or Path(os.environ.get("CLAUDE_SKILLS_DIR") or Path.home() / ".claude/skills"))
    cleanup = [*args.cleanup_dir, *(path / "skills" for path in args.retired_source)]
    return roots, cleanup, args.evidence_project


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--skill-root", type=Path, action="append", default=[])
    parser.add_argument("--cleanup-root", type=Path, action="append", default=[])
    parser.add_argument("--project", type=Path)
    parser.add_argument("--evidence-home", type=Path)
    parser.add_argument("--installer-args", nargs=argparse.REMAINDER)
    parser.add_argument("--exit-on-links", action="store_true", help="updater internal mode; storage status still appears in output")
    args = parser.parse_args()
    try:
        roots, cleanup, project = args.skill_root, args.cleanup_root, args.project
        if args.installer_args is not None:
            roots, cleanup, project = installer_roots(args.installer_args)
        if not roots:
            raise ValueError("provide --skill-root or --installer-args")
        report = inspect(args.root, roots, cleanup, project, args.evidence_home)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["links_result" if args.exit_on_links else "result"] == "current" else 1
    except (OSError, ValueError, TypeError) as error:
        print(json.dumps({"result": "blocked", "error": str(error)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
