"""Enforces the dependency rule from ARCHITECTURE.md §4 by scanning imports."""

import ast
import json
from pathlib import Path

from nexus.brain.tokens import estimate_tokens
from nexus.instructions.assemble import build_system_prompt
from nexus.tools.registry import default_registry

SOURCE = Path(__file__).parent.parent / "src" / "nexus"
LEAF_PACKAGES = {"brain", "tools", "guardrails", "context", "instructions", "session"}


def package_imports() -> dict[str, set[str]]:
    """Map each top-level package (or module) of nexus to the nexus packages it imports."""
    graph: dict[str, set[str]] = {}
    for file in SOURCE.rglob("*.py"):
        relative = file.relative_to(SOURCE)
        owner = relative.parts[0].removesuffix(".py")
        for node in ast.walk(ast.parse(file.read_text())):
            modules = []
            if isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)
            elif isinstance(node, ast.Import):
                modules += [alias.name for alias in node.names]
            for module in modules:
                parts = module.split(".")
                if parts[0] == "nexus" and len(parts) > 1 and parts[1] != owner:
                    graph.setdefault(owner, set()).add(parts[1])
    return graph


def test_messages_imports_nothing_from_nexus() -> None:
    assert "messages" not in package_imports()


def test_leaf_packages_never_import_the_loop_or_the_cli() -> None:
    graph = package_imports()
    for package in LEAF_PACKAGES:
        assert not graph.get(package, set()) & {"loop", "cli"}, package


def test_the_loop_never_touches_the_terminal_layer() -> None:
    assert "cli" not in package_imports().get("loop", set())


def test_packages_do_not_import_each_other_in_a_cycle() -> None:
    graph = package_imports()

    def reaches(start: str, target: str, seen: frozenset[str] = frozenset()) -> bool:
        return any(
            step == target or (step not in seen and reaches(step, target, seen | {step}))
            for step in graph.get(start, set())
        )

    assert [package for package in graph if reaches(package, package)] == []


def test_system_prompt_and_tool_specs_fit_the_fixed_budget(tmp_path: Path) -> None:
    prompt = build_system_prompt(tmp_path)
    specs = json.dumps([spec.to_dict() for spec in default_registry().specs()])
    assert estimate_tokens(prompt) + estimate_tokens(specs) < 2000
