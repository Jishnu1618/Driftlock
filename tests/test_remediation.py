"""Tests for the DriftLock closed-loop remediation engine.

Verifies that DriftRemediator patches stale TEST, DOCUMENTATION, and AGENT_MEMORY
files so that re-scanning the blast radius finds zero remaining impacted artifacts.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from driftlock.blast_radius.graph import BlastRadiusMapper, BlastRadiusResult
from driftlock.core.diff import compute_contract_diff
from driftlock.core.parser import parse_file
from driftlock.sync.remediator import DriftRemediator, RemediationResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_temp_demo() -> tuple[Path, Path, Path]:
    """Copy fixtures/demo_repo/ into a temp dir and return (tmp_dir, base_file, head_file).

    Caller is responsible for cleaning up the tmp_dir.
    """
    project_root = Path(__file__).resolve().parent.parent
    demo_dir = project_root / "fixtures" / "demo_repo"
    tmp = tempfile.mkdtemp(prefix="driftlock_test_")
    tmp_dir = Path(tmp) / "demo_repo"
    shutil.copytree(str(demo_dir), str(tmp_dir))
    base_file = tmp_dir / "api_base.py"
    head_file = tmp_dir / "api_head.py"
    return tmp_dir, base_file, head_file


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDriftRemediator:
    """Tests for the deterministic offline remediation engine."""

    def test_remediation_reduces_impacted_to_zero(self):
        """After remediation, re-scanning blast radius should find 0 impacted files."""
        tmp_dir, base_file, head_file = _setup_temp_demo()
        try:
            base = parse_file(base_file)
            head = parse_file(head_file)
            report = compute_contract_diff(base, head)

            mapper = BlastRadiusMapper(str(tmp_dir))
            initial_result = mapper.scan_blast_radius(report)

            # Verify we start with impacted files
            assert initial_result.total_impacted_files >= 3, (
                f"Expected >= 3 impacted files before fix, got {initial_result.total_impacted_files}"
            )

            # Run remediation
            remediator = DriftRemediator(use_api=False)
            rem_result = remediator.remediate(initial_result, head)
            remediator.apply_patches(rem_result)

            # Re-scan
            post_mapper = BlastRadiusMapper(str(tmp_dir))
            post_result = post_mapper.scan_blast_radius(report)

            assert post_result.total_impacted_files == 0, (
                f"Expected 0 impacted files after fix, got {post_result.total_impacted_files}. "
                f"Remaining: {[a.file_path for a in post_result.impacted_artifacts]}"
            )
        finally:
            shutil.rmtree(str(tmp_dir.parent), ignore_errors=True)

    def test_remediation_patches_test_file(self):
        """test_users.py should be patched with the missing fields."""
        tmp_dir, base_file, head_file = _setup_temp_demo()
        try:
            base = parse_file(base_file)
            head = parse_file(head_file)
            report = compute_contract_diff(base, head)
            mapper = BlastRadiusMapper(str(tmp_dir))
            result = mapper.scan_blast_radius(report)

            remediator = DriftRemediator(use_api=False)
            rem_result = remediator.remediate(result, head)

            test_patches = [p for p in rem_result.patches if p.artifact_type == "TEST"]
            assert len(test_patches) >= 1, "Expected at least one TEST patch"

            patch = test_patches[0]
            assert "tier" in patch.patched_content, "Patched test should contain 'tier'"
            assert "organization_id" in patch.patched_content, (
                "Patched test should contain 'organization_id'"
            )
        finally:
            shutil.rmtree(str(tmp_dir.parent), ignore_errors=True)

    def test_remediation_patches_documentation(self):
        """README.md should be patched with the new fields in tables and JSON."""
        tmp_dir, base_file, head_file = _setup_temp_demo()
        try:
            base = parse_file(base_file)
            head = parse_file(head_file)
            report = compute_contract_diff(base, head)
            mapper = BlastRadiusMapper(str(tmp_dir))
            result = mapper.scan_blast_radius(report)

            remediator = DriftRemediator(use_api=False)
            rem_result = remediator.remediate(result, head)

            doc_patches = [p for p in rem_result.patches if p.artifact_type == "DOCUMENTATION"]
            assert len(doc_patches) >= 1, "Expected at least one DOCUMENTATION patch"

            patch = doc_patches[0]
            assert "tier" in patch.patched_content, "Patched docs should contain 'tier'"
            assert "organization_id" in patch.patched_content, (
                "Patched docs should contain 'organization_id'"
            )
        finally:
            shutil.rmtree(str(tmp_dir.parent), ignore_errors=True)

    def test_remediation_patches_agent_memory(self):
        """AGENT_CONTEXT.md should be patched with the new fields."""
        tmp_dir, base_file, head_file = _setup_temp_demo()
        try:
            base = parse_file(base_file)
            head = parse_file(head_file)
            report = compute_contract_diff(base, head)
            mapper = BlastRadiusMapper(str(tmp_dir))
            result = mapper.scan_blast_radius(report)

            remediator = DriftRemediator(use_api=False)
            rem_result = remediator.remediate(result, head)

            agent_patches = [p for p in rem_result.patches if p.artifact_type == "AGENT_MEMORY"]
            assert len(agent_patches) >= 1, "Expected at least one AGENT_MEMORY patch"

            patch = agent_patches[0]
            assert "tier" in patch.patched_content, "Patched agent context should contain 'tier'"
            assert "organization_id" in patch.patched_content, (
                "Patched agent context should contain 'organization_id'"
            )
        finally:
            shutil.rmtree(str(tmp_dir.parent), ignore_errors=True)

    def test_remediation_preserves_original_content(self):
        """Original fixture files should NOT be mutated."""
        project_root = Path(__file__).resolve().parent.parent
        demo_dir = project_root / "fixtures" / "demo_repo"

        # Snapshot originals
        originals = {}
        for fname in ["tests/test_users.py", "README.md", "AGENT_CONTEXT.md"]:
            fpath = demo_dir / fname
            originals[fname] = fpath.read_text(encoding="utf-8")

        # Run remediation on temp copy
        tmp_dir, base_file, head_file = _setup_temp_demo()
        try:
            base = parse_file(base_file)
            head = parse_file(head_file)
            report = compute_contract_diff(base, head)
            mapper = BlastRadiusMapper(str(tmp_dir))
            result = mapper.scan_blast_radius(report)

            remediator = DriftRemediator(use_api=False)
            rem_result = remediator.remediate(result, head)
            remediator.apply_patches(rem_result)
        finally:
            shutil.rmtree(str(tmp_dir.parent), ignore_errors=True)

        # Verify originals are untouched
        for fname, original_content in originals.items():
            fpath = demo_dir / fname
            current = fpath.read_text(encoding="utf-8")
            assert current == original_content, (
                f"Original fixture {fname} was mutated! This is a critical bug."
            )

    def test_remediation_result_structure(self):
        """RemediationResult should have correct structure and metadata."""
        tmp_dir, base_file, head_file = _setup_temp_demo()
        try:
            base = parse_file(base_file)
            head = parse_file(head_file)
            report = compute_contract_diff(base, head)
            mapper = BlastRadiusMapper(str(tmp_dir))
            result = mapper.scan_blast_radius(report)

            remediator = DriftRemediator(use_api=False)
            rem_result = remediator.remediate(result, head)

            # Check structure
            assert rem_result.files_patched >= 3, (
                f"Expected >= 3 patched files, got {rem_result.files_patched}"
            )

            # Each patch must have original != patched
            for patch in rem_result.patches:
                assert patch.original_content != patch.patched_content, (
                    f"Patch for {patch.file_path} has identical content (no-op)"
                )
                assert patch.artifact_type in {"TEST", "DOCUMENTATION", "AGENT_MEMORY"}
                assert len(patch.changes_applied) > 0, (
                    f"Patch for {patch.file_path} has no recorded changes"
                )

            # patch_map should be consistent
            patch_map = rem_result.patch_map
            assert len(patch_map) == rem_result.files_patched
        finally:
            shutil.rmtree(str(tmp_dir.parent), ignore_errors=True)

    def test_cli_demo_fix_runs_without_error(self):
        """The demo --fix command should execute without raising exceptions."""
        from typer.testing import CliRunner
        from driftlock.cli.main import app

        runner = CliRunner()
        result = runner.invoke(app, ["demo", "--fix"])
        assert result.exit_code == 0, f"Demo --fix failed with output:\n{result.output}"
        assert "SYNCHRONIZED" in result.output or "Remediation" in result.output


class TestRemediationWorkspaceAPI:
    """Test the public ``remediate_workspace`` API returns the expected dict."""

    def test_remediate_workspace_returns_dict(self):
        """remediate_workspace should return {path: (original, patched)}."""
        tmp_dir, base_file, head_file = _setup_temp_demo()
        try:
            base = parse_file(base_file)
            head = parse_file(head_file)
            report = compute_contract_diff(base, head)
            mapper = BlastRadiusMapper(str(tmp_dir))
            result = mapper.scan_blast_radius(report)

            remediator = DriftRemediator(use_api=False)
            workspace = remediator.remediate_workspace(result, head)

            assert isinstance(workspace, dict)
            assert len(workspace) >= 3

            for path, (orig, patched) in workspace.items():
                assert isinstance(orig, str)
                assert isinstance(patched, str)
                assert orig != patched
        finally:
            shutil.rmtree(str(tmp_dir.parent), ignore_errors=True)
