#!/usr/bin/env python3
"""Explicit evidence setup; importing or inspecting this module has no side effects.

Machine bindings live outside Git. A consuming project's portable policy carries
stable identities, limits and retention, never account credentials or disk paths.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import uuid

sys.dont_write_bytecode = True
SCRIPT_ROOT = Path(__file__).resolve().parent
ENGINE_ROOT = SCRIPT_ROOT.parent / "skills/to-sdd-pipeline/scripts"
sys.path.insert(0, str(ENGINE_ROOT))
from evidence.policy import load_defaults, validate_policy
from evidence.io import EvidenceError


class SetupError(ValueError):
    """A precise setup failure, without provider fallback."""


def evidence_home(value=None):
    return Path(value or os.environ.get("SDD_EVIDENCE_HOME") or Path.home() / ".sdd-pipeline/evidence").expanduser().resolve()


def _read(path):
    if path.is_symlink() or not path.is_file():
        raise SetupError("missing regular setup file: " + str(path))
    if path.stat().st_size > 1024 * 1024:
        raise SetupError("setup file exceeds 1 MiB: " + str(path))
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise SetupError("duplicate setup field: " + key)
            result[key] = value
        return result
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise SetupError("malformed setup file: " + str(path)) from exc


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=".setup-", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            os.chmod(temporary, 0o600)
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _outside(path, project):
    """Machine state and durable evidence may not live in the consuming checkout."""
    roots = [SCRIPT_ROOT.parent]
    if project is not None:
        roots.append(Path(project).resolve())
    for root in roots:
        if path == root or root in path.parents:
            raise SetupError("machine state and durable storage must be outside the repository: " + str(path))
    if any((ancestor / ".git").exists() for ancestor in (path, *path.parents)):
        raise SetupError("machine paths and credentials must be outside Git checkouts: " + str(path))


def _policy_path(project):
    root = Path(project).expanduser().resolve()
    path = root / "forge/evidence-policy.json"
    if path.parent.is_symlink() or path.is_symlink():
        raise SetupError("portable policy must use a contained regular project path")
    return path


def parse_bridge_command(value):
    """A JSON argument array is portable across Windows and Unix terminals."""
    if value.lstrip().startswith("["):
        try:
            result = json.loads(value)
        except json.JSONDecodeError as exc:
            raise SetupError("bridge command JSON must be an argument array") from exc
    else:
        result = shlex.split(value)
    if not isinstance(result, list) or not result or any(not isinstance(item, str) or not item for item in result):
        raise SetupError("bridge command requires a nonempty array of string arguments")
    return result


def _setup_action(project, home):
    arguments = [sys.executable, str(SCRIPT_ROOT / "evidence_setup.py"), "wizard"]
    project_path = Path(project).expanduser().resolve() if project else None
    if project_path is not None:
        arguments += ["--project", str(project_path)]
    # Preserve the exact machine-state destination even when it was supplied by
    # a CLI flag, rather than relying on an unsaved shell environment override.
    arguments += ["--evidence-home", str(home)]
    has_saved_policy = (project_path / "forge/evidence-policy.json").exists() if project_path is not None else (home / "default.json").exists()
    if has_saved_policy:
        arguments.append("--reconfigure")
    command = "& " + " ".join("'" + value.replace("'", "''") + "'" for value in arguments) if os.name == "nt" else shlex.join(arguments)
    return {"next_action": command, "next_action_argv": arguments,
            "setup_note": "Saved choices change only through explicit reconfiguration; restore an unavailable selected disk or external credential before retrying routine operations."}


def _valid_config(config):
    if not isinstance(config, dict) or type(config.get("version")) is not int or config.get("version") != 1:
        raise SetupError("unsupported machine storage configuration; expected version 1")
    if config.get("provider") not in ("local", "folder", "google-drive"):
        raise SetupError("missing or unsupported selected storage provider")
    try:
        if str(uuid.UUID(config["store_id"])) != config["store_id"]:
            raise ValueError()
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        raise SetupError("machine configuration has an invalid store_id") from exc
    if not isinstance(config.get("destination"), str) or not config["destination"]:
        raise SetupError("storage destination is missing")
    receipt = config.get("setup_receipt", {})
    if receipt.get("verified") is not True:
        raise SetupError("storage setup lacks a successful independent-byte probe; rerun explicit configuration")
    if config["provider"] == "google-drive" and config.get("transport") not in ("rclone", "connected"):
        raise SetupError("Google Drive requires the rclone or connected original-byte transport")
    if config["provider"] == "google-drive" and config.get("transport") == "rclone" and config.get("rclone_config") and not Path(config["rclone_config"]).is_file():
        raise SetupError("configured Drive credentials are missing; restore the external rclone config or explicitly --reconfigure after rclone config authentication")
    if config["provider"] == "google-drive":
        if config["transport"] == "rclone":
            executable = config.get("rclone_executable") or "rclone"
            if not isinstance(executable, str) or not shutil.which(executable):
                raise SetupError("configured rclone executable is missing; install the optional rclone tool or restore its saved executable path, then authenticate the selected remote with rclone config")
        else:
            command = config.get("bridge_command")
            if not isinstance(command, list) or not command or any(not isinstance(item, str) or not item for item in command):
                raise SetupError("configured connected Drive bridge command is missing; explicitly --reconfigure with --bridge-command")
            if not shutil.which(command[0]):
                raise SetupError("configured connected Drive bridge executable is missing; restore the saved host bridge or explicitly --reconfigure")
    if config["provider"] != "google-drive" and not Path(config["destination"]).is_dir():
        raise SetupError("selected durable folder is unavailable: " + config["destination"])
    return config


def inspect(project=None, home=None):
    """Read-only status, including setup missing after an otherwise current pull."""
    home = evidence_home(home)
    try:
        policy = validate_policy(_read(_policy_path(project))) if project else None
        config_path = home / "bindings" / (policy["project_id"] + ".json") if policy else home / "default.json"
        config = _valid_config(_read(config_path))
        if policy and (config.get("project_id") != policy["project_id"] or config["store_id"] != policy["store_id"] or config["provider"] != policy["provider"]):
            raise SetupError("project policy and machine binding identities disagree")
        return {"result": "configured", "provider": config["provider"], "store_id": config["store_id"],
                "project_id": policy["project_id"] if policy else None, "config_path": str(config_path),
                "policy_path": str(_policy_path(project)) if project else None}
    except (OSError, ValueError, EvidenceError, KeyError, TypeError) as exc:
        return {"result": "setup_required", "reason": str(exc), "project": str(Path(project).resolve()) if project else None,
                **_setup_action(project, home)}


def _probe(config, project=None):
    """The manager, never an upload response, establishes storage availability."""
    home = evidence_home(config["evidence_home"])
    home.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="setup-probe-", dir=home) as temporary:
        candidate = Path(temporary) / "candidate.json"
        _write(candidate, config)
        command = [sys.executable, str(ENGINE_ROOT / "evidence_store.py"), "setup-probe", "--config", str(candidate)]
        if project:
            command += ["--project", str(Path(project).resolve())]
        result = subprocess.run(command, capture_output=True, text=True, timeout=600)
        try:
            receipt = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise SetupError("storage probe did not return a verification receipt; check the configured transport capabilities") from exc
        if result.returncode or receipt.get("verified") is not True:
            # Manager errors are intended diagnostics. Never emit its subprocess stderr,
            # which could contain credentials from an externally configured bridge.
            message = receipt.get("error") or receipt.get("reason") or "independent-byte verification failed"
            raise SetupError("storage setup failed: " + str(message))
        return receipt


def configure(project=None, *, provider, destination=None, transport=None, bridge_command=None,
              rclone_config=None, rclone_executable=None, home=None, limits=None, retention_days=None,
              drive_retention_days="unset", adopt=None, reconfigure=False, probe=None):
    """An explicit selected provider authorizes its bounded verification upload."""
    home = evidence_home(home)
    _outside(home, project)
    policy_path = _policy_path(project) if project else None
    existing_policy = validate_policy(_read(policy_path)) if policy_path and policy_path.exists() else None
    old_config_path = home / "bindings" / (existing_policy["project_id"] + ".json") if existing_policy else None if project else home / "default.json"
    old_config = _read(old_config_path) if old_config_path and old_config_path.exists() else None
    previous_policy = existing_policy
    if previous_policy is None and not project and old_config and (home / "default-policy.json").exists():
        previous_policy = _read(home / "default-policy.json")
    if old_config and not reconfigure:
        raise SetupError("saved storage choices exist; use --reconfigure to change them")
    if existing_policy and not old_config and not reconfigure:
        raise SetupError("this checkout already has a portable policy; use --reconfigure to bind this machine without changing its project identity")
    if provider not in ("local", "folder", "google-drive"):
        raise SetupError("provider must be local, folder, or google-drive")
    if adopt and not project:
        raise SetupError("archive adoption requires --project and its declarative mapping")
    if provider == "google-drive" and drive_retention_days == "unset" and not (old_config and old_config.get("provider") == "google-drive" and previous_policy):
        raise SetupError("choose --drive-retention-days DAYS or never explicitly; local retention never sets Drive archive expiry")
    destination = destination or None
    if destination and provider in ("local", "folder"):
        destination = str(Path(destination).expanduser().resolve())
    same_store = old_config and old_config.get("provider") == provider and (destination is None or old_config.get("destination") == destination)
    store_id = old_config["store_id"] if same_store else existing_policy["store_id"] if existing_policy and not old_config else str(uuid.uuid4())
    same_provider = old_config and old_config.get("provider") == provider
    if same_provider:
        destination = destination or old_config["destination"]
        transport = transport or old_config.get("transport")
        bridge_command = bridge_command or old_config.get("bridge_command")
        rclone_config = rclone_config or old_config.get("rclone_config")
        rclone_executable = rclone_executable or old_config.get("rclone_executable")
    if provider == "local":
        destination = destination or str(home / "durable" / store_id)
        transport = "local"
    elif provider == "folder":
        if not destination:
            raise SetupError("folder storage requires --destination pointing to the selected folder or mounted disk")
        transport = "local"
    else:
        if not destination:
            raise SetupError("Google Drive requires --destination REMOTE:PATH or a connected Drive folder ID")
        transport = transport or "rclone"
        if transport not in ("rclone", "connected"):
            raise SetupError("Google Drive transport must be rclone or connected")
        if transport == "connected" and not bridge_command:
            raise SetupError("connected Drive requires --bridge-command with original-byte upload/download capabilities")
    if provider != "google-drive":
        destination = str(Path(destination).expanduser().resolve())
        _outside(Path(destination), project)
    config = {"version": 1, "provider": provider, "destination": destination, "transport": transport,
              "evidence_home": str(home), "store_id": store_id}
    if bridge_command:
        config["bridge_command"] = list(bridge_command)
    if rclone_config:
        credential_path = Path(rclone_config).expanduser().resolve()
        _outside(credential_path, project)
        config["rclone_config"] = str(credential_path)
    if rclone_executable:
        config["rclone_executable"] = rclone_executable
    project_id = existing_policy["project_id"] if existing_policy else str(uuid.uuid4())
    policy = deepcopy(previous_policy or load_defaults())
    policy.update(project_id=project_id, store_id=store_id, provider=provider)
    policy["limits"].update(limits or {})
    if retention_days is not None:
        policy["retention"]["local_days"] = retention_days
    if drive_retention_days != "unset":
        policy["retention"]["drive_days"] = None if drive_retention_days == "never" else int(drive_retention_days)
    policy = validate_policy(policy)
    if project:
        config["project_id"] = project_id
    receipt = (probe or _probe)(config, project)
    if not isinstance(receipt, dict) or receipt.get("verified") is not True:
        raise SetupError("storage probe did not independently verify bytes")
    config["setup_receipt"] = receipt
    config["configured_at"] = datetime.now(timezone.utc).isoformat()
    config_path = home / "bindings" / (project_id + ".json") if project else home / "default.json"
    _write(home / "stores" / (store_id + ".json"), config)
    _write(config_path, config)
    if project:
        _write(policy_path, policy)
    else:
        # Defaults are separately saved machine choices; a project receives its own UUID.
        _write(home / "default-policy.json", {key: value for key, value in policy.items() if key not in ("project_id", "store_id", "provider")})
    status = inspect(project, home)
    _write(home / "setup-status.json", status)
    if adopt:
        command = [sys.executable, str(ENGINE_ROOT / "evidence_store.py"), "adopt", "--project", str(Path(project).resolve()), "--mapping", str(Path(adopt).resolve())]
        result = subprocess.run(command, capture_output=True, text=True, timeout=600)
        if result.returncode:
            raise SetupError("storage configured, but archive adoption is incomplete; inspect the mapping with evidence_store.py adopt before using dependent evidence")
        status["adoption"] = "completed"
    return status


def _apply_saved_default(project, home):
    config = _valid_config(_read(home / "default.json"))
    _outside(home, project)
    if config["provider"] != "google-drive":
        _outside(Path(config["destination"]).resolve(), project)
    policy_path = _policy_path(project)
    if policy_path.exists():
        policy = validate_policy(_read(policy_path))
        if policy["store_id"] != config["store_id"] or policy["provider"] != config["provider"]:
            raise SetupError("portable policy selects another store; explicitly reconfigure this machine's binding")
    else:
        policy = _read(home / "default-policy.json")
        policy.update(project_id=str(uuid.uuid4()), store_id=config["store_id"], provider=config["provider"])
        policy = validate_policy(policy)
        _write(policy_path, policy)
    config["project_id"] = policy["project_id"]
    _write(home / "bindings" / (policy["project_id"] + ".json"), config)
    return inspect(project, home)


def ensure(project=None, *, home=None, interactive=False):
    """An explicit managed-operation boundary; never run merely on project open."""
    home = evidence_home(home)
    status = inspect(project, home)
    if status["result"] == "configured":
        return status
    if project and (home / "default.json").exists():
        try:
            policy_path = _policy_path(project)
            policy = validate_policy(_read(policy_path)) if policy_path.exists() else None
            # Never replace a corrupt or unavailable selected binding with defaults.
            if policy is None or not (home / "bindings" / (policy["project_id"] + ".json")).exists():
                status = _apply_saved_default(project, home)
        except (SetupError, EvidenceError, OSError, ValueError, TypeError) as exc:
            status["reason"] = str(exc)
    # Saved-but-unavailable stores require explicit reconfiguration; an ordinary
    # update must not repeat questions or replace the account/destination.
    saved_choice = (home / "default.json").exists()
    if project:
        try:
            saved_choice = saved_choice or _policy_path(project).exists()
        except SetupError:
            saved_choice = True
    if status["result"] == "setup_required" and interactive and not saved_choice:
        return wizard(project, home=home)
    _outside(home, project)
    _write(home / "setup-status.json", status)
    return status


def wizard(project=None, *, home=None, reconfigure=False, input_fn=input):
    """Small terminal wizard. EOF/cancel leaves existing policies and stores untouched."""
    print("Select durable evidence storage: 1 managed local, 2 selected folder/disk, 3 Google Drive.")
    print("A folder on the same disk reduces Git clutter but does not free disk space. Cache/staging are separate from the durable store.")
    try:
        prior = None
        defaults = load_defaults()
        if reconfigure:
            policy_path = _policy_path(project) if project else evidence_home(home) / "default-policy.json"
            if policy_path.exists():
                defaults = _read(policy_path)
                config_path = evidence_home(home) / "bindings" / (defaults["project_id"] + ".json") if project else evidence_home(home) / "default.json"
                if config_path.exists():
                    prior = _read(config_path)
        choice = input_fn("Storage choice [1/2/3; blank postpones setup]: ").strip()
        if not choice:
            return ensure(project, home=home, interactive=False)
        if choice not in ("1", "2", "3"):
            raise SetupError("choose 1, 2, or 3")
        provider = {"1": "local", "2": "folder", "3": "google-drive"}[choice]
        destination = (input_fn("Destination folder, rclone REMOTE:PATH, or connected folder ID (blank preserves an existing same-provider choice): ").strip() or None) if choice != "1" else None
        options = {}
        if provider == "google-drive":
            transport_default = prior.get("transport", "rclone") if prior and prior["provider"] == "google-drive" else "rclone"
            options["transport"] = input_fn("Drive transport [rclone/connected, default " + transport_default + "]: ").strip() or transport_default
            if options["transport"] == "connected":
                value = input_fn("Connected original-byte bridge command (JSON argument array recommended; blank preserves saved command): ").strip()
                options["bridge_command"] = parse_bridge_command(value) if value else None
            previous_drive = prior and prior["provider"] == "google-drive"
            drive_default = str(defaults["retention"]["drive_days"]) if defaults["retention"]["drive_days"] is not None else "never"
            label = "Drive archive expiry [days or never" + (", saved " + drive_default if previous_drive else "; explicit choice required") + "]: "
            options["drive_retention_days"] = input_fn(label).strip() or (drive_default if previous_drive else "")
            if not options["drive_retention_days"]:
                raise SetupError("Drive archive expiry needs an explicit choice")
        limits = {}
        for key, label in (("local_stop_bytes", "Combined local capture/cache/staging/readback/restoration bytes"),
                           ("run_stop_bytes", "Gross run bytes"), ("unit_stop_bytes", "Cumulative unit bytes"),
                           ("project_generation_stop_bytes", "Cumulative project generation bytes"),
                           ("retained_stop_bytes", "Retained unique project bytes"), ("retained_stop_objects", "Retained physical objects"),
                           ("run_stop_files", "Logical files per run"), ("unit_stop_files", "Cumulative logical files per unit"),
                           ("project_generation_stop_files", "Cumulative logical project files"), ("metadata_stop_bytes", "Combined metadata/history/index bytes")):
            value = input_fn(label + " [" + str(defaults["limits"][key]) + "]: ").strip()
            if value:
                limits[key] = int(value)
        # Review warnings and format targets remain independently configurable via CLI.
        retention_default = defaults["retention"]["local_days"]
        retention = input_fn("Local generated-artifact retention days [" + str(retention_default) + "]: ").strip()
        adoption = input_fn("Existing archive mapping to adopt [blank means none]: ").strip() if project else None
        return configure(project, provider=provider, destination=destination, home=home, limits=limits,
                         retention_days=int(retention or str(retention_default)), adopt=adoption, reconfigure=reconfigure, **options)
    except EOFError:
        return ensure(project, home=home, interactive=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "ensure", "wizard", "configure"):
        sub = commands.add_parser(name)
        sub.add_argument("--project", type=Path)
        sub.add_argument("--evidence-home", type=Path)
        if name in ("ensure", "wizard"):
            sub.add_argument("--reconfigure", action="store_true")
            sub.add_argument("--non-interactive", action="store_true")
        if name == "configure":
            sub.add_argument("--provider", required=True, choices=("local", "folder", "google-drive"))
            sub.add_argument("--destination")
            sub.add_argument("--transport", choices=("rclone", "connected"))
            sub.add_argument("--bridge-command", help="JSON argument array, or shell-quoted executable and arguments")
            sub.add_argument("--rclone-config", type=Path)
            sub.add_argument("--rclone-executable")
            sub.add_argument("--local-work-bytes", type=int)
            sub.add_argument("--run-stop-bytes", type=int)
            sub.add_argument("--unit-generated-bytes", type=int)
            sub.add_argument("--project-retained-bytes", type=int)
            sub.add_argument("--limit", action="append", default=[], metavar="KEY=INTEGER", help="override any named aggregate policy limit")
            sub.add_argument("--retention-days", type=int, help="local expiry eligibility; first setup defaults to 30, reconfiguration preserves saved days")
            sub.add_argument("--drive-retention-days", default="unset", help="explicit DAYS or never for Google Drive")
            sub.add_argument("--adopt", type=Path)
            sub.add_argument("--reconfigure", action="store_true")
    args = parser.parse_args(argv)
    try:
        if sys.version_info < (3, 12):
            raise SetupError("Python 3.12+ is required; no setup changes made")
        if args.command == "status":
            status = inspect(args.project, args.evidence_home)
        elif args.command in ("ensure", "wizard"):
            interactive = not args.non_interactive and sys.stdin.isatty() and sys.stdout.isatty()
            if args.reconfigure:
                if not interactive:
                    raise SetupError("noninteractive reconfiguration requires the configure command and explicit provider options")
                status = wizard(args.project, home=args.evidence_home, reconfigure=True)
            elif args.command == "wizard" and interactive:
                status = wizard(args.project, home=args.evidence_home)
            else:
                status = ensure(args.project, home=args.evidence_home, interactive=interactive)
        else:
            limits = {}
            for value in args.limit:
                key, separator, number = value.partition("=")
                if not separator:
                    raise SetupError("--limit requires KEY=INTEGER")
                limits[key] = int(number)
            for option, key in ((args.local_work_bytes, "local_stop_bytes"), (args.run_stop_bytes, "run_stop_bytes"),
                                (args.unit_generated_bytes, "unit_stop_bytes"), (args.project_retained_bytes, "retained_stop_bytes")):
                if option is not None:
                    limits[key] = option
            status = configure(args.project, provider=args.provider, destination=args.destination, transport=args.transport,
                               bridge_command=parse_bridge_command(args.bridge_command) if args.bridge_command else None,
                               rclone_config=args.rclone_config, rclone_executable=args.rclone_executable,
                               home=args.evidence_home, limits=limits, retention_days=args.retention_days,
                               drive_retention_days=args.drive_retention_days, adopt=args.adopt, reconfigure=args.reconfigure)
        print(json.dumps(status, indent=2))
        return 0 if status["result"] == "configured" else 2
    except (OSError, SetupError, EvidenceError, ValueError, TypeError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"result": "setup_required", "reason": str(exc)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
