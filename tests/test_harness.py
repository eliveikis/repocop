"""Sanity checks for the test harness itself. Replace/extend as real modules land."""

from pathlib import Path

import repocop
from tests.conftest import HostLayout, run_git


def test_package_imports() -> None:
    assert repocop.__version__


def test_primary_checkout_fixture(primary_checkout: Path, host: HostLayout) -> None:
    assert (primary_checkout / ".git").exists()
    assert run_git("rev-parse", "--abbrev-ref", "HEAD", cwd=primary_checkout) == "main"
    assert primary_checkout.is_relative_to(host.repos_root)
    assert not host.worktrees_root.is_relative_to(host.repos_root)
