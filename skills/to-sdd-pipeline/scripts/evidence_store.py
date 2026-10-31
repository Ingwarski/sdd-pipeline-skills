#!/usr/bin/env python3
"""Explicit, bounded evidence management. The SDD checker never calls this tool."""
import argparse
from contextlib import contextmanager
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import uuid

sys.dont_write_bytecode = True
from evidence.io import EvidenceError, atomic_json, hash_file, read_json
from evidence.policy import load_defaults, validate_policy
from evidence.transports import LocalTransport, RcloneDriveTransport, ConnectedDriveTransport, JsonCommandAdapter
from evidence.manager import Manager
from evidence.archive import build_pack, verify_pack
from evidence.accounting import Accounting, git_blob_growth
from evidence import lifecycle_cli


def home_path(value=None):
    return Path(value or os.environ.get("SDD_EVIDENCE_HOME") or Path.home() / ".sdd-pipeline/evidence").expanduser().resolve()


def transport(config, state, host_session=None):
    provider = config["provider"]
    if provider in ("local", "folder"):
        return LocalTransport(Path(config["destination"]).expanduser().resolve())
    if provider != "google-drive":
        raise EvidenceError("unsupported configured provider; rerun explicit storage setup")
    if config.get("transport") == "rclone":
        return RcloneDriveTransport(config["destination"], config=config.get("rclone_config"),
                                    executable=config.get("rclone_executable") or "rclone", state_dir=state)
    if config.get("transport") == "connected":
        if config.get("bridge_command"):
            adapter = JsonCommandAdapter(config["bridge_command"])
        else:
            from evidence.connected_host import ConnectedHostAdapter
            selected = host_session or os.environ.get("SDD_EVIDENCE_HOST_SESSION")
            if not selected:
                raise EvidenceError("connected Drive needs an active Codex/Claude tool session; ask the agent to start the bundled evidence_host.py session and pass --host-session (or SDD_EVIDENCE_HOST_SESSION). The installed Google Drive plugin supplies authentication; no custom bridge or rclone is required")
            adapter = ConnectedHostAdapter(selected)
        return ConnectedDriveTransport(adapter, config["destination"], state_dir=state)
    raise EvidenceError("Google Drive has no selected authenticated transport; configure rclone or an available host bridge")


def load_manager(args):
    home = home_path(args.home)
    project = Path(args.project).resolve() if args.project else None
    if args.policy:
        policy = validate_policy(read_json(Path(args.policy).resolve(), 1024 * 1024))
    elif project:
        policy = validate_policy(read_json(project / "forge/evidence-policy.json", 1024 * 1024))
    elif args.project_id and args.config:
        config = read_json(Path(args.config).resolve(), 1024 * 1024)
        policy = validate_policy({**load_defaults(), "project_id": args.project_id, "store_id": config["store_id"], "provider": config["provider"]})
    else:
        raise EvidenceError("storage setup required: pass --project, or cold recovery --config and --project-id")
    config_path = Path(args.config).resolve() if args.config else home / "bindings" / (policy["project_id"] + ".json")
    config = read_json(config_path, 1024 * 1024)
    if config.get("version") != 1 or (config["provider"], config["store_id"]) != (policy["provider"], policy["store_id"]):
        raise EvidenceError("portable project policy and machine storage binding disagree")
    home = home_path(args.home or config.get("evidence_home"))
    for candidate in (home, Path(config["destination"]).resolve() if config["provider"] in ("local", "folder") else home):
        if project and candidate.is_relative_to(project):
            raise EvidenceError("evidence store and working space must be outside the project")
    state = home / "projects" / policy["project_id"] / "transfers"
    manager = Manager(transport(config, state, getattr(args, "host_session", None)), home, policy, project=project)
    if not args.policy and not project:
        catalog = manager._catalog(recover_policy=True)
        if not catalog.get("root_key") or "policy" not in catalog:
            raise EvidenceError("cold recovery needs a catalog with its original portable policy, or explicit --policy")
        recovered = validate_policy(catalog["policy"])
        if (recovered["project_id"], recovered["store_id"], recovered["provider"]) != (policy["project_id"], policy["store_id"], policy["provider"]):
            raise EvidenceError("recovered portable policy disagrees with the selected storage identity")
        manager.policy, manager.limits = recovered, recovered["limits"]
    return manager


def project_setup(args):
    """Explicit managed first use reuses saved choices; status only inspects."""
    if not args.project or args.config or args.policy:
        return None
    source = Path(__file__).resolve().parents[3] / "scripts/evidence_setup.py"
    spec = importlib.util.spec_from_file_location("sdd_evidence_setup_boundary", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    home = home_path(args.home)
    report = module.inspect(Path(args.project).resolve(), home)
    if report["result"] == "configured":
        return None
    if args.command in ("archive", "prepare", "restore", "import", "adopt", "run"):
        report = module.ensure(Path(args.project).resolve(), home=home,
                               interactive=sys.stdin.isatty() and sys.stdout.isatty(),
                               host_session=getattr(args, "host_session", None))
    return None if report["result"] == "configured" else report


def references(args, manager):
    if args.refs:
        value = read_json(Path(args.refs).resolve(), manager.limits["metadata_stop_bytes"])
        return value["refs"] if isinstance(value, dict) else value
    catalog = manager._catalog()
    if args.artifact:
        try:
            return [catalog["refs"][ident] for ident in args.artifact]
        except KeyError as error:
            raise EvidenceError("artifact identity is absent from durable catalog") from error
    return list(catalog["refs"].values())


def _history_home(evidence_cache):
    home = None
    if evidence_cache is not None:
        cache = Path(evidence_cache).resolve()
        if cache.name == "cache" and cache.parent.parent.name == "projects":
            home = str(cache.parent.parent.parent)
    return home


def _history_manager(project, *, evidence_cache=None):
    from types import SimpleNamespace
    return load_manager(SimpleNamespace(project=str(Path(project).resolve()), home=_history_home(evidence_cache),
                        policy=None, config=None, project_id=None, host_session=None))


@contextmanager
def history_publication_guard(project, manifest_path, *, evidence_cache=None, enabled=True):
    """Serialize managed history publication with dependency-based deletion."""
    if not enabled:
        yield None
        return
    import sdd_history
    manifest = read_json(sdd_history.physical(project, manifest_path), 16 * 1024 * 1024)
    adopted = isinstance(manifest.get("history_integrity"), dict) and manifest["history_integrity"].get("optional_diagnostics_ref")
    if not adopted:
        # Legacy prepared-proof work does not need a new provider session. The
        # designated coordinator persists adoption locally; old branches on that
        # coordinator still see the barrier even without a new manifest field.
        policy_path = Path(project) / "forge/evidence-policy.json"
        if not policy_path.exists():
            yield None
            return
        policy = validate_policy(read_json(policy_path, 1024 * 1024))
        home = home_path(_history_home(evidence_cache))
        binding_path = home / "bindings" / (policy["project_id"] + ".json")
        bound = binding_path.exists()
        if bound:
            binding = read_json(binding_path, 1024 * 1024)
            home = home_path(_history_home(evidence_cache) or binding.get("evidence_home"))
        state = home / "projects" / policy["project_id"]
        if not (state / "lifecycle-bindings.json").exists() and not any(state.glob("lifecycle-adoption-*.json")):
            if not bound:
                yield None
                return
            # Serialize with adoption without opening the provider. Recheck
            # after acquiring the lock in case adoption won the race.
            local = Manager(None, home, policy, project=Path(project).resolve())
            with local.locked():
                fresh = read_json(sdd_history.physical(project, manifest_path), 16 * 1024 * 1024)
                fresh_marker = isinstance(fresh.get("history_integrity"), dict) and fresh["history_integrity"].get("optional_diagnostics_ref")
                if not fresh_marker and not (state / "lifecycle-bindings.json").exists() and not any(state.glob("lifecycle-adoption-*.json")):
                    yield None
                    return
    try:
        manager = _history_manager(project, evidence_cache=evidence_cache)
    except (EvidenceError, FileNotFoundError) as error:
        if adopted or not (isinstance(error, FileNotFoundError) or isinstance(error.__cause__, FileNotFoundError)):
            raise
        yield None
        return
    with manager.locked():
        catalog = manager._catalog(mutation=True)
        manager._lifecycle_writer_guard(catalog)
        if adopted and not catalog.get("lifecycle", {}).get("adopted"):
            raise EvidenceError("lifecycle adoption is unfinished; resume it before history publication")
        yield manager


def checkpoint_after_history(project, manifest_path, *, evidence_cache=None):
    """Refresh adopted dependencies after a successful history publication.

    This is called by the mutating CLI, not history validators or the checker.
    Preserve the original command's stdout/reference schema and report cleanup
    separately. An unavailable binding defers cleanup, never changes acceptance.
    """
    try:
        import sdd_history
        selected = sdd_history.physical(project, manifest_path)
        manifest = read_json(selected, 16 * 1024 * 1024)
        if not isinstance(manifest.get("history_integrity"), dict) or not manifest["history_integrity"].get("optional_diagnostics_ref"):
            return None
        manager = _history_manager(project, evidence_cache=evidence_cache)
        return lifecycle_cli.checkpoint(manager, manifest_path=manifest_path)
    except (EvidenceError, ValueError, OSError, KeyError, TypeError) as error:
        return {"status": "cleanup_deferred", "reason": str(error)}


def probe(args):
    config = read_json(Path(args.config).resolve(), 1024 * 1024)
    home = home_path(config.get("evidence_home"))
    home.mkdir(parents=True, exist_ok=True)
    ident = str(uuid.uuid4())
    test_transport = transport(config, home / "setup-transfers" / ident, getattr(args, "host_session", None))
    locator = None
    with tempfile.TemporaryDirectory(dir=home, prefix="probe-") as temp:
        temp = Path(temp).resolve()
        data = temp / "synthetic.bin"
        data.write_bytes(b"SDD synthetic storage verification\n" * 256)
        digest, size = hash_file(data)
        packed = build_pack([{"path": data, "sha256": digest, "size": size}], temp / "pack.zip", 1024 * 1024, 10)
        try:
            locator = test_transport.put("setup-probes/" + ident + ".zip", temp / "pack.zip")
            test_transport.get(locator, temp / "independent.zip", packed["size"])
            verified = verify_pack(temp / "independent.zip", packed["sha256"], packed["size"], packed["members"],
                                   destination=temp / "restored", max_bytes=1024 * 1024, max_files=10)
            if hash_file(temp / "restored" / digest) != (digest, size):
                raise EvidenceError("setup restoration hash mismatch")
        finally:
            if locator is not None:
                # delete() verifies provider-specific absence; failures do not claim successful setup.
                test_transport.delete(locator)
    return {"version": 1, "verified": True, "provider": config["provider"],
            "archive_sha256": packed["sha256"], "archive_size": packed["size"],
            "original_sha256": digest, "original_size": size, "test_resource_removed": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("archive", "prepare", "restore", "recover", "import", "adopt", "cleanup", "reconcile", "retention-policy", "status", "accounting-receipt", "run", "complete-run", "initialize-generation-authority", "acknowledge-missing-upload", "quarantine-producer", "revalidate-quarantine-device", "git-review", "setup-probe") + lifecycle_cli.COMMANDS:
        sub = commands.add_parser(name)
        sub.add_argument("--project")
        sub.add_argument("--policy")
        sub.add_argument("--config")
        sub.add_argument("--project-id")
        sub.add_argument("--home")
        sub.add_argument("--host-session", help="Active agent's bundled Drive tool session; never saved as account configuration")
        sub.add_argument("--refs")
        sub.add_argument("--artifact", action="append")
        if name in lifecycle_cli.COMMANDS:
            lifecycle_cli.arguments(sub, name)
        elif name == "archive":
            sub.add_argument("--spec", required=True)
            sub.add_argument("--migration", action="store_true")
            sub.add_argument("--remove-local", action="store_true")
            sub.add_argument("--output")
        elif name in ("import", "adopt"):
            sub.add_argument("--mapping", required=True)
            sub.add_argument("--output")
        elif name in ("restore", "recover"):
            sub.add_argument("--destination", required=True)
        elif name == "cleanup":
            sub.add_argument("--apply", action="store_true")
            sub.add_argument("--expire", action="store_true")
            sub.add_argument("--claims")
        elif name == "reconcile":
            sub.add_argument("--apply", action="store_true")
        elif name == "quarantine-producer":
            sub.add_argument("--attempt-id", required=True)
            sub.add_argument("--proof", required=True, help="Bound original producer disposition proof JSON")
            sub.add_argument("--apply", action="store_true")
        elif name == "revalidate-quarantine-device":
            sub.add_argument("--attempt-id", required=True)
            sub.add_argument("--assertion", required=True)
            sub.add_argument("--assertion-sha256", required=True)
            sub.add_argument("--operation-id", required=True)
            sub.add_argument("--apply", action="store_true")
        elif name == "git-review":
            sub.add_argument("--base", required=True)
            sub.add_argument("--head", default="HEAD")
        elif name == "run":
            sub.add_argument("--run-id", required=True)
            sub.add_argument("--unit-id", required=True)
            sub.add_argument("--output-dir", required=True)
            sub.add_argument("--reserve-bytes", type=int, required=True)
            sub.add_argument("--reserve-files", type=int, required=True)
            sub.add_argument("--timeout", type=int, default=3600)
            sub.add_argument("--defer-run-completion", action="store_true", help="Settle this worker; the coordinator seals the shared run with complete-run")
            sub.add_argument("producer", nargs=argparse.REMAINDER)
        elif name == "complete-run":
            sub.add_argument("--run-id", required=True)
        elif name == "acknowledge-missing-upload":
            sub.add_argument("--key", required=True, help="Exact immutable key from the pending upload checkpoint")
        elif name == "accounting-receipt":
            sub.add_argument("--output")
    args = parser.parse_args()
    if sys.version_info < (3, 12):
        parser.error("Python 3.12+ is required")
    try:
        if args.command == "setup-probe":
            result = probe(args)
        elif args.command == "git-review":
            policy_path = Path(args.policy).resolve() if args.policy else Path(args.project or ".").resolve() / "forge/evidence-policy.json"
            thresholds = validate_policy(read_json(policy_path, 1024 * 1024))["git_review"] if policy_path.exists() else load_defaults()["git_review"]
            result = git_blob_growth(Path(args.project or ".").resolve(), args.base, args.head,
                                    blob_review_bytes=thresholds["blob_bytes"], range_review_bytes=thresholds["range_bytes"])
        else:
            setup = project_setup(args)
            if setup is not None:
                print(json.dumps(setup, ensure_ascii=True, sort_keys=True))
                return 2
            manager = load_manager(args)
            if args.command in ("archive", "prepare", "restore", "recover", "import", "adopt", "run"):
                manager.cleanup(dry_run=False)
            if args.command in lifecycle_cli.COMMANDS:
                result = lifecycle_cli.execute(args, manager)
            elif args.command == "archive":
                result = {"version": 1, "refs": manager.archive(read_json(Path(args.spec).resolve(), manager.limits["metadata_stop_bytes"]),
                    migration=args.migration, remove_local=args.remove_local)}
            elif args.command in ("import", "adopt"):
                result = {"version": 1, "refs": manager.import_archive(read_json(Path(args.mapping).resolve(), manager.limits["metadata_stop_bytes"]))}
            elif args.command == "prepare":
                result = {"cache": str(manager.prepare(references(args, manager)))}
            elif args.command in ("restore", "recover"):
                result = {"restored": manager.restore(references(args, manager), args.destination)}
            elif args.command == "cleanup":
                claims = read_json(Path(args.claims).resolve(), manager.limits["metadata_stop_bytes"]) if args.claims else {}
                if claims and (claims.get("version") != 1 or claims.get("project_id") != manager.policy["project_id"]):
                    raise EvidenceError("current claim snapshot belongs to another project or schema")
                result = {"actions": manager.cleanup(dry_run=not args.apply, expire=args.expire,
                    protected_refs=claims.get("evidence_refs", []), reference_snapshot_complete=claims.get("complete") is True)}
            elif args.command == "reconcile":
                result = {"actions": manager.reconcile(dry_run=not args.apply)}
            elif args.command == "quarantine-producer":
                result = manager.quarantine_producer(args.attempt_id,
                    read_json(Path(args.proof).resolve(), manager.limits["metadata_stop_bytes"]),
                    dry_run=not args.apply)
            elif args.command == "initialize-generation-authority":
                result = manager.initialize_generation_authority()
            elif args.command == "acknowledge-missing-upload":
                acknowledge = getattr(manager.transport, "acknowledge_missing_upload", None)
                if acknowledge is None:
                    raise EvidenceError("selected transport has no pending cloud-upload checkpoints")
                prefix = "projects/" + manager.policy["project_id"] + "/"
                if not args.key.startswith(prefix):
                    raise EvidenceError("upload acknowledgement must name an exact key in this project's namespace")
                acknowledge(args.key)
                result = {"acknowledged_missing_upload": args.key, "verified_absent": True}
            elif args.command == "complete-run":
                manager.assert_generation_authority()
                with Accounting(manager.state / "accounting.sqlite", manager.policy["project_id"], manager.policy) as ledger:
                    manager._reconcile_ledger(manager._catalog(), ledger)
                    ledger._publication_manager = (manager, None, None)
                    ledger.complete_run(args.run_id)
                result = {"run_id": args.run_id, "status": "complete"}
            elif args.command == "retention-policy":
                if not args.artifact:
                    raise EvidenceError("explicit imported artifact identities are required for a migration retention decision")
                result = {"refs": manager.establish_import_retention(args.artifact)}
            elif args.command == "accounting-receipt":
                if not args.project and not args.policy:
                    raise EvidenceError("accounting-receipt requires --project or --policy with the original portable policy file: recovered policy values cannot establish its original byte hash; cold payload restoration remains available")
                policy_sha = hash_file(Path(args.policy).resolve() if args.policy else Path(args.project).resolve() / "forge/evidence-policy.json")[0]
                with manager.accounting_receipt_snapshot(policy_sha) as result:
                    if args.output:
                        selected = Path(args.output).expanduser().absolute()
                        selected.parent.mkdir(parents=True, exist_ok=True)
                        atomic_json(selected.parent.resolve() / selected.name, result)
                    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
                    if (result.get("version") in (2, 3) and result.get("generation_ready") is True
                            and result.get("selected_scope", {}).get("complete") is True):
                        return 0
                    return 1 if result.get("incomplete") else 0
            elif args.command == "revalidate-quarantine-device":
                result = manager.revalidate_quarantine_device(args.attempt_id,
                    {"path": str(Path(args.assertion).expanduser().absolute()), "sha256": args.assertion_sha256},
                    operation_id=args.operation_id, dry_run=not args.apply)
            elif args.command == "run":
                from evidence.producer import run_producer
                manager.assert_generation_authority()
                with Accounting(manager.state / "accounting.sqlite", manager.policy["project_id"], manager.policy) as ledger:
                    # A missing local DB is cold recovery, not a fresh project.
                    # Durable generation establishes the floor before launching
                    # or creating producer outputs; failed local charges remain.
                    manager._reconcile_ledger(manager._catalog(), ledger)
                    violations = ledger._violations(ledger.snapshot(args.run_id, args.unit_id)["totals"])
                    if violations:
                        raise EvidenceError("producer cannot start with exhausted aggregate accounting: " + "; ".join(violations))
                    command = args.producer[1:] if args.producer[:1] == ["--"] else args.producer
                    selected = Path(args.output_dir).expanduser().absolute()
                    if selected.is_symlink():
                        raise EvidenceError("producer output directory must not be a link")
                    selected.mkdir(parents=True, exist_ok=True)
                    intent = manager.begin_generation(args.run_id, args.unit_id, args.reserve_bytes, args.reserve_files)
                    result = None
                    try:
                        result = run_producer(ledger, args.run_id, args.unit_id, selected.resolve(), command,
                                              args.reserve_bytes, args.reserve_files, timeout=args.timeout,
                                              complete_run=not args.defer_run_completion, intent_id=intent, manager=manager)
                    finally:
                        manager.finish_generation(intent, reservation_id=(result or {}).get("reservation_id"))
            else:
                result = manager.status()
        if getattr(args, "output", None):
            selected = Path(args.output).expanduser().absolute()
            selected.parent.mkdir(parents=True, exist_ok=True)
            atomic_json(selected.parent.resolve() / selected.name, result)
        if args.command in ("archive", "import", "adopt", "run", "complete-run"):
            status = lifecycle_cli.checkpoint(manager)
            if status.get("status") != "not_adopted":
                print(json.dumps({"evidence_lifecycle": status}, ensure_ascii=True), file=sys.stderr)
        print(json.dumps(result, ensure_ascii=True, sort_keys=True))
        if (args.command == "accounting-receipt" and result.get("version") == 2
                and result.get("kind") == "scoped-known-generation"
                and result.get("generation_ready") is True
                and result.get("selected_scope", {}).get("complete") is True):
            return 0
        if result.get("incomplete") or result.get("status") == "incomplete" or any(x.get("incomplete") or x.get("action") == "delete-failed" for x in result.get("actions", [])):
            return 1
        return 0
    except (EvidenceError, ValueError, OSError, KeyError, TypeError) as error:
        print(json.dumps({"incomplete": True, "error": str(error)}, ensure_ascii=True))
        return 1


if __name__ == "__main__":
    sys.exit(main())
