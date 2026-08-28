#!/usr/bin/env python3
"""Read the pinned OWASP ASVS catalog offline. No scans, downloads or writes."""

import argparse
import hashlib
import json
from pathlib import Path
import sys


CATALOG = Path(__file__).resolve().parent.parent / "references/owasp/ASVS-5.0.0.json"
CATALOG_SHA256 = "bcdbec214d70abcfad9284a31d4f9e5134305831d628aad3aa85d7e26626cb35"
VERSION = "5.0.0"


def load_catalog(path=CATALOG):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != CATALOG_SHA256:
        raise ValueError("ASVS catalog does not match the reviewed pin; repair the skill resources")
    catalog = json.loads(raw)
    if catalog.get("Version") != VERSION:
        raise ValueError("unsupported ASVS version")
    return catalog


def requirements(catalog):
    return [
        {"id": "v" + VERSION + "-" + item["Shortcode"][1:], "level": int(item["L"]),
         "chapter": chapter["Shortcode"], "chapter_name": chapter["Name"],
         "section": section["Name"], "description": item["Description"]}
        for chapter in catalog["Requirements"]
        for section in chapter["Items"]
        for item in section["Items"]
    ]


def select(catalog, chapters=None, level=2, ids=None):
    rows = requirements(catalog)
    if ids is not None:
        by_id = {row["id"]: row for row in rows}
        unknown = set(ids) - set(by_id)
        if unknown:
            raise ValueError("unknown versioned ASVS IDs: " + ", ".join(sorted(unknown)))
        return [row for row in rows if row["id"] in ids]
    known = {chapter["Shortcode"] for chapter in catalog["Requirements"]}
    unknown = set(chapters or []) - known
    if unknown:
        raise ValueError("unknown ASVS chapters: " + ", ".join(sorted(unknown)))
    return [row for row in rows if row["level"] <= level and (not chapters or row["chapter"] in chapters)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--list-chapters", action="store_true")
    group.add_argument("--chapters", nargs="+", metavar="V6")
    group.add_argument("--ids", nargs="+", metavar="v5.0.0-6.2.1")
    parser.add_argument("--level", type=int, choices=(1, 2, 3), default=2,
                        help="include controls at this level and below (default: 2)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        catalog = load_catalog()
        if args.list_chapters or (not args.chapters and not args.ids):
            rows = [{"id": item["Shortcode"], "name": item["Name"]} for item in catalog["Requirements"]]
            lines = [row["id"] + ": " + row["name"] for row in rows]
        else:
            rows = select(catalog, args.chapters, args.level, args.ids)
            lines = [row["id"] + " [L" + str(row["level"]) + "; " + row["section"] + "] " + row["description"] for row in rows]
        print(json.dumps(rows, ensure_ascii=False, indent=2) if args.json else "\n".join(lines))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
