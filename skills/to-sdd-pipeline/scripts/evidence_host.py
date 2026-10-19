#!/usr/bin/env python3
"""Service a foreground evidence command using installed authenticated Drive tools."""
import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
from evidence.connected_host import close_session, next_request, respond, start_session, MAX_CONTROL_BYTES
from evidence.io import EvidenceError, read_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    start = actions.add_parser("start")
    start.add_argument("--parent", required=True)
    for name in ("next", "respond", "close"):
        command = actions.add_parser(name)
        command.add_argument("--session", required=True)
        if name == "respond":
            command.add_argument("--request", required=True)
            command.add_argument("--response", required=True)
            command.add_argument("--download")
        if name == "close":
            command.add_argument("--cancel", action="store_true")
    args = parser.parse_args()
    try:
        if args.action == "start":
            result = {"session": str(start_session(Path(args.parent).absolute()))}
        elif args.action == "next":
            result = {"request": next_request(args.session)}
        elif args.action == "respond":
            respond(args.session, args.request, read_json(args.response, MAX_CONTROL_BYTES), materialized_path=args.download)
            result = {"accepted": True}
        else:
            close_session(args.session, cancel=args.cancel)
            result = {"closed": True}
        print(json.dumps(result, ensure_ascii=True))
        return 0
    except (EvidenceError, OSError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
