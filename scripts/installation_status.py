#!/usr/bin/env python3
"""Read-only installed-target/resource check. Caller resolves its actual managed roots."""
import argparse
import json
import os
from pathlib import Path
import sys

from install_manifest import validate_manifest


def inspect(root, skill_roots, cleanup_roots=()):
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
    return {"result": "cleanup_required" if retired else "repair_required" if invalid else "current",
            "invalid_targets": invalid, "retired_paths": retired, "checked_roots": list(map(str, skill_roots)),
            "limits": "Local source/links only; caller must separately verify the selected remote revision and Python support."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--skill-root", type=Path, action="append", required=True)
    parser.add_argument("--cleanup-root", type=Path, action="append", default=[])
    args = parser.parse_args()
    try:
        report = inspect(args.root, args.skill_root, args.cleanup_root)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["result"] == "current" else 1
    except (OSError, ValueError, TypeError) as error:
        print(json.dumps({"result": "blocked", "error": str(error)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
