from __future__ import annotations

import ast
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_package_metadata_locks_qualified_git_dependencies() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    packages = {package["name"]: package for package in lock["package"]}

    assert project["project"]["requires-python"] == ">=3.12"
    assert project["project"]["dependencies"][:2] == [
        "llm-tools @ git+https://github.com/NielsdaWheelz/llm-tools.git@9e6d155f3b64f03495911435b7cae8b8d131f9a2",
        "provider-runtime @ git+https://github.com/NielsdaWheelz/llm-calling.git@a14432276142872785b19460d4dc4a6d9650c8ff",
    ]
    assert packages["provider-runtime"]["source"]["git"].endswith(
        "?rev=a14432276142872785b19460d4dc4a6d9650c8ff#a14432276142872785b19460d4dc4a6d9650c8ff"
    )
    assert packages["llm-tools"]["source"]["git"].endswith(
        "?rev=9e6d155f3b64f03495911435b7cae8b8d131f9a2#9e6d155f3b64f03495911435b7cae8b8d131f9a2"
    )
    provider = packages["provider-runtime"]
    assert "websockets" in {dependency["name"] for dependency in provider["dependencies"]}
    assert "optional-dependencies" not in provider
    assert "openai-codex" not in packages
    assert "openai-codex-cli-bin" not in packages
    assert packages["websockets"]["version"].startswith("16.")


def test_import_has_no_filesystem_or_network_side_effect(tmp_path: Path) -> None:
    script = "import llm_agent_kernel"
    subprocess.run(
        [sys.executable, "-I", "-c", script],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    assert list(tmp_path.iterdir()) == []


def test_runtime_uses_no_private_dependency_imports() -> None:
    forbidden_roots = {"anthropic", "codex", "openai", "openai_codex"}
    for path in (ROOT / "src" / "llm_agent_kernel").glob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(name.name.split(".")[0] not in forbidden_roots for name in node.names)
            if isinstance(node, ast.ImportFrom) and node.module is not None:
                parts = node.module.split(".")
                assert parts[0] not in forbidden_roots
                if parts[0] in {"llm_tools", "provider_runtime"}:
                    assert not any(part.startswith("_") for part in parts), (path, node.module)


def test_kernel_does_not_reimplement_llm_tools_owners() -> None:
    forbidden_classes = {
        "BudgetState",
        "CapabilityProfile",
        "PositionRecorder",
        "ToolCatalog",
        "ToolExecutor",
        "ToolPlan",
    }
    declared: set[str] = set()
    for path in (ROOT / "src" / "llm_agent_kernel").glob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        declared.update(node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef))

    assert declared.isdisjoint(forbidden_classes)


def test_production_never_calls_event_discarding_run_turn_projection() -> None:
    for path in (ROOT / "src" / "llm_agent_kernel").glob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr != "run_turn", path


def test_package_contains_no_application_infrastructure() -> None:
    names = {path.name for path in (ROOT / "src" / "llm_agent_kernel").glob("*.py")}
    forbidden = {
        "approvals.py",
        "connectors.py",
        "credentials.py",
        "delivery.py",
        "migrations.py",
        "scheduler.py",
        "workflow.py",
    }

    assert names.isdisjoint(forbidden)
