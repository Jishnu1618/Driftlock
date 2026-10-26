"""Blast Radius Mapper: walks a repository to find stale references to drifted contracts.

For each drift in a DriftReport, scans test files, agent context files, and
documentation to identify files that reference the changed schema/route but
are missing the new or changed field names.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from driftlock.core.diff import ContractDrift, DriftReport

# Directories to always skip when walking the repo
SKIP_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", "node_modules", ".tox", ".mypy_cache"}

# Agent context filenames (case-insensitive matching)
AGENT_CONTEXT_NAMES = {
    "agent_context.md",
    "claude.md",
    "gemini.md",
    "cursorrules",
    ".cursorrules",
}

AGENT_MEMORY_PATTERNS = [
    re.compile(r"\.alan[/\\]memory\.md$", re.IGNORECASE),
    re.compile(r"agent_context\.md$", re.IGNORECASE),
    re.compile(r"claude\.md$", re.IGNORECASE),
    re.compile(r"gemini\.md$", re.IGNORECASE),
    re.compile(r"cursorrules$", re.IGNORECASE),
]


@dataclass
class ImpactedArtifact:
    """A file impacted by contract drift."""

    file_path: str
    artifact_type: str  # "TEST", "DOCUMENTATION", "AGENT_MEMORY"
    reason: str  # Human-readable description of why this file is impacted
    stale_reference: str  # The identifier (schema/route name) referenced but stale
    suggested_action: str  # What the user/agent should do to fix it


@dataclass
class BlastRadiusResult:
    """Result of a blast radius scan."""

    drift_report: DriftReport
    impacted_artifacts: list[ImpactedArtifact] = field(default_factory=list)

    @property
    def total_impacted_files(self) -> int:
        """Count of unique impacted file paths."""
        return len({a.file_path for a in self.impacted_artifacts})

    @property
    def impacted_tests(self) -> list[ImpactedArtifact]:
        return [a for a in self.impacted_artifacts if a.artifact_type == "TEST"]

    @property
    def impacted_docs(self) -> list[ImpactedArtifact]:
        return [a for a in self.impacted_artifacts if a.artifact_type == "DOCUMENTATION"]

    @property
    def impacted_agent_memory(self) -> list[ImpactedArtifact]:
        return [a for a in self.impacted_artifacts if a.artifact_type == "AGENT_MEMORY"]


class BlastRadiusMapper:
    """Scans a repository for stale references to drifted contracts."""

    def __init__(self, repo_root: str):
        self.repo_root = Path(repo_root)
        if not self.repo_root.is_dir():
            raise FileNotFoundError(f"Repository root not found: {repo_root}")

    def scan_blast_radius(self, drift_report: DriftReport) -> BlastRadiusResult:
        """Walk the repo and find files impacted by each drift."""
        result = BlastRadiusResult(drift_report=drift_report)

        if not drift_report.has_drift:
            return result

        # Collect all scannable files
        file_entries = self._collect_files()

        # For each drift, check relevant files
        for drift in drift_report.drifts:
            schema_name, field_name = self._parse_drift_identifiers(drift)
            if not schema_name:
                continue

            for fpath, ftype in file_entries:
                self._check_file(fpath, ftype, drift, schema_name, field_name, result)

        return result

    def _collect_files(self) -> list[tuple[Path, str]]:
        """Walk the repository and classify files by type."""
        entries: list[tuple[Path, str]] = []

        for dirpath, dirnames, filenames in os.walk(self.repo_root):
            # Prune skipped directories in-place
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

            for fname in filenames:
                fpath = Path(dirpath) / fname
                ftype = self._classify_file(fpath, fname)
                if ftype:
                    entries.append((fpath, ftype))

        return entries

    def _classify_file(self, fpath: Path, fname: str) -> Optional[str]:
        """Classify a file as TEST, DOCUMENTATION, AGENT_MEMORY, or None."""
        fname_lower = fname.lower()

        # Agent context/memory files
        if fname_lower in AGENT_CONTEXT_NAMES:
            return "AGENT_MEMORY"
        for pattern in AGENT_MEMORY_PATTERNS:
            if pattern.search(str(fpath)):
                return "AGENT_MEMORY"

        # Test files
        if fname.endswith(".py") and (fname.startswith("test_") or fname.endswith("_test.py")):
            return "TEST"

        # Documentation files
        if fname_lower == "readme.md":
            return "DOCUMENTATION"
        if fname_lower.endswith(".md"):
            # Check if in a docs/ directory
            rel = fpath.relative_to(self.repo_root)
            parts = [p.lower() for p in rel.parts]
            if "docs" in parts or "doc" in parts or "documentation" in parts:
                return "DOCUMENTATION"

        return None

    def _parse_drift_identifiers(self, drift: ContractDrift) -> tuple[Optional[str], Optional[str]]:
        """Extract the schema/route name and field/param name from a drift identifier.

        Examples:
          "UserCreate.tier"  -> ("UserCreate", "tier")
          "POST /v1/users"   -> ("POST /v1/users", None)
          "POST /v1/users param:tier"  -> ("/v1/users", "tier")
        """
        ident = drift.identifier

        if "." in ident and "param:" not in ident:
            # Schema field drift: "UserCreate.tier"
            parts = ident.split(".", 1)
            return parts[0], parts[1]

        if "param:" in ident:
            # Route param drift: "POST /v1/users param:tier"
            route_part, param_part = ident.rsplit(" param:", 1)
            # Extract just the path from "POST /v1/users"
            route_path = route_part.split(" ", 1)[-1] if " " in route_part else route_part
            return route_path, param_part

        if " " in ident and ident.split(" ")[0] in {"GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"}:
            # Route drift: "POST /v1/users"
            route_path = ident.split(" ", 1)[1]
            return route_path, None

        # Schema-level drift (SCHEMA_ADDED, SCHEMA_REMOVED)
        return ident, None

    def _check_file(
        self,
        fpath: Path,
        ftype: str,
        drift: ContractDrift,
        schema_name: str,
        field_name: Optional[str],
        result: BlastRadiusResult,
    ) -> None:
        """Check if a file references the schema/route and is missing the drifted field."""
        try:
            content = fpath.read_text(encoding="utf-8", errors="ignore")
        except (OSError, PermissionError):
            return

        # Must reference the schema/route name
        if schema_name not in content:
            return

        # For field-level drifts, the file is stale if it references the schema
        # but does NOT contain the new/changed field name
        if field_name and drift.category in {
            "FIELD_ADDED",
            "FIELD_TYPE_CHANGED",
            "FIELD_REQUIRED_CHANGED",
            "ROUTE_PARAM_ADDED",
            "ROUTE_PARAM_TYPE_CHANGED",
        }:
            if field_name in content:
                # File already references the new field -- not stale
                return

            reason = self._build_reason(drift, ftype, schema_name, field_name)
            suggested_action = self._build_suggestion(drift, ftype, schema_name, field_name)

            result.impacted_artifacts.append(ImpactedArtifact(
                file_path=str(fpath),
                artifact_type=ftype,
                reason=reason,
                stale_reference=drift.identifier,
                suggested_action=suggested_action,
            ))

        elif drift.category in {"FIELD_REMOVED", "ROUTE_REMOVED", "ROUTE_PARAM_REMOVED"}:
            # For removals: the file is stale if it still references the removed field/route
            removed_name = field_name if field_name else schema_name
            if removed_name in content:
                reason = self._build_reason(drift, ftype, schema_name, field_name)
                suggested_action = self._build_suggestion(drift, ftype, schema_name, field_name)

                result.impacted_artifacts.append(ImpactedArtifact(
                    file_path=str(fpath),
                    artifact_type=ftype,
                    reason=reason,
                    stale_reference=drift.identifier,
                    suggested_action=suggested_action,
                ))

    def _build_reason(
        self,
        drift: ContractDrift,
        ftype: str,
        schema_name: str,
        field_name: Optional[str],
    ) -> str:
        """Build a human-readable reason for the impact."""
        type_label = {"TEST": "Test file", "DOCUMENTATION": "Documentation", "AGENT_MEMORY": "Agent context"}
        label = type_label.get(ftype, "File")

        if drift.category == "FIELD_ADDED":
            return (
                f"{label} references '{schema_name}' but is missing the "
                f"newly added field '{field_name}'"
            )
        elif drift.category == "FIELD_REMOVED":
            return (
                f"{label} still references removed field "
                f"'{schema_name}.{field_name}'"
            )
        elif drift.category == "FIELD_TYPE_CHANGED":
            return (
                f"{label} references '{schema_name}.{field_name}' whose "
                f"type has changed"
            )
        elif drift.category in {"ROUTE_PARAM_ADDED", "ROUTE_PARAM_TYPE_CHANGED"}:
            return (
                f"{label} references route '{schema_name}' but is missing "
                f"the changed parameter '{field_name}'"
            )
        elif drift.category in {"ROUTE_REMOVED", "ROUTE_PARAM_REMOVED"}:
            return (
                f"{label} still references removed "
                f"'{drift.identifier}'"
            )
        return f"{label} is impacted by drift: {drift.details}"

    def _build_suggestion(
        self,
        drift: ContractDrift,
        ftype: str,
        schema_name: str,
        field_name: Optional[str],
    ) -> str:
        """Build a suggested action to remediate the stale reference."""
        if ftype == "TEST":
            if drift.category == "FIELD_ADDED":
                return (
                    f"Update test fixtures and assertions to include the "
                    f"new field '{field_name}' on '{schema_name}'"
                )
            elif drift.category == "FIELD_REMOVED":
                return (
                    f"Remove references to deleted field "
                    f"'{field_name}' from '{schema_name}' test fixtures"
                )
            elif drift.category == "FIELD_TYPE_CHANGED":
                return (
                    f"Update test fixtures to use the new type for "
                    f"'{schema_name}.{field_name}'"
                )
            return f"Update test to reflect drift: {drift.details}"

        elif ftype == "DOCUMENTATION":
            if drift.category == "FIELD_ADDED":
                return (
                    f"Add documentation for the new field '{field_name}' "
                    f"on '{schema_name}'"
                )
            elif drift.category == "FIELD_REMOVED":
                return (
                    f"Remove documentation references to deleted field "
                    f"'{field_name}' on '{schema_name}'"
                )
            return f"Update documentation to reflect drift: {drift.details}"

        elif ftype == "AGENT_MEMORY":
            if drift.category == "FIELD_ADDED":
                return (
                    f"Update agent context to include the new field "
                    f"'{field_name}' in the '{schema_name}' contract definition"
                )
            elif drift.category == "FIELD_REMOVED":
                return (
                    f"Remove agent context references to deleted field "
                    f"'{field_name}' on '{schema_name}'"
                )
            return f"Update agent context to reflect drift: {drift.details}"

        return f"Review and update for drift: {drift.details}"
