"""Tests for the DriftLock MCP adapter (stdio server surface).

The adapter is exercised through ``MCPServer.list_tools`` and
``MCPServer.call_tool``, which validate arguments and convert results exactly
like the transport layer, without opening a socket.
"""

import asyncio
import ast
import hashlib
import shutil
from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from driftlock.mcp_server import WORKSPACE_ENV, server

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PRODUCTION_CONTRACT = PROJECT_ROOT / "driftlock" / "api" / "server.py"
FIXTURES = PROJECT_ROOT / "fixtures" / "demo_repo"

TOOL_NAMES = {"driftlock_audit", "driftlock_demo", "driftlock_apply_fix"}


def _call(name: str, arguments: dict):
    return asyncio.run(server.call_tool(name, arguments))


def _payload(result) -> dict:
    assert result.is_error is False
    assert result.structured_content is not None
    return result.structured_content


def _write_contract_pair(tmp_path: Path, *, mutate: bool) -> tuple[Path, Path, Path]:
    """Create a workspace with base/head contracts copied from production."""
    repo = tmp_path / "repo"
    repo.mkdir()
    source = PRODUCTION_CONTRACT.read_text(encoding="utf-8")
    base = repo / "server_base.py"
    head = repo / "server_head.py"
    base.write_text(source, encoding="utf-8")

    if mutate:
        tree = ast.parse(source)
        target = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and node.name == "CustomAuditRequest"
        )
        lines = source.splitlines(keepends=True)
        lines.insert(
            target.end_lineno,
            '    request_id: str = Field(..., description="Caller id")\n',
        )
        source = "".join(lines)
        ast.parse(source)  # keep the mutation syntactically valid
    head.write_text(source, encoding="utf-8")
    return repo, base, head


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv(WORKSPACE_ENV, str(tmp_path))
    return tmp_path


# ---------------------------------------------------------------------------
# Discovery and validation
# ---------------------------------------------------------------------------


def test_tool_discovery_exposes_verified_capabilities():
    tools = asyncio.run(server.list_tools())
    by_name = {tool.name: tool for tool in tools}

    assert set(by_name) == TOOL_NAMES
    assert set(by_name["driftlock_audit"].input_schema["required"]) == {
        "repository_root", "base_contract", "head_contract",
    }
    assert "ci" in by_name["driftlock_audit"].input_schema["properties"]
    assert set(by_name["driftlock_apply_fix"].input_schema["required"]) == {
        "repository_root", "base_contract", "head_contract",
    }
    assert "authorize" in by_name["driftlock_apply_fix"].input_schema["properties"]
    assert by_name["driftlock_demo"].input_schema.get("required") in (None, [])

    assert by_name["driftlock_audit"].annotations.read_only_hint is True
    assert by_name["driftlock_demo"].annotations.read_only_hint is True
    assert by_name["driftlock_apply_fix"].annotations.read_only_hint is False
    assert by_name["driftlock_apply_fix"].annotations.destructive_hint is True


def test_missing_arguments_are_rejected(workspace):
    with pytest.raises(ToolError):
        _call("driftlock_audit", {"repository_root": str(workspace)})


def test_missing_workspace_configuration_is_rejected(tmp_path, monkeypatch):
    monkeypatch.delenv(WORKSPACE_ENV, raising=False)
    repo, base, head = _write_contract_pair(tmp_path, mutate=False)

    with pytest.raises(ToolError, match=WORKSPACE_ENV):
        _call("driftlock_audit", {
            "repository_root": str(repo),
            "base_contract": "server_base.py",
            "head_contract": "server_head.py",
        })


def test_paths_outside_workspace_are_rejected(workspace, tmp_path):
    repo, _, _ = _write_contract_pair(tmp_path, mutate=False)

    with pytest.raises(ToolError, match="outside the authorized workspace"):
        _call("driftlock_audit", {
            "repository_root": "/etc",
            "base_contract": "server_base.py",
            "head_contract": "server_head.py",
        })

    with pytest.raises(ToolError, match="outside the authorized workspace"):
        _call("driftlock_audit", {
            "repository_root": str(repo),
            "base_contract": "../../etc/passwd",
            "head_contract": "server_head.py",
        })

    with pytest.raises(ToolError, match="is not a file"):
        _call("driftlock_audit", {
            "repository_root": str(repo),
            "base_contract": "does_not_exist.py",
            "head_contract": "server_head.py",
        })


# ---------------------------------------------------------------------------
# Audits and CI semantics
# ---------------------------------------------------------------------------


def test_clean_audit_preserves_json_schema_and_ci_pass(workspace, tmp_path):
    repo, base, _ = _write_contract_pair(tmp_path, mutate=False)

    result = _payload(_call("driftlock_audit", {
        "repository_root": str(repo),
        "base_contract": str(base),
        "head_contract": str(base),
        "ci": True,
    }))

    assert result["mode"] == "production_audit"
    assert result["is_production_audit"] is True
    assert result["exit_code"] == 0
    report = result["report"]
    assert set(report) >= {
        "schema_version", "has_drift", "total_drifts", "drifts",
        "blast_radius", "ci",
    }
    assert report["has_drift"] is False
    assert report["total_drifts"] == 0
    assert report["ci"]["status"] == "passed"
    assert report["ci"]["exit_code"] == 0
    assert isinstance(result["diagnostics"], list)


def test_breaking_drift_detected_and_ci_blocks(workspace, tmp_path):
    repo, base, head = _write_contract_pair(tmp_path, mutate=True)
    base_before = base.read_text(encoding="utf-8")
    head_before = head.read_text(encoding="utf-8")

    result = _payload(_call("driftlock_audit", {
        "repository_root": str(repo),
        "base_contract": str(base),
        "head_contract": str(head),
        "ci": True,
    }))

    assert result["exit_code"] == 1
    report = result["report"]
    assert report["has_breaking_drift"] is True
    assert report["total_drifts"] == 1
    assert report["drifts"] == [{
        "category": "FIELD_ADDED",
        "identifier": "CustomAuditRequest.request_id",
        "details": (
            "Field 'request_id' added to 'CustomAuditRequest' "
            "(type=str, required=True, default=None)"
        ),
        "is_breaking": True,
    }]
    assert report["ci"] == {
        "enabled": True,
        "status": "blocked",
        "exit_code": 1,
        "blocking_reasons": ["breaking_contract_drift"],
        "remaining_impacted_files": 0,
    }
    errors = [line for line in result["diagnostics"] if "CI Gatekeeper" in line]
    assert errors and "BLOCKED" in errors[0]
    # The read-only audit never writes to the workspace.
    assert base.read_text(encoding="utf-8") == base_before
    assert head.read_text(encoding="utf-8") == head_before
    assert {path.name for path in repo.iterdir()} == {"server_base.py", "server_head.py"}


def test_audit_without_ci_keeps_zero_exit_on_drift(workspace, tmp_path):
    repo, base, head = _write_contract_pair(tmp_path, mutate=True)

    result = _payload(_call("driftlock_audit", {
        "repository_root": str(repo),
        "base_contract": str(base),
        "head_contract": str(head),
    }))

    assert result["exit_code"] == 0
    assert result["report"]["has_drift"] is True
    assert result["report"]["ci"]["status"] == "not_run"


# ---------------------------------------------------------------------------
# Fixture demo
# ---------------------------------------------------------------------------


def test_demo_is_labeled_as_fixture_not_production(workspace):
    test_file = FIXTURES / "tests" / "test_users.py"
    before = hashlib.sha256(test_file.read_bytes()).hexdigest()

    result = _payload(_call("driftlock_demo", {}))

    assert result["mode"] == "fixture_demo"
    assert result["is_production_audit"] is False
    assert "not a production audit" in result["label"]
    assert result["exit_code"] == 0
    assert result["report"]["has_drift"] is True
    assert result["report"]["total_drifts"] == 4
    assert hashlib.sha256(test_file.read_bytes()).hexdigest() == before


# ---------------------------------------------------------------------------
# Authorized remediation
# ---------------------------------------------------------------------------


def test_fix_requires_authorization_and_reports_real_changes(workspace, tmp_path):
    demo = tmp_path / "demo"
    shutil.copytree(FIXTURES, demo)
    test_file = demo / "tests" / "test_users.py"
    before = test_file.read_text(encoding="utf-8")

    with pytest.raises(ToolError, match="authorize=true"):
        _call("driftlock_apply_fix", {
            "repository_root": str(demo),
            "base_contract": "api_base.py",
            "head_contract": "api_head.py",
            "authorize": False,
        })
    assert test_file.read_text(encoding="utf-8") == before

    result = _payload(_call("driftlock_apply_fix", {
        "repository_root": str(demo),
        "base_contract": "api_base.py",
        "head_contract": "api_head.py",
        "authorize": True,
    }))

    assert result["mode"] == "apply_fix"
    assert result["authorized"] is True
    assert result["exit_code"] == 0
    assert len(result["files_changed"]) == 3
    assert all(Path(path).is_relative_to(demo) for path in result["files_changed"])
    assert result["verification"] == {
        "remaining_impacted_files": 0,
        "synchronized": True,
        "files_written": 3,
    }
    assert len(result["diffs"]) == 3
    assert all(diff["unified_diff"].startswith("--- a/") for diff in result["diffs"])
    assert test_file.read_text(encoding="utf-8") != before
    assert "organization_id" in test_file.read_text(encoding="utf-8")
