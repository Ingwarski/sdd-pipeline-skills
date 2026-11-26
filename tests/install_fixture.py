"""Build a disposable, committed SDD source from the working tree for installer tests."""
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
OFFICIAL = "https://github.com/Ingwarski/sdd-pipeline-skills.git"


def git(checkout, *arguments):
    return subprocess.run(["git", "-C", str(checkout), *arguments], check=True,
                          stdout=subprocess.PIPE).stdout


def publish_snapshot(checkout):
    """Make edited inputs represent one published fixture revision."""
    git(checkout, "add", "-A")
    git(checkout, "-c", "user.name=SDD tests", "-c", "user.email=sdd-tests@example.invalid",
        "commit", "--allow-empty", "--quiet", "-m", "Installer fixture revision")
    for channel in ("main", "stable"):
        git(checkout, "update-ref", "refs/remotes/origin/" + channel, "HEAD")


def create_checkout(checkout):
    checkout.mkdir(parents=True)
    names = git(ROOT, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
    for name in filter(None, os.fsdecode(names).split("\0")):
        source = ROOT / name
        if source.is_file():
            target = checkout / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    git(checkout, "init", "--quiet", "--initial-branch=main")
    git(checkout, "remote", "add", "origin", OFFICIAL)
    publish_snapshot(checkout)


if __name__ == "__main__":
    checkout = Path(sys.argv[2])
    {"create": create_checkout, "publish": publish_snapshot}[sys.argv[1]](checkout)
