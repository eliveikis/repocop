"""Host configuration: file discovery, env overrides, expansion, and safety validation."""

import re
import shlex
from pathlib import Path

import pytest

from repocop.config import FORMER_NAME, PROJECT_ROOT, Settings, load_settings
from repocop.errors import ConfigError


def write_config(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_load_settings_defaults_without_file_or_env(tmp_path: Path) -> None:
    home = tmp_path / "home"
    settings = load_settings()
    assert settings.repos_root == home / "code"
    assert settings.worktrees_root == home / "agent-worktrees"
    assert settings.database_path == home / ".local/share/repocop/repocop.db"
    assert settings.logs_dir == home / ".local/share/repocop/logs"
    assert settings.host == "127.0.0.1"
    assert settings.port == 8765
    assert settings.claude_bin == "claude"
    assert settings.template_dir == PROJECT_ROOT / "templates" / "default-repo"
    assert settings.changes_dir == "specs/changes"


def test_load_settings_reads_explicit_config_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = write_config(tmp_path / "elsewhere" / "c.yaml", "repos_root: /srv/code\nport: 9001\n")
    monkeypatch.setenv("REPOCOP_CONFIG", str(config))
    settings = load_settings()
    assert settings.repos_root == Path("/srv/code")
    assert settings.port == 9001


def test_load_settings_explicit_config_must_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REPOCOP_CONFIG", str(tmp_path / "missing.yaml"))
    with pytest.raises(ConfigError, match=re.escape("missing.yaml")):
        load_settings()


def test_load_settings_prefers_local_file_over_user_file(tmp_path: Path) -> None:
    write_config(tmp_path / "home/.config/repocop/config.yaml", "port: 1111\n")
    write_config(tmp_path / "repocop.yaml", "port: 2222\n")
    assert load_settings().port == 2222


def test_load_settings_falls_back_to_user_file(tmp_path: Path) -> None:
    write_config(tmp_path / "home/.config/repocop/config.yaml", "port: 1111\n")
    assert load_settings().port == 1111


def test_load_settings_env_overrides_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_config(tmp_path / "repocop.yaml", "port: 2222\nhost: 127.0.0.1\n")
    monkeypatch.setenv("REPOCOP_PORT", "9000")
    monkeypatch.setenv("REPOCOP_CLAUDE_BIN", "/opt/claude/bin/claude")
    settings = load_settings()
    assert settings.port == 9000
    assert settings.claude_bin == "/opt/claude/bin/claude"


def test_load_settings_expands_tilde_and_env_vars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WORK", "/data/work")
    write_config(tmp_path / "repocop.yaml", "repos_root: ~/src\nworktrees_root: $WORK/trees\n")
    settings = load_settings()
    assert settings.repos_root == tmp_path / "home" / "src"
    assert settings.worktrees_root == Path("/data/work/trees")


def test_load_settings_resolves_relative_file_paths_against_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = write_config(tmp_path / "cfg" / "c.yaml", "template_dir: ./tpl\n")
    monkeypatch.setenv("REPOCOP_CONFIG", str(config))
    assert load_settings().template_dir == tmp_path / "cfg" / "tpl"


def test_example_config_file_is_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPOCOP_CONFIG", str(PROJECT_ROOT / "repocop.example.yaml"))
    settings = load_settings()
    assert settings.host == "127.0.0.1"


def test_example_config_file_documents_every_setting() -> None:
    text = (PROJECT_ROOT / "repocop.example.yaml").read_text(encoding="utf-8")
    listed = set(re.findall(r"^(?:# )?([a-z_]+):", text, re.MULTILINE))
    assert set(Settings.model_fields) <= listed


def test_load_settings_rejects_unknown_keys(tmp_path: Path) -> None:
    write_config(tmp_path / "repocop.yaml", "prot: 9000\n")
    with pytest.raises(ConfigError, match="prot"):
        load_settings()


@pytest.mark.parametrize("text", ["- just\n- a list\n", "port: [unclosed\n"])
def test_load_settings_rejects_malformed_file(tmp_path: Path, text: str) -> None:
    write_config(tmp_path / "repocop.yaml", text)
    with pytest.raises(ConfigError, match=re.escape("repocop.yaml")):
        load_settings()


def test_load_settings_empty_file_uses_defaults(tmp_path: Path) -> None:
    write_config(tmp_path / "repocop.yaml", "")
    assert load_settings().port == 8765


@pytest.mark.parametrize("port", ["0", "70000", "http"])
def test_load_settings_rejects_invalid_port(monkeypatch: pytest.MonkeyPatch, port: str) -> None:
    monkeypatch.setenv("REPOCOP_PORT", port)
    with pytest.raises(ConfigError, match="port"):
        load_settings()


@pytest.mark.parametrize(
    ("repos_root", "worktrees_root"),
    [
        ("/srv/code", "/srv/code"),
        ("/srv/code", "/srv/code/agent-worktrees"),
        ("/srv/trees/code", "/srv/trees"),
    ],
)
def test_settings_rejects_overlapping_roots(repos_root: str, worktrees_root: str) -> None:
    with pytest.raises(ValueError, match="must not overlap"):
        Settings(repos_root=Path(repos_root), worktrees_root=Path(worktrees_root))


def test_load_settings_reports_overlap_as_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPOCOP_REPOS_ROOT", "/srv/code")
    monkeypatch.setenv("REPOCOP_WORKTREES_ROOT", "/srv/code/trees")
    with pytest.raises(ConfigError, match="must not overlap"):
        load_settings()


def test_settings_accepts_sibling_roots() -> None:
    settings = Settings(repos_root=Path("/srv/code"), worktrees_root=Path("/srv/code-worktrees"))
    assert settings.worktrees_root == Path("/srv/code-worktrees")


@pytest.mark.parametrize("folder", ["/abs/specs", "../outside", "specs/../../outside", ""])
def test_settings_rejects_a_changes_folder_outside_the_repository(folder: str) -> None:
    with pytest.raises(ValueError, match="changes_dir"):
        Settings(changes_dir=folder)


@pytest.mark.parametrize("folder", ["docs/rfcs", "changes", "."])
def test_settings_accepts_a_changes_folder_inside_the_repository(folder: str) -> None:
    assert Settings(changes_dir=folder).changes_dir == folder


@pytest.mark.parametrize(
    "line",
    [
        "requirement_path_pattern: specs/changes/todo/req-{id}-{slug}.md",
        "requirements_dir: specs/changes/todo",
    ],
)
def test_load_settings_refuses_a_retired_key_and_names_its_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, line: str
) -> None:
    config = write_config(tmp_path / "c.yaml", f"{line}\n")
    monkeypatch.setenv("REPOCOP_CONFIG", str(config))
    with pytest.raises(ConfigError, match="replaced by changes_dir"):
        load_settings()


def test_load_settings_refuses_a_requirement_path_pattern_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REPOCOP_REQUIREMENT_PATH_PATTERN", "specs/req-{id}-{slug}.md")
    with pytest.raises(ConfigError, match="replaced by changes_dir"):
        load_settings()


@pytest.mark.parametrize("field", ["repos_root", "host", "claude_bin"])
def test_settings_rejects_empty_values(field: str) -> None:
    with pytest.raises(ValueError, match=field):
        Settings.model_validate({field: ""})


def test_settings_is_immutable(settings: Settings) -> None:
    with pytest.raises(ValueError, match="frozen"):
        settings.port = 1  # type: ignore[misc]


def test_settings_default_to_the_claude_subscription() -> None:
    assert Settings().anthropic_api_key is None


def test_settings_take_an_api_key_from_the_environment_and_never_show_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REPOCOP_ANTHROPIC_API_KEY", "sk-ant-secret-value")
    settings = load_settings()
    assert settings.anthropic_api_key is not None
    assert settings.anthropic_api_key.get_secret_value() == "sk-ant-secret-value"
    assert "sk-ant-secret-value" not in repr(settings)


def test_settings_ignore_the_plain_anthropic_api_key_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-for-other-tools")
    assert load_settings().anthropic_api_key is None


def test_settings_have_no_editor_link_by_default() -> None:
    settings = Settings()
    assert settings.editor_url is None
    assert settings.editor_link(Path("/srv/code/sample")) is None


def test_settings_name_no_review_model_unless_one_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert Settings().review_model is None
    monkeypatch.setenv("REPOCOP_REVIEW_MODEL", "  ")
    assert load_settings().review_model is None
    monkeypatch.setenv("REPOCOP_REVIEW_MODEL", "gpt-6-sol")
    assert load_settings().review_model == "gpt-6-sol"


def test_settings_review_at_high_effort_unless_another_or_none_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert Settings().review_effort == "high"
    monkeypatch.setenv("REPOCOP_REVIEW_EFFORT", "xhigh")
    assert load_settings().review_effort == "xhigh"
    monkeypatch.setenv("REPOCOP_REVIEW_EFFORT", " ")
    assert load_settings().review_effort is None


def test_settings_treat_a_blank_editor_url_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPOCOP_EDITOR_URL", "  ")
    assert load_settings().editor_url is None


def test_editor_link_puts_the_encoded_path_in_the_template() -> None:
    settings = Settings(editor_url="vscode://vscode-remote/wsl+Ubuntu{path}/")
    link = settings.editor_link(Path("/home/me/my repo/a#b?c"))
    assert link == "vscode://vscode-remote/wsl+Ubuntu/home/me/my%20repo/a%23b%3Fc/"


@pytest.mark.parametrize("value", ["vscode://file/", "vscode://file{path}{path}", "vscode://{pat}"])
def test_settings_reject_an_editor_url_without_exactly_one_path_placeholder(value: str) -> None:
    with pytest.raises(ValueError, match="editor_url"):
        Settings(editor_url=value)


def test_load_settings_reports_a_bad_editor_url_as_config_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REPOCOP_EDITOR_URL", "vscode://file/")
    with pytest.raises(ConfigError, match=r"editor_url: .*\{path\} exactly once"):
        load_settings()


# ---------------------------------------------------------------- the former name


def refusal() -> str:
    with pytest.raises(ConfigError) as refused:
        load_settings()
    return str(refused.value)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (f"{FORMER_NAME}.yaml", "repocop.yaml"),
        (f"home/.config/{FORMER_NAME}/config.yaml", "home/.config/repocop/config.yaml"),
    ],
)
def test_load_settings_refuses_a_config_file_under_the_former_name_and_says_how_to_move_it(
    tmp_path: Path, old: str, new: str
) -> None:
    former = write_config(tmp_path / old, "port: 1111\n")
    moved = tmp_path / new
    command = f"mkdir -p {shlex.quote(str(moved.parent))} && mv {shlex.quote(str(former))} "
    assert command + shlex.quote(str(moved)) in refusal()
    assert former.read_text() == "port: 1111\n" and not moved.exists()


def test_load_settings_reads_the_config_file_at_its_new_place_over_one_under_the_former_name(
    tmp_path: Path,
) -> None:
    write_config(tmp_path / f"home/.config/{FORMER_NAME}/config.yaml", "port: 1111\n")
    write_config(tmp_path / "home/.config/repocop/config.yaml", "port: 2222\n")
    assert load_settings().port == 2222


def test_load_settings_refuses_the_data_folder_under_the_former_name_and_says_how_to_move_it(
    tmp_path: Path,
) -> None:
    former = tmp_path / "home/.local/share" / FORMER_NAME
    (former / "logs").mkdir(parents=True)
    (former / f"{FORMER_NAME}.db").write_text("the database")
    moved = tmp_path / "home/.local/share/repocop"
    message = refusal()
    assert f"mv {shlex.quote(str(former))} {shlex.quote(str(moved))}" in message
    old_db, new_db = moved / f"{FORMER_NAME}.db", moved / "repocop.db"
    assert f"mv {shlex.quote(str(old_db))} {shlex.quote(str(new_db))}" in message
    assert (former / f"{FORMER_NAME}.db").read_text() == "the database" and not moved.exists()


@pytest.mark.parametrize("setting", ["database_path", "logs_dir"])
def test_load_settings_leaves_the_former_data_folder_alone_when_its_place_is_configured(
    tmp_path: Path, setting: str
) -> None:
    (tmp_path / "home/.local/share" / FORMER_NAME).mkdir(parents=True)
    write_config(tmp_path / "repocop.yaml", f"{setting}: {tmp_path / 'state' / 'x'}\n")
    load_settings()


def test_load_settings_leaves_the_former_data_folder_alone_once_the_new_one_exists(
    tmp_path: Path,
) -> None:
    (tmp_path / "home/.local/share" / FORMER_NAME).mkdir(parents=True)
    (tmp_path / "home/.local/share/repocop").mkdir(parents=True)
    load_settings()


@pytest.mark.parametrize("key", ["PORT", "CONFIG"])
def test_load_settings_refuses_an_environment_variable_under_the_former_name(
    monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    monkeypatch.setenv(f"{FORMER_NAME.upper()}_{key}", "9000")
    assert f"{FORMER_NAME.upper()}_{key} to REPOCOP_{key}" in refusal()
