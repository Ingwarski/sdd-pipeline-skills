#!/usr/bin/env python3
"""Guard fresh installations and fast-forward updates of a standalone SDD checkout."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile


RECOVERY = "docs/installation.md#recover-a-misplaced-installation"
RETIRED = ("communications-audit", "issue-happypro-certificate")
SOURCE_ROOTS = ("skills", ".agents/skills", ".codex/skills", ".claude/skills")
REQUIRED = ("skills-manifest.json", "retired-skills.txt", "install.sh", "install.ps1",
            "update.sh", "update.ps1", "scripts/install_manifest.py",
            "skills/to-sdd-pipeline/SKILL.md")
ORIGIN = re.compile(r"(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)"
                    r"ingwarski/(?:sdd-pipeline-skills|codex-skills)(?:\.git)?/?", re.I)
PRODUCT_MARKERS = (
    ".git", ".hg", ".svn", "forge", ".sdd-pipeline-skills", "skills-manifest.json",
    "package.json", "pyproject.toml", "setup.py", "requirements.txt", "Cargo.toml",
    "go.mod", "pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle",
    "Gemfile", "composer.json", "Package.swift", "CMakeLists.txt", "Makefile",
    "Dockerfile", "pubspec.yaml", "mix.exs", "src", "index.html", "main.py",
    "app.py", "main.go", "AGENTS.md", "CLAUDE.md", "docs/product-idea.md",
    "docs/project-context.md", "docs/prd.md", "docs/development-plan.md",
)
GIT_PATH_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
                "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
                "GIT_QUARANTINE_PATH", "GIT_NAMESPACE", "GIT_SHALLOW_FILE")


def entry(path):
    """Keep unreadable, dangling and missing entries distinct."""
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


def redirected(info):
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def absolute(value):
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts or any(c in str(path) for c in "\r\n"):
        raise ValueError(f"provide an absolute path without '..' or line breaks: {path}")
    return path


def physical_directory(value):
    path = absolute(value)
    # Resolve each existing ancestor strictly. resolve(strict=False) alone turns
    # a dangling junction/symlink into what looks like an eligible absent path.
    physical = Path(path.anchor)
    for part in path.parts[1:]:
        physical /= part
        info = entry(physical)
        if info is not None:
            resolved = physical.resolve(strict=True)
            if not resolved.is_dir():
                raise ValueError(f"directory {path} conflicts with {resolved}")
            physical = resolved
    if physical == physical.parent:
        raise ValueError(f"a filesystem root cannot be an installation location: {path} -> {physical}")
    return physical


def product_marker(directory, *, source=False):
    for marker in PRODUCT_MARKERS:
        if source and marker in (".git", "AGENTS.md", "CLAUDE.md", "skills-manifest.json"):
            continue
        if entry(directory / marker) is not None:
            return directory / marker
    if directory.is_dir():
        with os.scandir(directory) as entries:
            for item in entries:
                if item.name.lower().endswith((".sln", ".csproj", ".xcodeproj", ".xcworkspace")):
                    return directory / item.name
    return None


def outside_products(selected, physical, *, source=False):
    # Check both the selected namespace and the final physical namespace. A
    # collection of sibling projects has no marker of its own.
    seen = set()
    for path in (physical, absolute(selected)):
        for directory in (path, *path.parents):
            identity = directory.resolve()
            if identity in seen:
                continue
            seen.add(identity)
            marker = product_marker(directory, source=source and identity == physical)
            if marker:
                raise ValueError(f"{selected} resolves to {physical}, inside product {directory} ({marker})")


def disjoint(first, second):
    if first.is_relative_to(second) or second.is_relative_to(first):
        raise ValueError(f"installation locations overlap: {first} and {second}")


def plain_file(path):
    info = entry(path)
    if info is not None and (not stat.S_ISREG(info.st_mode) or redirected(info) or info.st_nlink != 1):
        raise ValueError(f"expected a private regular file at {path}; conflicting target {path.resolve()}")


def contained(path, root):
    # 'root' is already physical. No child may redirect the intended write,
    # even to a different area of the same product or personal directory.
    if path.resolve() != path:
        raise ValueError(f"selected location {root} redirects {path} to {path.resolve()}")


def git(root, *args):
    command = ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C", str(root), *args]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        detail = os.fsdecode(result.stderr).strip() or "Git could not verify " + args[0]
        raise ValueError(f"{root}: {detail}")
    return os.fsdecode(result.stdout)


def verify_source(root, revision, allowed_retired):
    metadata = root / ".git"
    info = entry(metadata)
    if info is None or not stat.S_ISDIR(info.st_mode) or redirected(info):
        raise ValueError(f"{root} needs a standalone clone with its own Git directory at {metadata}")
    for option, expected in (("--show-toplevel", root), ("--absolute-git-dir", metadata),
                             ("--git-common-dir", metadata)):
        actual = Path(git(root, "rev-parse", "--path-format=absolute", option).strip()).resolve(strict=True)
        if actual != expected:
            raise ValueError(f"Git location for {root} is {actual}; expected {expected}")

    # A redirected refs, logs or index path would let fetch/merge write outside
    # this checkout. Local clones legitimately share immutable object files.
    for directory, children, files in os.walk(metadata, onerror=raise_oserror):
        for name in children + files:
            path = Path(directory) / name
            if redirected(path.lstat()):
                raise ValueError(f"Git metadata at {path} redirects to {path.resolve()}")
    for name in ("commondir", "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD",
                 "rebase-apply", "rebase-merge", "index.lock", "objects/info/alternates"):
        if entry(metadata / name) is not None:
            raise ValueError(f"cannot verify independent, idle checkout {root} with {metadata / name}")

    origin = git(root, "config", "--local", "--get-all", "remote.origin.url").strip()
    if not ORIGIN.fullmatch(origin):
        raise ValueError(f"{root} origin {origin!r} is not the expected SDD repository")
    head = git(root, "rev-parse", "--verify", "HEAD^{commit}").strip()
    if revision is not None:
        if head != revision:
            raise ValueError(f"{root} is at {head}; expected {revision}")
    elif not git(root, "for-each-ref", "--count=1", "--format=%(refname)", "--contains", head,
                 "refs/remotes/origin").strip():
        raise ValueError(f"{root} revision {head} is absent from local origin history")

    tracked = {}
    for record in git(root, "ls-files", "-v", "-z").split("\0"):
        if record:
            flag, name = record.split(" ", 1)
            if flag != "H":
                raise ValueError(f"cannot verify complete checkout {root}; hidden or incomplete index entry {root / name}")
            tracked[name] = True
    for name in REQUIRED:
        if name not in tracked or not (root / name).is_file():
            raise ValueError(f"incomplete SDD checkout {root}: missing {root / name}")
    dirty = git(root, "status", "--porcelain=v1", "-z", "--untracked-files=no")
    if dirty:
        raise ValueError(f"Local changes exist in {root}: {root / dirty[3:].partition(chr(0))[0]}")
    # No exclusion rules: a product's ignored .env or untracked source counts.
    for name in git(root, "ls-files", "--others", "-z").split("\0"):
        if not name:
            continue
        extra = root / name
        if any(extra.is_relative_to(path) for path in allowed_retired):
            continue
        if extra.name == ".DS_Store" or (extra.parent.name == "__pycache__" and extra.suffix == ".pyc"):
            info = entry(extra)
            if info and stat.S_ISREG(info.st_mode) and not redirected(info):
                continue
        raise ValueError(f"Local changes exist in {root}: unowned content at {extra}")


def raise_oserror(error):
    raise error


def check_evidence(home, project):
    for name in ("bindings", "stores", "pending-setup", "pending-setup/history", "durable",
                 "default.json", "default-policy.json", "setup-status.json"):
        contained(home / name, home)
    for name in ("bindings", "stores", "pending-setup", "pending-setup/history", "durable"):
        physical_directory(home / name)
    # The lock is opened in-place. Published JSON files use atomic replacement.
    import hashlib
    key = hashlib.sha256(str(project or "installation-default").encode()).hexdigest()
    plain_file(home / "pending-setup" / (key + ".lock"))
    contained(home / "pending-setup/history" / key, home)


def check_locations(*, fresh=None, source=None, registration=(), personal_root=(),
                    source_root=(), cleanup_dir=(), revision=None, evidence_home=None,
                    evidence_project=None):
    if (fresh is None) == (source is None):
        raise ValueError("select exactly one checkout location")
    for variable in GIT_PATH_ENV:
        if variable in os.environ:
            raise ValueError(f"Git path override {variable}={os.environ[variable]!r} conflicts with checkout {fresh or source}")
    selected = source if source is not None else fresh
    checkout = physical_directory(selected)
    outside_products(selected, checkout, source=source is not None)
    if fresh is not None and checkout.exists():
        first = next(checkout.iterdir(), None)
        if first:
            raise ValueError(f"fresh destination {selected} resolves to {checkout} and contains {first}")

    source_retirements = []
    for value in source_root:
        folder = physical_directory(value)
        if folder not in {checkout / name for name in SOURCE_ROOTS}:
            raise ValueError(f"source cleanup path {value} resolves to {folder} outside its intended location in {checkout}")
        # A redirect to another permitted root is also ambiguous.
        expected = checkout / absolute(value).relative_to(absolute(selected))
        if expected != folder:
            raise ValueError(f"source cleanup path {expected} redirects to {folder}")
        source_retirements.extend(folder / name for name in RETIRED)
    if source is not None:
        verify_source(checkout, revision, source_retirements)

    registrations = []
    for value in registration:
        folder = physical_directory(value)
        outside_products(value, folder)
        disjoint(folder, checkout)
        plain_file(folder / ".codex-sdd-skills-source")
        registrations.append(folder)
    for value in personal_root:
        folder = physical_directory(value)
        outside_products(value, folder)
        disjoint(folder, checkout)
    for value in cleanup_dir:
        # Only an explicit recovery operation can supply these exact skill roots.
        folder = physical_directory(value)
        if folder.name.casefold() != "skills":
            raise ValueError(f"expected an explicitly selected legacy skills directory: {value} -> {folder}")
        if folder.is_relative_to(checkout) or checkout.is_relative_to(folder):
            raise ValueError(f"explicit legacy cleanup {folder} overlaps checkout {checkout}")

    project = physical_directory(evidence_project) if evidence_project is not None else None
    if project:
        for path in [checkout, *registrations]:
            disjoint(path, project)
        contained(project / "forge/evidence-policy.json", project)
    if evidence_home is not None:
        home = physical_directory(evidence_home)
        outside_products(evidence_home, home)
        for path in [checkout, *registrations]:
            disjoint(path, home)
        if project:
            disjoint(home, project)
        check_evidence(home, project)
    return checkout


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--fresh")
    group.add_argument("--source")
    parser.add_argument("--revision")
    for flag in ("registration", "personal-root", "source-root", "cleanup-dir"):
        parser.add_argument("--" + flag, action="append", default=[])
    parser.add_argument("--evidence-home")
    parser.add_argument("--evidence-project")
    args = parser.parse_args(argv)
    try:
        print(check_locations(**vars(args)))
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Installation preflight failed: {error}. See {RECOVERY}", file=sys.stderr)
        return 1
    return 0


OFFICIAL_URL = "https://github.com/Ingwarski/sdd-pipeline-skills.git"


def registration_roots(agent, codex_dir=None, claude_dir=None):
    """Return exactly the roots that will be passed to the platform installer."""
    roots = {}
    if agent in ("both", "codex"):
        codex = codex_dir or os.environ.get("CODEX_SKILLS_DIR")
        if not codex:
            home = os.environ.get("CODEX_HOME")
            official = Path.home() / ".agents/skills"
            legacy = Path.home() / ".codex/skills"
            codex = Path(home) / "skills" if home else legacy if legacy.is_dir() and not official.is_dir() else official
        roots["codex"] = Path(codex)
    if agent in ("both", "claude"):
        claude = claude_dir or os.environ.get("CLAUDE_SKILLS_DIR")
        if not claude:
            claude = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "skills"
        roots["claude"] = Path(claude)
    return roots


def release_head(directory, channel, revision=None):
    ref = "refs/heads/" + channel
    result = git(directory, "ls-remote", "--exit-code", OFFICIAL_URL, ref).split()
    if len(result) != 2 or result[1] != ref or not re.fullmatch("[0-9a-f]{40}", result[0]):
        raise ValueError(f"cannot verify {ref} at {OFFICIAL_URL} for checkout {directory}")
    if revision is not None and revision != result[0]:
        raise ValueError(f"{directory}: expected {revision}, official {ref} is at {result[0]}")
    return result[0]


@contextmanager
def staged_release(parent, channel, expected):
    # A bare snapshot holds the selected commit without creating a worktree.
    # Prove release identity and ancestry here before fetching into a user's clone.
    with tempfile.TemporaryDirectory(prefix="sdd-release-") as temporary:
        stage = Path(temporary) / "release.git"
        git(parent, "clone", "--quiet", "--bare", "--single-branch", "--branch", channel, "--", OFFICIAL_URL, str(stage))
        actual = git(stage, "rev-parse", "--verify", "HEAD").strip()
        if actual != expected:
            raise ValueError(f"{channel} moved from {expected} to {actual}; select the release again for {parent}")
        git(stage, "cat-file", "-e", expected + ":scripts/install_location.py")
        yield stage


def check_active_links(tree, revision, checkout, registrations, repair):
    manifest = json.loads(git(tree, "show", revision + ":skills-manifest.json"))
    for folder in registrations.values():
        receipt = folder / ".codex-sdd-skills-source"
        previous = None
        if repair and receipt.is_file():
            lines = receipt.read_text(encoding="utf-8-sig").splitlines()
            if lines and Path(lines[0]).is_absolute():
                previous = Path(lines[0])
        for skill in manifest["skills"]:
            name = skill["name"]
            relative = "skills/" + name
            if not re.fullmatch(r"to-[a-z0-9-]+", name) or skill["path"] != relative:
                raise ValueError(f"invalid skill path in {revision}: {skill!r}")
            link = folder / name
            info = entry(link)
            if info is None:
                continue
            if redirected(info):
                target = link.resolve()
                if target == checkout / relative or (previous and target == (previous / relative).resolve()):
                    continue
                raise ValueError(f"{link} targets {target}; expected {checkout / relative}")
            raise ValueError(f"{link} occupies the registration path for {checkout / relative}")


def advance_checkout(source, channel, revision=None, registrations=None):
    checkout = check_locations(source=source, registration=(registrations or {}).values())
    branch = git(checkout, "symbolic-ref", "--short", "HEAD").strip()
    if branch != "main":
        raise ValueError(f"update requires main at {checkout}; current branch is {branch}")
    selected = release_head(checkout, channel, revision)
    current = git(checkout, "rev-parse", "HEAD").strip()
    if current == selected:
        git(checkout, "cat-file", "-e", selected + ":scripts/install_location.py")
        if registrations:
            check_active_links(checkout, selected, checkout, registrations, repair=True)
        return checkout
    with staged_release(checkout, channel, selected) as stage:
        try:
            git(stage, "merge-base", "--is-ancestor", current, selected)
        except ValueError as error:
            raise ValueError(f"{checkout} at {current} is ahead of GitHub or diverges from {channel} {selected}") from error
        if registrations:
            check_active_links(stage, selected, checkout, registrations, repair=True)
        check_locations(source=checkout, registration=(registrations or {}).values(), revision=current)
        tracking = "refs/remotes/origin/" + channel
        git(checkout, "fetch", "--quiet", "--no-tags", "--no-recurse-submodules",
            "--no-write-fetch-head", str(stage), f"refs/heads/{channel}:{tracking}")
        git(checkout, "merge", "--ff-only", "--no-edit", selected)
    return checkout


def install_release(opts):
    if sys.version_info < (3, 12):
        raise ValueError("Python 3.12+ is required")
    if not re.fullmatch("[0-9a-f]{40}", opts.revision):
        raise ValueError("select the full commit SHA from the official channel")
    if len(opts.destination) != 1:
        raise ValueError("select one absolute --destination; received " + ", ".join(opts.destination))
    selected = opts.destination[0]
    registrations = registration_roots(opts.agent, opts.codex_dir, opts.claude_dir)
    options = {"registration": registrations.values()}
    if opts.operation == "bootstrap":
        checkout = check_locations(fresh=selected, **options)
        parent = checkout.parent
        while not parent.exists():
            parent = parent.parent
        release_head(parent, opts.channel, opts.revision)
        with staged_release(parent, opts.channel, opts.revision) as stage:
            check_active_links(stage, opts.revision, checkout, registrations, repair=False)
            # Resolve the original spelling again, immediately before the first write.
            if check_locations(fresh=selected, **options) != checkout:
                raise ValueError(f"selected path {selected} moved since validation of {checkout}")
            git(parent, "clone", "--quiet", "--no-local", "--single-branch", "--branch", opts.channel,
                "--", str(stage), str(checkout))
            git(checkout, "remote", "set-url", "origin", OFFICIAL_URL)
            if opts.channel != "main":
                git(checkout, "branch", "-m", "main")
    else:
        checkout = advance_checkout(selected, opts.channel, opts.revision, registrations)
    check_locations(source=checkout, revision=opts.revision, **options)
    if os.name == "nt":
        command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                   str(checkout / "install.ps1"), "-" + ("All" if opts.agent == "both" else opts.agent.title())]
        for agent, folder in registrations.items():
            command.extend(["-" + agent.title() + "Dir", str(folder)])
        if opts.operation == "update":
            command.append("-Repair")
    else:
        command = ["bash", str(checkout / "install.sh"), "--" + ("all" if opts.agent == "both" else opts.agent)]
        for agent, folder in registrations.items():
            command.extend(["--" + agent + "-dir", str(folder)])
        if opts.operation == "update":
            command.append("--repair")
    return subprocess.run(command, cwd=checkout).returncode


def release_cli(argv):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("operation", choices=("advance", "bootstrap", "update"))
    parser.add_argument("--channel", choices=("stable", "main"), default="stable")
    if argv[0] == "advance":
        parser.add_argument("--source", required=True)
    else:
        parser.add_argument("--destination", action="append", required=True)
        parser.add_argument("--revision", required=True)
        parser.add_argument("--agent", choices=("both", "codex", "claude"), default="both")
        parser.add_argument("--codex-dir")
        parser.add_argument("--claude-dir")
    opts = parser.parse_args(argv)
    try:
        if opts.operation == "advance":
            advance_checkout(opts.source, opts.channel)
            return 0
        return install_release(opts)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Installation preflight failed: {error}. See {RECOVERY}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    if sys.argv[1:2] in (["bootstrap"], ["update"], ["advance"]):
        sys.exit(release_cli(sys.argv[1:]))
    sys.exit(main())
