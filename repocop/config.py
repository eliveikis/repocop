"""Host configuration. This is the only module that reads config files or the environment.

The config file is the first one found of:
  1. $REPOCOP_CONFIG (must exist)
  2. ./repocop.yaml
  3. $XDG_CONFIG_HOME/repocop/config.yaml (default ~/.config/repocop/config.yaml)

Any key can then be overridden with REPOCOP_<KEY> (e.g. REPOCOP_PORT=9000).
`~` and $VARS are expanded in paths. Relative paths in a config file are resolved against that
file's directory. Relative paths from env vars are resolved against the working directory.

Nothing is read under the product's former name. A config file or default data folder that only
exists under it, or an environment variable named with it, is refused with how to carry it over,
so it's never left behind without a word, and nothing is moved on the developer's behalf.
"""

from __future__ import annotations

import logging
import os
import shlex
from pathlib import Path
from typing import Any
from urllib.parse import quote

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from repocop.errors import ConfigError

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
NAME = "repocop"
ENV_PREFIX = "REPOCOP_"
CONFIG_ENV = "REPOCOP_CONFIG"
LOCAL_CONFIG_NAME = f"{NAME}.yaml"
FORMER_NAME = "coordinator"  # the product's name before RepoCop
FORMER_ENV_PREFIX = f"{FORMER_NAME.upper()}_"
PATH_FIELDS = ("repos_root", "worktrees_root", "database_path", "logs_dir", "template_dir")
# Keys that no longer exist, and what took their place. A config naming one is refused.
_CHANGES_DIR = (
    "changes_dir, the folder holding a repository's todo/ and archive/ (default specs/changes)"
)
RETIRED = {"requirement_path_pattern": _CHANGES_DIR, "requirements_dir": _CHANGES_DIR}
# Keys for the coding agents RepoCop used to run, which nothing replaced (ADR-039).
AGENT_KEYS = ("claude_bin", "anthropic_api_key", "review_model", "review_effort")


def _expand(value: str) -> Path:
    return Path(os.path.expandvars(value)).expanduser()


def _data_base() -> Path:
    return _expand(os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share"))


def _config_base() -> Path:
    return _expand(os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config"))


def _data_home() -> Path:
    return _data_base() / NAME


class Settings(BaseModel):
    """Validated host configuration. Immutable once loaded."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)

    repos_root: Path = Path("~/code")
    worktrees_root: Path = Path("~/agent-worktrees")
    database_path: Path = Field(default_factory=lambda: _data_home() / f"{NAME}.db")
    logs_dir: Path = Field(default_factory=lambda: _data_home() / "logs")
    host: str = Field(default="127.0.0.1", min_length=1)
    port: int = Field(default=8765, ge=1, le=65535)
    template_dir: Path = PROJECT_ROOT / "templates" / "default-repo"
    # The folder of a newly registered repository that holds its changes, relative to it: todo/
    # holds those still to deliver, one Markdown file each, and archive/ the delivered ones.
    changes_dir: str = "specs/changes"
    # A URL template containing {path}, e.g. vscode://file{path}/. Unset: pages show no editor link.
    editor_url: str | None = None

    @field_validator("editor_url", mode="before")
    @classmethod
    def _blank_means_none(cls, value: Any) -> Any:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("editor_url")
    @classmethod
    def _check_editor_url(cls, value: str | None) -> str | None:
        if value is not None and value.count("{path}") != 1:
            raise ValueError("must contain {path} exactly once")
        return value

    def editor_link(self, path: Path, *, file: bool = False) -> str | None:
        """The URL that opens `path` in the configured editor, or None when none is configured.

        For a `file`, a slash right after `{path}` is left out, since it marks a folder.
        """
        if self.editor_url is None:
            return None
        template = self.editor_url.replace("{path}/", "{path}") if file else self.editor_url
        return template.replace("{path}", quote(str(path), safe="/"))

    @field_validator(*PATH_FIELDS, mode="before")
    @classmethod
    def _expand_path(cls, value: Any) -> Any:
        if isinstance(value, str | Path):
            if not str(value).strip():
                raise ValueError("must not be empty")
            return _expand(str(value)).resolve()
        return value

    @model_validator(mode="before")
    @classmethod
    def _refuse_retired_keys(cls, values: Any) -> Any:
        if isinstance(values, dict):
            for key, replacement in RETIRED.items():
                if key in values:
                    raise ValueError(f"{key} is replaced by {replacement}")
            for key in AGENT_KEYS:
                if key in values:
                    raise ValueError(
                        f"{key} is no longer used: RepoCop runs no coding agents. Remove it."
                    )
        return values

    @field_validator("changes_dir")
    @classmethod
    def _check_changes_dir(cls, value: str) -> str:
        folder = Path(value)
        if not value.strip() or folder.is_absolute() or ".." in folder.parts:
            raise ValueError("must be a folder inside the repository, relative to it (no '..')")
        return value

    @model_validator(mode="after")
    def _check_roots_disjoint(self) -> Settings:
        repos, worktrees = self.repos_root, self.worktrees_root
        if worktrees.is_relative_to(repos) or repos.is_relative_to(worktrees):
            raise ValueError(
                f"worktrees_root ({worktrees}) and repos_root ({repos}) must not overlap: "
                "RepoCop worktrees must stay outside human-owned checkouts"
            )
        return self


def load_settings() -> Settings:
    """Load settings from the config file (if any) and REPOCOP_* env vars."""
    config_file = find_config_file()
    values: dict[str, Any] = {}
    if config_file is not None:
        values.update(_read_config_file(config_file))
        logger.info("Loaded configuration from %s", config_file)
    values.update(_env_overrides())
    if steps := _carry_overs(config_file, values):
        raise ConfigError(
            f"RepoCop no longer reads anything under its former name, {FORMER_NAME}. "
            "Carry it over, then start again: " + "; ".join(steps)
        )
    try:
        return Settings.model_validate(values)
    except ValidationError as exc:
        raise ConfigError(_describe(exc, config_file)) from exc


def find_config_file() -> Path | None:
    explicit = os.environ.get(CONFIG_ENV)
    if explicit:
        path = _expand(explicit)
        if not path.is_file():
            raise ConfigError(f"{CONFIG_ENV} points to {path}, which is not a file")
        return path.resolve()
    local = Path.cwd() / LOCAL_CONFIG_NAME
    if local.is_file():
        return local.resolve()
    user = _config_base() / NAME / "config.yaml"
    return user.resolve() if user.is_file() else None


def _carry_overs(config_file: Path | None, values: dict[str, Any]) -> list[str]:
    """What still goes by the former name and would be ignored, each with how to carry it over.
    Only the default places count: a config file when there's none at the new ones, and the data
    folder when its place isn't configured and there's no new one."""
    steps = [
        f"rename the environment variable {key} to {key.replace(FORMER_ENV_PREFIX, ENV_PREFIX, 1)}"
        for key in sorted(os.environ)
        if key.startswith(FORMER_ENV_PREFIX)
    ]
    if config_file is None:
        former_files = {
            Path.cwd() / f"{FORMER_NAME}.yaml": Path.cwd() / LOCAL_CONFIG_NAME,
            _config_base() / FORMER_NAME / "config.yaml": _config_base() / NAME / "config.yaml",
        }
        steps += [
            f"move the config file: {_moving(former, new)}"
            for former, new in former_files.items()
            if former.is_file()
        ]
    former_data, new_data = _data_base() / FORMER_NAME, _data_home()
    configured = {"database_path", "logs_dir"} & values.keys()
    if former_data.is_dir() and not new_data.exists() and not configured:
        renames = [
            f"mv {_q(new_data / f'{FORMER_NAME}.db{suffix}')} {_q(new_data / f'{NAME}.db{suffix}')}"
            for suffix in ("", "-wal", "-shm")
            if (former_data / f"{FORMER_NAME}.db{suffix}").is_file()
        ]
        command = " && ".join([f"mv {_q(former_data)} {_q(new_data)}", *renames])
        steps.append(f"move the data folder: {command}")
    return steps


def _moving(former: Path, new: Path) -> str:
    """The shell command that moves `former` to `new`, making its folder first."""
    return f"mkdir -p {_q(new.parent)} && mv {_q(former)} {_q(new)}"


def _q(path: Path) -> str:
    return shlex.quote(str(path))


def _read_config_file(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"cannot read config file {path}: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"config file {path} must be a mapping of keys to values")
    for key in PATH_FIELDS:
        value = data.get(key)
        if isinstance(value, str) and value.strip() and not _expand(value).is_absolute():
            data[key] = str(path.parent / _expand(value))
    return data


def _env_overrides() -> dict[str, str]:
    overrides: dict[str, str] = {}
    for name in (*Settings.model_fields, *RETIRED, *AGENT_KEYS):
        value = os.environ.get(ENV_PREFIX + name.upper())
        if value is not None:
            overrides[name] = value
    return overrides


def _describe(exc: ValidationError, config_file: Path | None) -> str:
    source = f"{config_file} and " if config_file else ""
    problems = "; ".join(
        f"{'.'.join(str(part) for part in err['loc']) or 'settings'}: {err['msg']}"
        for err in exc.errors()
    )
    return f"invalid configuration (from {source}{ENV_PREFIX}* env vars / defaults): {problems}"
