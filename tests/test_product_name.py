"""The product goes by one name, RepoCop."""

import subprocess

from repocop.config import FORMER_NAME, PROJECT_ROOT

# Where the former name stays: records of what was decided and changed, which are never
# rewritten, and the checks that refuse to start while something still goes by it.
KEEP_THE_FORMER_NAME = ("specs/decisions/", "specs/changes/", "repocop/config.py")


def test_only_records_and_the_checks_for_it_say_the_former_name() -> None:
    listed = subprocess.run(
        ["git", "ls-files", "-z"], cwd=PROJECT_ROOT, capture_output=True, check=True
    ).stdout.decode()
    saying_it = [
        path
        for path in listed.split("\0")
        if path
        and not path.startswith(KEEP_THE_FORMER_NAME)
        and (FORMER_NAME in path.lower() or FORMER_NAME in _text(path).lower())
    ]
    assert saying_it == []


def _text(path: str) -> str:
    file = PROJECT_ROOT / path
    return file.read_bytes().decode("utf-8", "replace") if file.is_file() else ""
