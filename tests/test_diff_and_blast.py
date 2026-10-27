"""Tests for DriftLock contract diff engine and blast radius mapper.

Covers:
- compute_contract_diff: field added/removed/type changed, route added/removed
- BlastRadiusMapper: stale test files, docs, and agent context detection
- CLI demo command execution
"""

import ast
import json
import os
from pathlib import Path

import pytest

from driftlock.core.parser import parse_code, parse_file
from driftlock.core.diff import ContractDrift, DriftReport, compute_contract_diff
from driftlock.blast_radius.graph import BlastRadiusMapper, BlastRadiusResult, ImpactedArtifact


# ---------------------------------------------------------------------------
# Fixtures: base and head source code
# ---------------------------------------------------------------------------

BASE_SOURCE = '''
from pydantic import BaseModel, Field
from fastapi import FastAPI

app = FastAPI()

class UserCreate(BaseModel):
    username: str = Field(..., min_length=3)
    email: str

class ItemCreate(BaseModel):
    name: str
    price: float = 9.99

@app.post("/v1/users", response_model=dict, status_code=201)
async def create_user(payload: UserCreate):
    pass

@app.get("/v1/users/{user_id}")
async def get_user(user_id: int):
    pass

@app.get("/v1/items")
def list_items():
    pass
'''

HEAD_SOURCE = '''
from pydantic import BaseModel, Field
from fastapi import FastAPI

app = FastAPI()

class UserCreate(BaseModel):
    username: str = Field(..., min_length=3)
    email: str
    tier: str = Field(..., description="Subscription tier")
    organization_id: int = Field(default=1)

class ItemCreate(BaseModel):
    name: str
    price: int = 10

@app.post("/v1/users", response_model=dict, status_code=201)
async def create_user(payload: UserCreate):
    pass

@app.get("/v1/users/{user_id}")
async def get_user(user_id: int):
    pass

@app.delete("/v1/users/{user_id}")
async def delete_user(user_id: int):
    pass
'''


# ---------------------------------------------------------------------------
# Tests: compute_contract_diff
# ---------------------------------------------------------------------------

class TestComputeContractDiff:
    """Tests for the contract diff engine."""

    def setup_method(self):
        self.base = parse_code(BASE_SOURCE, "base.py")
        self.head = parse_code(HEAD_SOURCE, "head.py")
        self.report = compute_contract_diff(self.base, self.head)

    def test_drift_detected(self):
        assert self.report.has_drift is True

    def test_has_breaking_drift(self):
        assert self.report.has_breaking_drift is True

    def test_field_added_breaking(self):
        """tier: str (required, no default) should be a breaking FIELD_ADDED."""
        tier_drifts = [
            d for d in self.report.drifts
            if d.category == "FIELD_ADDED" and "tier" in d.identifier
        ]
        assert len(tier_drifts) >= 1
        assert tier_drifts[0].is_breaking is True
        assert "UserCreate" in tier_drifts[0].identifier

    def test_field_added_non_breaking(self):
        """organization_id: int = 1 (has default) should be a non-breaking FIELD_ADDED."""
        org_drifts = [
            d for d in self.report.drifts
            if d.category == "FIELD_ADDED" and "organization_id" in d.identifier
        ]
        assert len(org_drifts) >= 1
        assert org_drifts[0].is_breaking is False

    def test_field_type_changed(self):
        """ItemCreate.price changed from float to int -> FIELD_TYPE_CHANGED."""
        type_drifts = [
            d for d in self.report.drifts
            if d.category == "FIELD_TYPE_CHANGED" and "price" in d.identifier
        ]
        assert len(type_drifts) == 1
        assert type_drifts[0].is_breaking is True
        assert "float" in type_drifts[0].details
        assert "int" in type_drifts[0].details

    def test_field_default_changed(self):
        """ItemCreate.price default changed from 9.99 to 10 -> FIELD_DEFAULT_CHANGED."""
        default_drifts = [
            d for d in self.report.drifts
            if d.category == "FIELD_DEFAULT_CHANGED" and "price" in d.identifier
        ]
        assert len(default_drifts) == 1
        assert default_drifts[0].is_breaking is False

    def test_route_added(self):
        """DELETE /v1/users/{user_id} is new -> ROUTE_ADDED (non-breaking)."""
        added = [
            d for d in self.report.drifts
            if d.category == "ROUTE_ADDED" and "DELETE" in d.identifier
        ]
        assert len(added) == 1
        assert added[0].is_breaking is False

    def test_route_removed(self):
        """GET /v1/items was removed -> ROUTE_REMOVED (breaking)."""
        removed = [
            d for d in self.report.drifts
            if d.category == "ROUTE_REMOVED" and "/v1/items" in d.identifier
        ]
        assert len(removed) == 1
        assert removed[0].is_breaking is True

    def test_no_drift_identical_contracts(self):
        """Same contract compared with itself should produce zero drifts."""
        report = compute_contract_diff(self.base, self.base)
        assert report.has_drift is False
        assert report.has_breaking_drift is False

    def test_deterministic_diff(self):
        """Running the diff twice produces identical reports."""
        report2 = compute_contract_diff(self.base, self.head)
        cats1 = [(d.category, d.identifier) for d in self.report.drifts]
        cats2 = [(d.category, d.identifier) for d in report2.drifts]
        assert cats1 == cats2


# ---------------------------------------------------------------------------
# Tests: BlastRadiusMapper
# ---------------------------------------------------------------------------

class TestBlastRadiusMapper:
    """Tests for the blast radius scanner using demo_repo fixtures."""

    @pytest.fixture(autouse=True)
    def setup_paths(self):
        project_root = Path(__file__).resolve().parent.parent
        self.demo_dir = project_root / "fixtures" / "demo_repo"
        self.base_file = self.demo_dir / "api_base.py"
        self.head_file = self.demo_dir / "api_head.py"

    def test_demo_fixtures_exist(self):
        """Verify all demo fixture files are present."""
        assert self.demo_dir.is_dir()
        assert self.base_file.is_file()
        assert self.head_file.is_file()
        assert (self.demo_dir / "tests" / "test_users.py").is_file()
        assert (self.demo_dir / "AGENT_CONTEXT.md").is_file()
        assert (self.demo_dir / "README.md").is_file()

    def test_blast_radius_detects_stale_test(self):
        """test_users.py references UserCreate but is missing 'tier'."""
        base = parse_file(self.base_file)
        head = parse_file(self.head_file)
        report = compute_contract_diff(base, head)
        mapper = BlastRadiusMapper(str(self.demo_dir))
        result = mapper.scan_blast_radius(report)

        test_impacts = result.impacted_tests
        test_paths = [a.file_path for a in test_impacts]
        assert any("test_users" in p for p in test_paths), (
            f"Expected test_users.py in impacted tests, got: {test_paths}"
        )

    def test_blast_radius_detects_stale_agent_context(self):
        """AGENT_CONTEXT.md references UserCreate but is missing 'tier'."""
        base = parse_file(self.base_file)
        head = parse_file(self.head_file)
        report = compute_contract_diff(base, head)
        mapper = BlastRadiusMapper(str(self.demo_dir))
        result = mapper.scan_blast_radius(report)

        agent_impacts = result.impacted_agent_memory
        agent_paths = [a.file_path for a in agent_impacts]
        assert any("AGENT_CONTEXT" in p for p in agent_paths), (
            f"Expected AGENT_CONTEXT.md in impacted agent memory, got: {agent_paths}"
        )

    def test_blast_radius_detects_stale_docs(self):
        """README.md references UserCreate but is missing 'tier'."""
        base = parse_file(self.base_file)
        head = parse_file(self.head_file)
        report = compute_contract_diff(base, head)
        mapper = BlastRadiusMapper(str(self.demo_dir))
        result = mapper.scan_blast_radius(report)

        doc_impacts = result.impacted_docs
        doc_paths = [a.file_path for a in doc_impacts]
        assert any("README" in p for p in doc_paths), (
            f"Expected README.md in impacted docs, got: {doc_paths}"
        )

    def test_blast_radius_total_impacted_files(self):
        """Should detect at least 3 impacted files (test, agent context, docs)."""
        base = parse_file(self.base_file)
        head = parse_file(self.head_file)
        report = compute_contract_diff(base, head)
        mapper = BlastRadiusMapper(str(self.demo_dir))
        result = mapper.scan_blast_radius(report)

        assert result.total_impacted_files >= 3

    def test_no_blast_radius_when_no_drift(self):
        """If contracts are identical, blast radius should be empty."""
        base = parse_file(self.base_file)
        report = compute_contract_diff(base, base)
        mapper = BlastRadiusMapper(str(self.demo_dir))
        result = mapper.scan_blast_radius(report)

        assert result.total_impacted_files == 0
        assert len(result.impacted_artifacts) == 0

    def test_impacted_artifact_has_suggested_action(self):
        """Every impacted artifact should have a non-empty suggested action."""
        base = parse_file(self.base_file)
        head = parse_file(self.head_file)
        report = compute_contract_diff(base, head)
        mapper = BlastRadiusMapper(str(self.demo_dir))
        result = mapper.scan_blast_radius(report)

        for artifact in result.impacted_artifacts:
            assert artifact.suggested_action, (
                f"Missing suggested_action for {artifact.file_path}"
            )
            assert len(artifact.suggested_action) > 10


# ---------------------------------------------------------------------------
# Tests: CLI demo integration
# ---------------------------------------------------------------------------

class TestCLIDemo:
    """Integration test for the CLI demo command."""

    def test_demo_command_invocation(self):
        """The demo command should run without raising exceptions."""
        from typer.testing import CliRunner
        from driftlock.cli.main import app

        runner = CliRunner()
        result = runner.invoke(app, ["demo"])
        assert result.exit_code == 0, f"Demo failed with output:\n{result.output}"
        assert "DRIFT DETECTED" in result.output or "drift" in result.output.lower()

    def test_audit_command_json_output(self):
        """The audit command with --json should produce valid JSON output."""
        from typer.testing import CliRunner
        from driftlock.cli.main import app

        project_root = Path(__file__).resolve().parent.parent
        demo_dir = project_root / "fixtures" / "demo_repo"
        base_file = demo_dir / "api_base.py"
        head_file = demo_dir / "api_head.py"

        runner = CliRunner()
        result = runner.invoke(app, [
            "audit",
            "--base", str(base_file),
            "--head", str(head_file),
            "--repo", str(demo_dir),
            "--json",
        ])
        assert result.exit_code == 0, f"Audit --json failed:\n{result.output}"
        # The output may have Rich formatting; find the JSON portion
        assert "has_drift" in result.output

    def test_audit_command_ci_flag_drift_detected_fails(self):
        """The audit command with --ci should exit with code 1 when breaking drift/impacted artifacts exist."""
        from typer.testing import CliRunner
        from driftlock.cli.main import app

        project_root = Path(__file__).resolve().parent.parent
        demo_dir = project_root / "fixtures" / "demo_repo"
        base_file = demo_dir / "api_base.py"
        head_file = demo_dir / "api_head.py"

        runner = CliRunner()
        result = runner.invoke(app, [
            "audit",
            "--base", str(base_file),
            "--head", str(head_file),
            "--repo", str(demo_dir),
            "--ci",
        ])
        assert result.exit_code == 1
        assert "CI Gatekeeper" in result.output

    def test_audit_command_ci_flag_clean_contract_passes(self):
        """The audit command with --ci should exit with code 0 when contracts are identical and in sync."""
        from typer.testing import CliRunner
        from driftlock.cli.main import app

        project_root = Path(__file__).resolve().parent.parent
        demo_dir = project_root / "fixtures" / "demo_repo"
        head_file = demo_dir / "api_head.py"

        runner = CliRunner()
        result = runner.invoke(app, [
            "audit",
            "--base", str(head_file),
            "--head", str(head_file),
            "--repo", str(demo_dir),
            "--ci",
        ])
        assert result.exit_code == 0
        assert "CI Gatekeeper" in result.output



# ---------------------------------------------------------------------------
# Tests: machine-readable --json contract (regression coverage)
# ---------------------------------------------------------------------------

class TestCLIJsonContract:
    """`--json` must emit exactly one JSON document on stdout.

    The CI gate message and progress diagnostics belong on stderr so that
    piping stdout into `jq` keeps working in both normal and CI mode.
    """

    @staticmethod
    def _demo_paths():
        project_root = Path(__file__).resolve().parent.parent
        demo_dir = project_root / "fixtures" / "demo_repo"
        return demo_dir, demo_dir / "api_base.py", demo_dir / "api_head.py"

    def test_audit_json_ci_drift_emits_single_document_and_blocks(self):
        from typer.testing import CliRunner
        from driftlock.cli.main import app

        demo_dir, base_file, head_file = self._demo_paths()

        runner = CliRunner()
        result = runner.invoke(app, [
            "audit",
            "--base", str(base_file),
            "--head", str(head_file),
            "--repo", str(demo_dir),
            "--json",
            "--ci",
        ])

        assert result.exit_code == 1
        data = json.loads(result.stdout)  # rejects any trailing non-JSON text
        assert data["schema_version"]
        assert data["has_drift"] is True
        assert data["has_breaking_drift"] is True
        assert data["total_drifts"] == 4
        assert data["breaking_drifts"] == 3
        assert data["non_breaking_drifts"] == 1
        assert data["blast_radius"]["total_impacted_files"] == 3
        assert {a["artifact_type"] for a in data["blast_radius"]["impacted_artifacts"]} == {
            "TEST",
            "DOCUMENTATION",
            "AGENT_MEMORY",
        }
        assert data["ci"] == {
            "enabled": True,
            "status": "blocked",
            "exit_code": 1,
            "blocking_reasons": ["breaking_contract_drift", "stale_artifacts"],
            "remaining_impacted_files": 3,
        }
        assert "CI Gatekeeper: BLOCKED" in result.stderr
        assert "CI Gatekeeper" not in result.stdout

    def test_audit_json_ci_clean_emits_single_document_and_passes(self):
        from typer.testing import CliRunner
        from driftlock.cli.main import app

        demo_dir, _, head_file = self._demo_paths()

        runner = CliRunner()
        result = runner.invoke(app, [
            "audit",
            "--base", str(head_file),
            "--head", str(head_file),
            "--repo", str(demo_dir),
            "--json",
            "--ci",
        ])

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["has_drift"] is False
        assert data["has_breaking_drift"] is False
        assert data["total_drifts"] == 0
        assert data["drifts"] == []
        assert data["blast_radius"]["total_impacted_files"] == 0
        assert data["blast_radius"]["impacted_artifacts"] == []
        assert data["ci"] == {
            "enabled": True,
            "status": "passed",
            "exit_code": 0,
            "blocking_reasons": [],
            "remaining_impacted_files": 0,
        }
        assert "CI Gatekeeper: PASSED" in result.stderr

    def test_audit_json_without_ci_reports_not_run(self):
        from typer.testing import CliRunner
        from driftlock.cli.main import app

        demo_dir, base_file, head_file = self._demo_paths()

        runner = CliRunner()
        result = runner.invoke(app, [
            "audit",
            "--base", str(base_file),
            "--head", str(head_file),
            "--repo", str(demo_dir),
            "--json",
        ])

        # Drift exists, but without --ci the process still exits 0.
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["has_drift"] is True
        assert data["ci"]["enabled"] is False
        assert data["ci"]["status"] == "not_run"
        assert data["ci"]["exit_code"] is None
        assert "CI Gatekeeper" not in result.stdout
        assert "CI Gatekeeper" not in result.stderr


# ---------------------------------------------------------------------------
# Tests: controlled mutation of the real production contract
# ---------------------------------------------------------------------------

def _build_mutated_production_pair(tmp_path):
    """Copy the production contract and add one required field in the copy.

    The mutation targets ``CustomAuditRequest`` in ``driftlock/api/server.py``
    because a required field without a default must classify as a breaking
    ``FIELD_ADDED``. Both files live under ``tmp_path``; the production file is
    only read.
    """
    project_root = Path(__file__).resolve().parent.parent
    server = project_root / "driftlock" / "api" / "server.py"

    base = tmp_path / "server_base.py"
    head = tmp_path / "server_head.py"
    base.write_bytes(server.read_bytes())

    source = base.read_text(encoding="utf-8")
    tree = ast.parse(source)
    target = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == "CustomAuditRequest"
    )
    lines = source.splitlines(keepends=True)
    lines.insert(
        target.end_lineno,
        '    request_id: str = Field(..., description="Caller-supplied idempotency key")\n',
    )
    head.write_text("".join(lines), encoding="utf-8")
    ast.parse(head.read_text(encoding="utf-8"))  # mutation stays syntactically valid

    return server, base, head


class TestCLIProductionContractMutation:
    """A real production-shaped model change must be detected, not self-compared."""

    def test_production_model_mutation_detected_in_json(self, tmp_path):
        from typer.testing import CliRunner
        from driftlock.cli.main import app

        server, base, head = _build_mutated_production_pair(tmp_path)
        before = server.read_bytes()

        runner = CliRunner()
        result = runner.invoke(app, [
            "audit",
            "--base", str(base),
            "--head", str(head),
            "--repo", str(tmp_path),
            "--json",
        ])

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["has_drift"] is True
        assert data["has_breaking_drift"] is True
        assert data["total_drifts"] == 1
        assert data["breaking_drifts"] == 1
        assert data["non_breaking_drifts"] == 0
        assert data["drifts"] == [{
            "category": "FIELD_ADDED",
            "identifier": "CustomAuditRequest.request_id",
            "details": (
                "Field 'request_id' added to 'CustomAuditRequest' "
                "(type=str, required=True, default=None)"
            ),
            "is_breaking": True,
        }]
        assert data["blast_radius"] == {
            "total_impacted_files": 0,
            "impacted_artifacts": [],
        }
        assert data["ci"]["enabled"] is False
        assert data["ci"]["status"] == "not_run"
        assert "CI Gatekeeper" not in result.stdout
        # The production source is never touched by the scenario.
        assert server.read_bytes() == before

    def test_production_model_mutation_blocks_ci(self, tmp_path):
        from typer.testing import CliRunner
        from driftlock.cli.main import app

        server, base, head = _build_mutated_production_pair(tmp_path)
        before = server.read_bytes()

        runner = CliRunner()
        result = runner.invoke(app, [
            "audit",
            "--base", str(base),
            "--head", str(head),
            "--repo", str(tmp_path),
            "--json",
            "--ci",
        ])

        assert result.exit_code == 1
        data = json.loads(result.stdout)  # exactly one JSON document on stdout
        assert data["ci"] == {
            "enabled": True,
            "status": "blocked",
            "exit_code": 1,
            "blocking_reasons": ["breaking_contract_drift"],
            "remaining_impacted_files": 0,
        }
        assert "CI Gatekeeper: BLOCKED" in result.stderr
        assert "CI Gatekeeper" not in result.stdout
        assert server.read_bytes() == before
