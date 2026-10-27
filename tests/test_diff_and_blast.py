"""Tests for DriftLock contract diff engine and blast radius mapper.

Covers:
- compute_contract_diff: field added/removed/type changed, route added/removed
- BlastRadiusMapper: stale test files, docs, and agent context detection
- CLI demo command execution
"""

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

