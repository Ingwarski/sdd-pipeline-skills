"""Frozen pathname emitters from sdd_history.py at 656aa8a774654f3fc9705d5d28beea6a05214e72.

The seven helper bodies are copied verbatim. This bounded compatibility fixture
has no checker, importer validation or network behavior. Its import-source mode
reproduces the old importer's first metadata write; full old CLI validation is
exercised separately against a local git archive.
"""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat
import sys
import uuid

HISTORY = "forge/unit-history"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=True, indent=2, allow_nan=False) + "\n").encode()


def _containment_path(path):
    """Compare equivalent resolved Windows anchors without changing I/O paths."""
    if isinstance(path, PureWindowsPath) and path.root:
        drive = path.drive
        if re.fullmatch(r"\\\\\?\\[A-Za-z]:", drive):
            return PureWindowsPath(drive[4:] + path.root, *path.parts[1:])
        if drive.casefold().startswith("\\\\?\\unc\\"):
            components = drive[8:].split("\\")
            if len(components) == 2 and all(part not in ("", ".", "..", "?") for part in components):
                return PureWindowsPath("\\\\" + drive[8:] + path.root, *path.parts[1:])
    return path


def physical(project, path):
    require(isinstance(path, str) and path and "\\" not in path, "history path must be relative POSIX text")
    parts = PurePosixPath(path)
    require(not parts.is_absolute() and all(p not in ("..", ".") for p in path.split("/")), "unsafe history path: " + path)
    root = Path(project).resolve()
    current = root
    for part in parts.parts:
        current /= part
        try:
            info = current.lstat()
        except (FileNotFoundError, NotADirectoryError):
            continue
        require(not (stat.S_ISLNK(info.st_mode) or
                     getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)),
                "history cannot follow links: " + path)
    # Concurrent parent creation can make Windows realpath retain its extended
    # prefix (initial missing-directory error, final missing-file error).
    require(_containment_path(current.resolve()).is_relative_to(_containment_path(root)),
            "history path escapes project")
    return current


def write_new(project, path, data):
    target = physical(project, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    return {"path": path, "content_hash": sha(data)}


def store_record(project, kind, record, directory=None):
    directory = directory or HISTORY + "/" + kind + "/" + uuid.uuid4().hex
    return write_new(project, directory + "/record.json", encoded(record))

if __name__ == "__main__":
    project, mode = Path(sys.argv[1]), sys.argv[2]
    try:
        if mode == "import-source":
            result = write_new(project, HISTORY + "/external-observations/frozen-emitter/manifest.json",
                               encoded({"synthetic_fixture": True, "verification": {"checks": []}}))
        else:
            result = store_record(project, "runtime-observations",
                                  {"event": "runtime_observation", "version": 2, "synthetic_fixture": True})
        print(json.dumps(result, sort_keys=True))
    except (ValueError, OSError) as error:
        print(json.dumps({"result": "blocked", "detail": str(error)}, sort_keys=True))
        sys.exit(1)
