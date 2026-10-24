"""Module boundaries, checked from source so a violation fails `make check`.

Backs `.claude/rules/safety.md` (only the process wrappers launch processes),
`.claude/rules/python.md` (dependencies point one way; only config reads the environment) and
`.claude/rules/agents.md` (what is specific to one agent stays in that agent's module).
"""

import ast
import re
from pathlib import Path

import repocop

PACKAGE_DIR = Path(repocop.__file__).resolve().parent
PROCESS_WRAPPERS = frozenset(
    {
        "repocop.services.git",
        "repocop.services.claude",
        "repocop.services.codex",
        "repocop.services.github",
    }
)
ENV_READERS = PROCESS_WRAPPERS | {"repocop.config"}  # wrappers pass env to child processes
LOWER_LAYERS = (
    "repocop.services",
    "repocop.db",
    "repocop.config",
    "repocop.errors",
)
WEB_LAYER = ("fastapi", "starlette", "repocop.main", "repocop.routes")
PROCESS_MODULES = ("subprocess", "pty", "claude_agent_sdk")
ASYNC_PROCESS_CALLS = frozenset({"create_subprocess_exec", "create_subprocess_shell"})
OS_PROCESS_CALLS = ("system", "popen", "exec", "spawn", "fork")
OS_ENV_NAMES = frozenset({"environ", "environb", "getenv", "getenvb", "putenv", "unsetenv"})
CLAUDE_MODULE = "repocop.services.claude"
CLAUDE_SDK = "claude_agent_sdk"
# Each agent's module, and what is that agent's own: its SDK, folder and file names, credential
# variables, settings, the options RepoCop relies on or forbids, and its permission modes.
AGENT_NAMES = {
    CLAUDE_MODULE: (
        CLAUDE_SDK,
        ".claude",
        "CLAUDE.md",
        "CLAUDE_",
        "ANTHROPIC_",
        "--resume",
        "--output-format",
        "--permission-mode",
        "--dangerously-skip-permissions",
        "acceptEdits",
        "bypassPermissions",
    ),
    "repocop.services.codex": (
        ".codex",
        "CODEX_",
        "sandbox_mode",
        "approval_policy",
        "model_reasoning_effort",
        "--dangerously-bypass-approvals-and-sandbox",
        "--skip-git-repo-check",
    ),
}
# Outside its agent's module today (`.claude/rules/agents.md`). Not precedent: delete an entry
# when its code moves into the module, and add none without a change that calls for it.
KNOWN_AGENT_COUPLING = [
    "repocop.services.runner: builds a slash command",
    "repocop.services.tasks: names .claude",
    "repocop/templates/requirements/show.html: names .claude",
]


def module_name(path: Path) -> str:
    parts = path.relative_to(PACKAGE_DIR.parent).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def package_modules() -> dict[str, ast.Module]:
    return {
        module_name(path): ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for path in sorted(PACKAGE_DIR.rglob("*.py"))
    }


def within(name: str, prefixes: tuple[str, ...]) -> bool:
    return any(name == prefix or name.startswith(prefix + ".") for prefix in prefixes)


def imported_names(tree: ast.Module) -> set[str]:
    """Every module a file imports; `from a import b` counts as both `a` and `a.b`."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def relative_imports(tree: ast.Module) -> list[str]:
    return [
        f"line {node.lineno}"
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.level > 0
    ]


def os_names(tree: ast.Module) -> set[str]:
    """Names used from `os`, whether as `os.name` or `from os import name`."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "os"
        ):
            names.add(node.attr)
        elif isinstance(node, ast.ImportFrom) and node.module == "os":
            names.update(alias.name for alias in node.names)
    return names


def process_launches(tree: ast.Module) -> list[str]:
    found = [
        f"imports {name}" for name in sorted(imported_names(tree)) if within(name, PROCESS_MODULES)
    ]
    found += sorted(
        f"calls {node.attr}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr in ASYNC_PROCESS_CALLS
    )
    found += [
        f"uses os.{name}" for name in sorted(os_names(tree)) if name.startswith(OS_PROCESS_CALLS)
    ]
    return found


def environment_reads(tree: ast.Module) -> list[str]:
    return [f"uses os.{name}" for name in sorted(os_names(tree) & OS_ENV_NAMES)]


def code_strings(tree: ast.Module) -> list[str]:
    """Every string in the code, the fixed parts of f-strings included, but no docstring."""
    owners = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, owners) and node.body and isinstance(node.body[0], ast.Expr)
    }
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


def builds_slash_command(tree: ast.Module) -> bool:
    """Whether an f-string is a slash and then a value, as in `/<workflow> <path>`."""
    return any(
        isinstance(node, ast.JoinedStr)
        and len(node.values) > 1
        and isinstance(node.values[0], ast.Constant)
        and node.values[0].value == "/"
        and isinstance(node.values[1], ast.FormattedValue)
        for node in ast.walk(tree)
    )


def agents_names(texts: list[str], module: str = "") -> list[str]:
    """Which agents' own names the texts hold, but for the agent whose module `module` is. A
    name inside a longer word doesn't count."""
    names = [name for owner, own in AGENT_NAMES.items() if owner != module for name in own]
    return [
        f"names {name}"
        for name in names
        if any(re.search(r"(?<!\w)" + re.escape(name), text) for text in texts)
    ]


def agent_coupling(tree: ast.Module, module: str = "") -> list[str]:
    """What a file takes from an agent itself, rather than asking that agent's module."""
    found = agents_names(code_strings(tree), module)
    if module != CLAUDE_MODULE:
        if any(within(name, (CLAUDE_SDK,)) for name in imported_names(tree)):
            found.append(f"imports {CLAUDE_SDK}")
        if builds_slash_command(tree):
            found.append("builds a slash command")
    return sorted(found)


def page_templates() -> dict[str, str]:
    return {
        path.relative_to(PACKAGE_DIR.parent).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted((PACKAGE_DIR / "templates").rglob("*.html"))
    }


def violations(check: str) -> list[str]:
    found: list[str] = []
    for name, tree in package_modules().items():
        if check == "process" and name not in PROCESS_WRAPPERS:
            found += [f"{name}: {v}" for v in process_launches(tree)]
        elif check == "layers" and within(name, LOWER_LAYERS):
            found += [
                f"{name} imports {i}" for i in sorted(imported_names(tree)) if within(i, WEB_LAYER)
            ]
        elif check == "env" and name not in ENV_READERS:
            found += [f"{name}: {v}" for v in environment_reads(tree)]
        elif check == "relative":
            found += [f"{name}: relative import at {v}" for v in relative_imports(tree)]
        elif check == "agent":
            found += [f"{name}: {v}" for v in agent_coupling(tree, name)]
    if check == "agent":
        for path, text in page_templates().items():
            found += [f"{path}: {v}" for v in agents_names([text])]
    return found


def test_architecture_only_process_wrappers_launch_processes() -> None:
    assert violations("process") == []


def test_architecture_lower_layers_never_import_the_web_layer() -> None:
    assert violations("layers") == []


def test_architecture_only_config_and_process_wrappers_read_the_environment() -> None:
    assert violations("env") == []


def test_architecture_imports_are_absolute_so_these_checks_see_them() -> None:
    assert violations("relative") == []


def test_architecture_only_an_agents_module_and_the_known_places_name_what_is_its_own() -> None:
    assert violations("agent") == KNOWN_AGENT_COUPLING, (
        "What is specific to one agent belongs in that agent's module, and "
        "KNOWN_AGENT_COUPLING lists exactly what is outside one: .claude/rules/agents.md"
    )


def test_architecture_agent_check_catches_known_violations() -> None:
    tree = ast.parse(
        '"""A docstring may mention .claude/skills and --resume."""\n'
        "from claude_agent_sdk import query\n"
        "SETTINGS = '.claude/settings.json'\n"
        "argv = [binary, '--permission-mode', mode]\n"
        "prompt = f'/{workflow} {path}'\n"
        "url = f'/tasks/{task_id}'\n"
        "loosened = ['-c', 'sandbox_mode=\"workspace-write\"']\n"
    )
    assert agent_coupling(tree) == [
        "builds a slash command",
        "imports claude_agent_sdk",
        "names --permission-mode",
        "names .claude",
        "names sandbox_mode",
    ]
    assert agents_names(["<code>CLAUDE.md</code> and ANTHROPIC_API_KEY"]) == [
        "names CLAUDE.md",
        "names ANTHROPIC_",
    ]
    assert agents_names(["{{ task.claude_session_id }}", "REPOCOP_CLAUDE_BIN"]) == []


def test_architecture_an_agents_module_may_name_its_own_agent_but_no_other() -> None:
    tree = ast.parse(
        "from claude_agent_sdk import query\n"
        "SETTINGS = '.claude/settings.json'\n"
        "HOME = '.codex/config.toml'\n"
    )
    assert agent_coupling(tree, CLAUDE_MODULE) == ["names .codex"]
    assert agent_coupling(tree, "repocop.services.codex") == [
        "imports claude_agent_sdk",
        "names .claude",
    ]


def test_architecture_checks_catch_known_violations() -> None:
    tree = ast.parse(
        "import subprocess\n"
        "import os\n"
        "from os import getenv\n"
        "from fastapi import FastAPI\n"
        "from . import sibling\n"
        "os.system('x')\n"
        "os.environ.get('X')\n"
        "asyncio.create_subprocess_exec('x')\n"
    )
    assert process_launches(tree) == [
        "imports subprocess",
        "calls create_subprocess_exec",
        "uses os.system",
    ]
    assert environment_reads(tree) == ["uses os.environ", "uses os.getenv"]
    assert any(within(name, WEB_LAYER) for name in imported_names(tree))
    assert relative_imports(tree) == ["line 5"]


def test_architecture_scans_the_whole_package() -> None:
    names = set(package_modules())
    assert {"repocop.main", "repocop.db", "repocop.routes.health"} <= names
    assert "repocop/templates/base.html" in page_templates()
