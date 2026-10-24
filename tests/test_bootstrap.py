"""Bootstrap: the repo template, and how a repository's branch compares with it."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from repocop.services import bootstrap
from repocop.services.bootstrap import BootstrapError, FileState, Kind, NoCommitsError
from tests.conftest import run_git, write_template

MARKDOWN = "<!-- managed by template -->"
COMMENT = "# managed by template"

# ---------------------------------------------------------------- sync plan


def commit_everything(checkout: Path, message: str = "commit") -> None:
    run_git("add", "-A", cwd=checkout)
    run_git("commit", "-qm", message, cwd=checkout)


def states(plan: bootstrap.SyncPlan) -> dict[str, bootstrap.FileState]:
    return {file.path: file.state for file in plan.files}


def test_sync_plan_marks_every_template_file_missing_from_a_fresh_repository(
    template_dir: Path, primary_checkout: Path
) -> None:
    plan = bootstrap.sync_plan(template_dir, primary_checkout, "main", "sample")
    assert states(plan) == {  # a folder kept only by .gitkeep isn't part of it
        ".claude/skills/demo/run.sh": bootstrap.FileState.MISSING,
        "CLAUDE.md": bootstrap.FileState.MISSING,
        "logo.bin": bootstrap.FileState.MISSING,
    }


def test_sync_plan_reads_the_branch_with_two_git_calls(
    template_dir: Path, primary_checkout: Path, git_calls: Callable[[], list[list[str]]]
) -> None:
    for n in range(20):
        (template_dir / f"rule-{n}.md").write_text(f"rule {n}\n")
        (primary_checkout / f"retired-{n}.md").write_text(f"{MARKDOWN}\n# Retired {n}\n")
    commit_everything(primary_checkout)
    before = len(git_calls())
    plan = bootstrap.sync_plan(template_dir, primary_checkout, "main", "sample")
    assert len(plan.retired) == 20
    assert len(git_calls()) - before == 2


def test_sync_plan_refuses_a_repository_with_no_commits(template_dir: Path, tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    run_git("init", "-q", "-b", "main", str(empty), cwd=tmp_path)
    with pytest.raises(
        NoCommitsError, match=r"sample has no commits yet\. Make a first commit on main"
    ):
        bootstrap.sync_plan(template_dir, empty, "main", "sample")


def test_sync_plan_refuses_a_branch_that_is_not_there(
    template_dir: Path, primary_checkout: Path
) -> None:
    with pytest.raises(BootstrapError, match="couldn't search gone") as refused:
        bootstrap.sync_plan(template_dir, primary_checkout, "gone", "sample")
    assert not isinstance(refused.value, NoCommitsError)


def test_sync_plan_refuses_a_missing_template_directory(
    tmp_path: Path, primary_checkout: Path
) -> None:
    with pytest.raises(BootstrapError, match="template"):
        bootstrap.sync_plan(tmp_path / "no-template", primary_checkout, "main", "sample")


def test_sync_plan_finds_a_repository_with_the_template_committed_up_to_date(
    template_dir: Path, primary_checkout: Path
) -> None:
    write_template(template_dir, primary_checkout)
    commit_everything(primary_checkout)
    plan = bootstrap.sync_plan(template_dir, primary_checkout, "main", "sample")
    assert set(states(plan).values()) == {bootstrap.FileState.IDENTICAL}
    assert plan.up_to_date


def test_sync_plan_compares_with_the_branch_not_the_working_tree(
    template_dir: Path, primary_checkout: Path
) -> None:
    write_template(template_dir, primary_checkout)
    commit_everything(primary_checkout)
    (primary_checkout / "CLAUDE.md").write_text("# edited but not committed\n")
    assert bootstrap.sync_plan(template_dir, primary_checkout, "main", "sample").up_to_date


def test_sync_plan_shows_a_diff_for_a_file_that_differs(
    template_dir: Path, primary_checkout: Path
) -> None:
    write_template(template_dir, primary_checkout)
    (primary_checkout / "CLAUDE.md").write_text("# Mine\n")
    commit_everything(primary_checkout)
    plan = bootstrap.sync_plan(template_dir, primary_checkout, "main", "sample")
    claude_md = next(file for file in plan.files if file.path == "CLAUDE.md")
    assert claude_md.state is bootstrap.FileState.DIFFERS
    assert "--- a/CLAUDE.md" in claude_md.diff and "+++ b/CLAUDE.md" in claude_md.diff
    assert "-# Mine" in claude_md.diff and "+# sample" in claude_md.diff
    assert [file.path for file in plan.differing] == ["CLAUDE.md"]
    assert not plan.up_to_date


def test_sync_plan_notes_a_binary_file_that_differs(
    template_dir: Path, primary_checkout: Path
) -> None:
    write_template(template_dir, primary_checkout)
    (primary_checkout / "logo.bin").write_bytes(b"\x00\xffother")
    commit_everything(primary_checkout)
    plan = bootstrap.sync_plan(template_dir, primary_checkout, "main", "sample")
    logo = next(file for file in plan.files if file.path == "logo.bin")
    assert (logo.state, logo.diff) == (bootstrap.FileState.DIFFERS, "Binary files differ")


def test_sync_plan_refuses_a_folder_where_the_template_has_a_file(
    template_dir: Path, primary_checkout: Path
) -> None:
    (primary_checkout / "CLAUDE.md").mkdir()
    (primary_checkout / "CLAUDE.md" / "notes.md").write_text("notes\n")
    commit_everything(primary_checkout)
    with pytest.raises(BootstrapError, match="folder"):
        bootstrap.sync_plan(template_dir, primary_checkout, "main", "sample")


# ---------------------------------------------------------------- files the template retired


def test_sync_plan_offers_to_delete_a_marked_file_the_template_no_longer_ships(
    template_dir: Path, primary_checkout: Path
) -> None:
    write_template(template_dir, primary_checkout)
    rules = primary_checkout / ".claude" / "rules"
    rules.mkdir(parents=True)
    (rules / "design.md").write_text(f"{MARKDOWN}\n# Design\n\nEdited here.\n")
    (rules / "scoped.md").write_text(f'---\npaths:\n  - "src/**"\n---\n{MARKDOWN}\n# Scoped\n')
    (rules / "windows.md").write_bytes(f"---\r\npaths: []\r\n---\r\n{MARKDOWN}\r\n# W\r\n".encode())
    (primary_checkout / "old.sh").write_text(f"#!/bin/sh\n{COMMENT}\necho old\n")
    (primary_checkout / ".ignored").write_text(f"{COMMENT}\nbuild/\n")
    commit_everything(primary_checkout)
    plan = bootstrap.sync_plan(template_dir, primary_checkout, "main", "sample")
    retired = [
        ".claude/rules/design.md",
        ".claude/rules/scoped.md",
        ".claude/rules/windows.md",  # line endings don't exempt it
        ".ignored",
        "old.sh",
    ]
    assert [file.path for file in plan.retired] == retired
    assert {states(plan)[path] for path in retired} == {FileState.RETIRED}
    assert not plan.up_to_date
    design = next(file for file in plan.files if file.path == ".claude/rules/design.md")
    assert f"-{MARKDOWN}\n-# Design\n-\n-Edited here.\n" in design.diff


@pytest.mark.parametrize(
    "text",
    [
        "# Notes\n",
        f"Quote it: `{MARKDOWN}`\n",
        f"# Notes\n{MARKDOWN}\n",
        f"\n{MARKDOWN}\n",
        f"```\n{MARKDOWN}\n```\n",
        f"#!/bin/sh\necho hi\n{COMMENT}\n",
        f"---\ntitle: notes\n---\n\n{MARKDOWN}\n",
        f"---\ntitle: notes\n{MARKDOWN}\n",
        f"#{COMMENT}\n",
        f"{MARKDOWN} and more\n",
    ],
)
def test_sync_plan_never_offers_to_delete_a_file_without_the_marker_first(
    template_dir: Path, primary_checkout: Path, text: str
) -> None:
    write_template(template_dir, primary_checkout)
    (primary_checkout / ".claude" / "rules").mkdir(parents=True)
    (primary_checkout / ".claude" / "rules" / "design.md").write_text(text)
    commit_everything(primary_checkout)
    plan = bootstrap.sync_plan(template_dir, primary_checkout, "main", "sample")
    assert ".claude/rules/design.md" not in states(plan)
    assert plan.up_to_date


def test_sync_plan_compares_a_marked_file_the_template_still_ships(
    template_dir: Path, primary_checkout: Path
) -> None:
    write_template(template_dir, primary_checkout)
    (primary_checkout / "CLAUDE.md").write_text(f"{MARKDOWN}\n# Mine\n")
    commit_everything(primary_checkout)
    plan = bootstrap.sync_plan(template_dir, primary_checkout, "main", "sample")
    assert states(plan)["CLAUDE.md"] is FileState.DIFFERS
    assert plan.retired == ()


def test_rendered_gives_a_template_file_as_it_would_be_written(template_dir: Path) -> None:
    assert bootstrap.rendered(template_dir, "CLAUDE.md", "crm-api") == b"# crm-api\n"


# ---------------------------------------------------------------- file kinds

SETTINGS = ".claude/settings.json"


def write_json(path: Path, data: object, indent: int = 2) -> None:
    path.write_text(json.dumps(data, indent=indent) + "\n")


def test_kinds_follow_the_manifest_and_default_to_managed(declared_kinds: Path) -> None:
    assert bootstrap.kinds(declared_kinds) == {
        SETTINGS: Kind.MERGED,
        ".claude/skills/demo/run.sh": Kind.MANAGED,
        "CLAUDE.md": Kind.STARTER,
        "logo.bin": Kind.MANAGED,
    }


def test_kinds_without_a_manifest_are_all_managed(template_dir: Path) -> None:
    assert set(bootstrap.kinds(template_dir).values()) == {Kind.MANAGED}


def test_sync_plan_lists_files_of_every_kind_but_never_the_manifest(
    declared_kinds: Path, primary_checkout: Path
) -> None:
    listed = states(bootstrap.sync_plan(declared_kinds, primary_checkout, "main", "sample"))
    assert {"CLAUDE.md", SETTINGS} <= set(listed)
    assert bootstrap.MANIFEST not in listed


@pytest.mark.parametrize(
    ("manifest", "reason"),
    [
        ("starter = [", "valid TOML"),
        ('starters = ["CLAUDE.md"]', "unknown key"),
        ('starter = "CLAUDE.md"', "list of paths"),
        ('starter = ["nope.md"]', "isn't a file in the template"),
        ('starter = ["specs/changes/todo"]', "isn't a file in the template"),
        ('starter = ["CLAUDE.md"]\nmerged = ["CLAUDE.md"]', "more than once"),
        ('merged = ["logo.bin"]', "JSON"),
    ],
)
def test_an_invalid_manifest_stops_sync(
    template_dir: Path, primary_checkout: Path, manifest: str, reason: str
) -> None:
    (template_dir / bootstrap.MANIFEST).write_text(manifest + "\n")
    with pytest.raises(BootstrapError, match=reason):
        bootstrap.sync_plan(template_dir, primary_checkout, "main", "sample")


def test_a_merged_template_file_must_be_a_json_object(
    template_dir: Path, primary_checkout: Path
) -> None:
    (template_dir / "list.json").write_text("[1, 2]\n")
    (template_dir / bootstrap.MANIFEST).write_text('merged = ["list.json"]\n')
    with pytest.raises(BootstrapError, match="JSON object"):
        bootstrap.sync_plan(template_dir, primary_checkout, "main", "sample")


def test_sync_plan_offers_a_missing_starter_file_for_creation(
    declared_kinds: Path, primary_checkout: Path
) -> None:
    plan = bootstrap.sync_plan(declared_kinds, primary_checkout, "main", "sample")
    assert states(plan)["CLAUDE.md"] is FileState.MISSING


def test_sync_plan_leaves_a_starter_file_the_repository_has_as_its_own(
    declared_kinds: Path, primary_checkout: Path
) -> None:
    write_template(declared_kinds, primary_checkout)
    (primary_checkout / "CLAUDE.md").write_text("# Mine\n")
    commit_everything(primary_checkout)
    plan = bootstrap.sync_plan(declared_kinds, primary_checkout, "main", "sample")
    claude_md = next(file for file in plan.files if file.path == "CLAUDE.md")
    assert (claude_md.state, claude_md.diff) == (FileState.OWNED, "")
    assert plan.differing == ()
    assert plan.up_to_date


def test_sync_plan_offers_to_merge_the_entries_a_merged_file_lacks(
    declared_kinds: Path, primary_checkout: Path
) -> None:
    write_template(declared_kinds, primary_checkout)
    write_json(primary_checkout / SETTINGS, {"permissions": {"allow": ["Bash(npm test)"]}})
    commit_everything(primary_checkout)
    plan = bootstrap.sync_plan(declared_kinds, primary_checkout, "main", "sample")
    settings = next(file for file in plan.files if file.path == SETTINGS)
    assert settings.state is FileState.BEHIND
    assert [file.path for file in plan.behind] == [SETTINGS]
    assert '+      "Bash(make check)"' in settings.diff
    assert '+  "model": "sonnet"' in settings.diff
    assert plan.differing == ()
    assert not plan.up_to_date


def test_sync_plan_offers_to_merge_a_value_a_merged_file_changed(
    declared_kinds: Path, primary_checkout: Path
) -> None:
    write_template(declared_kinds, primary_checkout)
    mine = {
        "model": "opus",
        "permissions": {"allow": ["Bash(make check)"], "ask": ["Bash(git push:*)"]},
    }
    write_json(primary_checkout / SETTINGS, mine)
    commit_everything(primary_checkout)
    plan = bootstrap.sync_plan(declared_kinds, primary_checkout, "main", "sample")
    settings = next(file for file in plan.files if file.path == SETTINGS)
    assert settings.state is FileState.BEHIND
    assert '-  "model": "opus"' in settings.diff and '+  "model": "sonnet"' in settings.diff
    assert not plan.up_to_date


def test_sync_plan_finds_a_merged_file_with_everything_the_template_says_up_to_date(
    declared_kinds: Path, primary_checkout: Path
) -> None:
    write_template(declared_kinds, primary_checkout)
    mine = {
        "model": "sonnet",
        "permissions": {
            "allow": ["Bash(make check)", "Bash(npm test)"],
            "ask": ["Bash(git push:*)"],
        },
    }
    write_json(primary_checkout / SETTINGS, mine, indent=4)
    commit_everything(primary_checkout)
    plan = bootstrap.sync_plan(declared_kinds, primary_checkout, "main", "sample")
    assert states(plan)[SETTINGS] is FileState.IDENTICAL
    assert plan.up_to_date


@pytest.mark.parametrize(
    ("content", "reason"), [("{not json\n", "not valid JSON"), ("[1]\n", "not a JSON object")]
)
def test_sync_plan_notes_a_merged_file_it_cannot_merge(
    declared_kinds: Path, primary_checkout: Path, content: str, reason: str
) -> None:
    write_template(declared_kinds, primary_checkout)
    (primary_checkout / SETTINGS).write_text(content)
    commit_everything(primary_checkout)
    plan = bootstrap.sync_plan(declared_kinds, primary_checkout, "main", "sample")
    settings = next(file for file in plan.files if file.path == SETTINGS)
    assert settings.state is FileState.UNMERGEABLE
    assert reason in settings.reason
    assert plan.behind == ()


def test_merge_takes_the_templates_values_and_keeps_the_repositorys_own_in_its_order(
    declared_kinds: Path,
) -> None:
    mine = {"model": "opus", "permissions": {"deny": ["Bash(rm:*)"], "allow": ["Bash(npm test)"]}}
    current = json.dumps(mine).encode()
    merged = json.loads(bootstrap.merge(declared_kinds, SETTINGS, "sample", current))
    assert merged == {
        "model": "sonnet",
        "permissions": {
            "deny": ["Bash(rm:*)"],
            "allow": ["Bash(npm test)", "Bash(make check)"],
            "ask": ["Bash(git push:*)"],
        },
    }
    assert list(merged) == ["model", "permissions"]
    assert list(merged["permissions"]) == ["deny", "allow", "ask"]


def test_merge_takes_the_templates_value_where_the_types_differ(declared_kinds: Path) -> None:
    current = json.dumps({"permissions": "mine", "theme": "dark"}).encode()
    merged = json.loads(bootstrap.merge(declared_kinds, SETTINGS, "sample", current))
    assert merged == {
        "permissions": {"allow": ["Bash(make check)"], "ask": ["Bash(git push:*)"]},
        "theme": "dark",
        "model": "sonnet",
    }


def test_merge_adds_the_templates_list_items_and_keeps_the_repositorys_own(
    tmp_path: Path,
) -> None:
    (tmp_path / "fruit.json").write_text('{"fruits": ["apple", "orange"]}\n')
    (tmp_path / bootstrap.MANIFEST).write_text('merged = ["fruit.json"]\n')
    mine = b'{"fruits": ["apple", "pear"]}'
    merged = json.loads(bootstrap.merge(tmp_path, "fruit.json", "sample", mine))
    assert merged == {"fruits": ["apple", "pear", "orange"]}


def test_merge_tells_true_from_one_when_deciding_whether_anything_changed(
    tmp_path: Path,
) -> None:
    (tmp_path / "flags.json").write_text('{"flag": true, "nested": {"on": true}}\n')
    (tmp_path / bootstrap.MANIFEST).write_text('merged = ["flags.json"]\n')
    current = b'{"flag": 1, "nested": {"on": 1}}'
    merged = bootstrap.merge(tmp_path, "flags.json", "sample", current)
    assert merged != current
    assert json.loads(merged) == {"flag": True, "nested": {"on": True}}
    assert json.loads(merged)["flag"] is True and json.loads(merged)["nested"]["on"] is True


def test_merge_tells_true_from_one_in_a_list(tmp_path: Path) -> None:
    (tmp_path / "flags.json").write_text('{"flags": [true]}\n')
    (tmp_path / bootstrap.MANIFEST).write_text('merged = ["flags.json"]\n')
    merged = json.loads(bootstrap.merge(tmp_path, "flags.json", "sample", b'{"flags": [1]}'))
    assert merged == {"flags": [1, True]}


def test_merge_returns_a_file_with_everything_the_template_says_unchanged(
    declared_kinds: Path,
) -> None:
    current = (
        b'{"model":"sonnet",'
        b'"permissions":{"allow":["Bash(make check)"],"ask":["Bash(git push:*)"]}}'
    )
    assert bootstrap.merge(declared_kinds, SETTINGS, "sample", current) == current


def test_merge_writes_two_space_json_with_a_trailing_newline(declared_kinds: Path) -> None:
    merged = bootstrap.merge(declared_kinds, SETTINGS, "sample", b"{}")
    assert (
        merged
        == (
            json.dumps(
                {
                    "permissions": {"allow": ["Bash(make check)"], "ask": ["Bash(git push:*)"]},
                    "model": "sonnet",
                },
                indent=2,
            )
            + "\n"
        ).encode()
    )
