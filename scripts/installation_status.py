#!/usr/bin/env python3
"""Read-only installed-target/resource check. Caller resolves its actual managed roots."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True
from install_manifest import validate_manifest
from install_location import registration_roots
from evidence_setup import inspect as inspect_evidence


def inspect(root, skill_roots, cleanup_roots=(), project=None, evidence_home=None, agents=None):
    root = Path(root).resolve()
    rows = validate_manifest(root)
    invalid, retired, registrations = [], [], []
    for folder in skill_roots:
        targets = {}
        for name, relative, _ in rows:
            installed, source = Path(folder) / name, root / relative
            actual = installed.resolve() if installed.is_dir() else None
            targets[name] = str(actual) if actual is not None else None
            if actual != source.resolve():
                invalid.append(str(installed))
        registrations.append({"agent": (agents or {}).get(folder), "directory": str(Path(folder).resolve()),
                              "targets": targets})
    names = (root / "retired-skills.txt").read_text().splitlines()
    for folder in set(map(str, [*skill_roots, *cleanup_roots, root / "skills"])):
        for name in names:
            path = Path(folder) / name
            if os.path.lexists(path):
                retired.append(str(path))
    links_result = "cleanup_required" if retired else "repair_required" if invalid else "current"
    evidence = inspect_evidence(project, evidence_home)
    revision = subprocess.run(["git", "-C", str(root), "rev-parse", "--verify", "HEAD"],
                              capture_output=True, text=True, check=False)
    return {"scope": "local_installation", "release_provenance": "not_checked",
            "checkout": str(root), "revision": revision.stdout.strip() if revision.returncode == 0 else None,
            "registrations": registrations,
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
    agent = "both" if args.all or args.codex == args.claude else "codex" if args.codex else "claude"
    roots = registration_roots(agent, args.codex_dir, args.claude_dir)
    cleanup = [*args.cleanup_dir, *(path / "skills" for path in args.retired_source)]
    return roots, cleanup, args.evidence_project


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--skill-root", type=Path, action="append", default=[])
    parser.add_argument("--codex-dir", type=Path)
    parser.add_argument("--claude-dir", type=Path)
    parser.add_argument("--cleanup-root", type=Path, action="append", default=[])
    parser.add_argument("--project", type=Path)
    parser.add_argument("--evidence-home", type=Path)
    parser.add_argument("--installer-args", nargs=argparse.REMAINDER)
    parser.add_argument("--exit-on-links", action="store_true", help="updater internal mode; storage status still appears in output")
    args = parser.parse_args()
    try:
        roots, cleanup, project = args.skill_root, args.cleanup_root, args.project
        selected = {agent: directory for agent, directory in (("codex", args.codex_dir), ("claude", args.claude_dir))
                    if directory is not None}
        if args.installer_args is not None:
            selected, cleanup, project = installer_roots(args.installer_args)
        roots = [*roots, *selected.values()]
        if not roots:
            raise ValueError("provide --skill-root or --installer-args")
        report = inspect(args.root, roots, cleanup, project, args.evidence_home,
                         {directory: agent for agent, directory in selected.items()})
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["links_result" if args.exit_on_links else "result"] == "current" else 1
    except (OSError, ValueError, TypeError) as error:
        print(json.dumps({"result": "blocked", "error": str(error)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
