"""No harness, statistics, RL or script module imports the scripted agents (R4, phases.md P1-7).

Scripted agents and cheaters live only in harness/agents/. If the task, scorer, integrity,
sandbox, statistics, RL or script code imported them, a real model could not replace them by
changing one setting, and agent knowledge (patches, true rates) could leak into scoring or
reporting.
"""

from __future__ import annotations

import ast
from pathlib import Path

from harness.tasks import REPO_ROOT

AGENTS = "harness.agents"
CHECKED_DIRS = ("harness", "stats", "rl", "scripts")


def checked_files() -> list[Path]:
    agents_dir = REPO_ROOT / "harness" / "agents"
    return sorted(
        p
        for d in CHECKED_DIRS
        if (REPO_ROOT / d).is_dir()
        for p in (REPO_ROOT / d).rglob("*.py")
        if agents_dir not in p.parents
    )


def agent_imports(source: str) -> list[str]:
    """Every import in source that reaches harness.agents, however it is spelled."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [
                a.name for a in node.names if a.name == AGENTS or a.name.startswith(f"{AGENTS}.")
            ]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if node.module == AGENTS or node.module.startswith(f"{AGENTS}."):
                found.append(node.module)
            elif node.module == "harness" and any(a.name == "agents" for a in node.names):
                found.append("harness.agents")
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute | ast.Name)
            and getattr(node.func, "attr", getattr(node.func, "id", ""))
            in ("import_module", "__import__")
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and str(node.args[0].value).startswith(AGENTS)
        ):
            found.append(str(node.args[0].value))
    return found


def test_no_checked_module_imports_the_scripted_agents() -> None:
    files = checked_files()
    assert any(p.name == "eval.py" for p in files), (
        "harness/eval.py must be among the checked files"
    )
    offenders = {str(p.relative_to(REPO_ROOT)): agent_imports(p.read_text()) for p in files}
    assert {path: found for path, found in offenders.items() if found} == {}


def test_the_check_catches_every_spelling() -> None:
    assert agent_imports("import harness.agents.oracle") == ["harness.agents.oracle"]
    assert agent_imports("from harness.agents.oracle import oracle_model") == [
        "harness.agents.oracle"
    ]
    assert agent_imports("from harness import agents") == ["harness.agents"]
    assert agent_imports("importlib.import_module('harness.agents.oracle')") == [
        "harness.agents.oracle"
    ]
    assert agent_imports("from harness import scorer\nimport harness.agentsx") == []
