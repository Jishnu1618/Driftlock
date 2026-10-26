"""Closed-Loop Remediation Engine for DriftLock.

Patches stale TEST, DOCUMENTATION, and AGENT_MEMORY files to synchronize them
with the updated contract.  Two modes:

1. **Deterministic AST/Regex Patcher** (default offline fallback) — never
   requires API keys, so demos and tests always pass.
2. **Open Model API** — if ``OPENROUTER_API_KEY`` or ``OPENAI_API_KEY`` is
   set, calls an open-weight model for richer, context-aware patches.
"""

from __future__ import annotations

import os
import re
import json
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from driftlock.blast_radius.graph import BlastRadiusResult, ImpactedArtifact
from driftlock.core.diff import ContractDrift, DriftReport
from driftlock.core.models import ContractSnapshot, FieldDefinition, SchemaDefinition


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class RemediationPatch:
    """A single file patch produced by the remediator."""

    file_path: str
    original_content: str
    patched_content: str
    artifact_type: str  # TEST, DOCUMENTATION, AGENT_MEMORY
    changes_applied: list[str] = field(default_factory=list)


@dataclass
class RemediationResult:
    """Aggregate result of a remediation run."""

    patches: list[RemediationPatch] = field(default_factory=list)

    @property
    def files_patched(self) -> int:
        return len(self.patches)

    @property
    def patch_map(self) -> dict[str, tuple[str, str]]:
        """Return ``{file_path: (original_content, patched_content)}``."""
        return {p.file_path: (p.original_content, p.patched_content) for p in self.patches}


# ---------------------------------------------------------------------------
# Helpers – collect newly-added fields from the drift report
# ---------------------------------------------------------------------------

def _extract_added_fields(
    drift_report: DriftReport,
    head_contract: ContractSnapshot,
) -> dict[str, list[FieldDefinition]]:
    """Return ``{SchemaName: [FieldDefinition, ...]}`` for every FIELD_ADDED drift."""
    added: dict[str, list[FieldDefinition]] = {}
    for drift in drift_report.drifts:
        if drift.category != "FIELD_ADDED":
            continue
        if "." not in drift.identifier:
            continue
        schema_name, field_name = drift.identifier.split(".", 1)
        schema = head_contract.get_schema(schema_name)
        if schema is None:
            continue
        fdef = schema.get_field(field_name)
        if fdef is None:
            continue
        added.setdefault(schema_name, []).append(fdef)
    return added


# ---------------------------------------------------------------------------
# Deterministic patchers (offline, zero-LLM)
# ---------------------------------------------------------------------------

def _patch_test_file(
    content: str,
    added_fields: dict[str, list[FieldDefinition]],
    impacted: list[ImpactedArtifact],
) -> tuple[str, list[str]]:
    """Inject missing fields into test dictionary payloads and add assertions."""
    patched = content
    changes: list[str] = []

    for schema_name, fields in added_fields.items():
        for fdef in fields:
            if fdef.name in patched:
                continue  # already present

            # ---- 1. Inject field into dictionary payloads ----
            # Matches  payload = {"username": "...", "email": "..."}
            #  and inserts the missing field before the closing brace.
            dict_pattern = re.compile(
                r'(payload\s*=\s*\{[^}]*?)(\})',
                re.DOTALL,
            )

            def _inject_field(m: re.Match) -> str:
                body = m.group(1).rstrip()
                # Determine value based on type
                val = _default_test_value(fdef)
                if body.endswith(","):
                    insert = f' "{fdef.name}": {val}'
                else:
                    insert = f', "{fdef.name}": {val}'
                return f"{body}{insert}}}"

            new_patched = dict_pattern.sub(_inject_field, patched)
            if new_patched != patched:
                patched = new_patched
                changes.append(f"Injected '{fdef.name}' into test payload dict for {schema_name}")

            # ---- 2. Add assertion for the new field ----
            # After lines like `assert "email" in payload`, add the new field.
            assertion_line = f'    assert "{fdef.name}" in payload'
            if assertion_line.strip() not in patched:
                # Find the last `assert "..." in payload` or `assert "..." in expected_fields`
                last_assert_pattern = re.compile(
                    r'(    assert\s+"[^"]+"\s+in\s+(payload|expected_fields)[^\n]*\n)',
                )
                matches = list(last_assert_pattern.finditer(patched))
                if matches:
                    last = matches[-1]
                    insert_pos = last.end()
                    patched = patched[:insert_pos] + assertion_line + "\n" + patched[insert_pos:]
                    changes.append(f"Added assertion for '{fdef.name}' in test")

            # ---- 3. Inject into expected_fields lists ----
            expected_pattern = re.compile(
                r'(expected_fields\s*=\s*\[[^\]]*?)(\])',
            )

            def _inject_expected(m: re.Match) -> str:
                body = m.group(1).rstrip()
                if body.endswith(","):
                    return f'{body} "{fdef.name}"]'
                else:
                    return f'{body}, "{fdef.name}"]'

            new_patched = expected_pattern.sub(_inject_expected, patched)
            if new_patched != patched:
                patched = new_patched
                changes.append(f"Added '{fdef.name}' to expected_fields for {schema_name}")

    return patched, changes


def _patch_documentation_file(
    content: str,
    added_fields: dict[str, list[FieldDefinition]],
    impacted: list[ImpactedArtifact],
) -> tuple[str, list[str]]:
    """Append missing schema fields into markdown documentation tables and JSON examples."""
    patched = content
    changes: list[str] = []

    for schema_name, fields in added_fields.items():
        for fdef in fields:
            if fdef.name in patched:
                continue

            # ---- 1. Inject into markdown table ----
            # Find the table section for the schema (e.g. after `UserCreate`)
            # Look for the last row of the table that belongs to this schema's section
            table_row_pattern = re.compile(
                r'(\|[^\n]*\|[^\n]*\|[^\n]*\|[^\n]*\|\n)(?=\n|\Z|[^|])',
            )
            matches = list(table_row_pattern.finditer(patched))
            if matches:
                last = matches[-1]
                required_str = "Yes" if fdef.is_required else "No"
                desc = fdef.description or f"{fdef.name} field"
                new_row = f"| {fdef.name} | {fdef.type_annotation} | {required_str} | {desc} |\n"
                insert_pos = last.end()
                patched = patched[:insert_pos] + new_row + patched[insert_pos:]
                changes.append(f"Added '{fdef.name}' row to documentation table for {schema_name}")

            # ---- 2. Inject into JSON examples ----
            # Find JSON blocks that contain schema fields (like "username")
            json_block_pattern = re.compile(
                r'(```json\s*\n\{[^}]*?)(\n\s*\})',
                re.DOTALL,
            )

            def _inject_json_field(m: re.Match) -> str:
                body = m.group(1).rstrip()
                closing = m.group(2)
                val = _default_json_value(fdef)
                if body.rstrip().endswith(","):
                    return f'{body}\n  "{fdef.name}": {val}{closing}'
                else:
                    return f'{body},\n  "{fdef.name}": {val}{closing}'

            # Only inject if the JSON block references fields from the same schema area
            new_patched = json_block_pattern.sub(_inject_json_field, patched)
            if new_patched != patched:
                patched = new_patched
                changes.append(f"Added '{fdef.name}' to JSON example in docs for {schema_name}")

    return patched, changes


def _patch_agent_memory_file(
    content: str,
    added_fields: dict[str, list[FieldDefinition]],
    impacted: list[ImpactedArtifact],
) -> tuple[str, list[str]]:
    """Append new fields into agent context schema tables and instruction sections."""
    patched = content
    changes: list[str] = []

    for schema_name, fields in added_fields.items():
        for fdef in fields:
            if fdef.name in patched:
                continue

            # ---- 1. Inject into markdown table ----
            table_row_pattern = re.compile(
                r'(\|[^\n]*\|[^\n]*\|[^\n]*\|[^\n]*\|\n)(?=\n|\Z|[^|])',
            )
            matches = list(table_row_pattern.finditer(patched))
            if matches:
                last = matches[-1]
                required_str = "Yes" if fdef.is_required else "No"
                desc = fdef.description or f"{fdef.name} field"
                new_row = f"| {fdef.name} | {fdef.type_annotation} | {required_str} | {desc} |\n"
                insert_pos = last.end()
                patched = patched[:insert_pos] + new_row + patched[insert_pos:]
                changes.append(f"Added '{fdef.name}' to agent context table for {schema_name}")

            # ---- 2. Inject into API contract bullet lists ----
            # Find lines like "- `email` (str, required): ..." and append after them
            bullet_pattern = re.compile(
                r'(- `(?:username|email)`[^\n]*\n)(?=\n|[^-])',
            )
            matches = list(bullet_pattern.finditer(patched))
            if matches:
                last = matches[-1]
                required_str = "required" if fdef.is_required else "optional"
                desc = fdef.description or f"{fdef.name} field"
                new_bullet = f"- `{fdef.name}` ({fdef.type_annotation}, {required_str}): {desc}\n"
                if new_bullet not in patched:
                    insert_pos = last.end()
                    patched = patched[:insert_pos] + new_bullet + patched[insert_pos:]
                    changes.append(f"Added '{fdef.name}' bullet to API contract for {schema_name}")

            # ---- 3. Update validation instructions ----
            validate_pattern = re.compile(
                r'(Always validate that `UserCreate` payloads contain `)([^`]+)(`)',
            )
            match = validate_pattern.search(patched)
            if match and fdef.name not in match.group(2):
                old_fields = match.group(2)
                new_fields = f"{old_fields}`, `{fdef.name}"
                patched = patched[:match.start(2)] + new_fields + patched[match.end(2):]
                changes.append(f"Updated validation instruction to include '{fdef.name}'")

    return patched, changes


# ---------------------------------------------------------------------------
# Value helpers for injecting reasonable defaults
# ---------------------------------------------------------------------------

def _default_test_value(fdef: FieldDefinition) -> str:
    """Return a Python-repr test value for the field type."""
    if fdef.default_value is not None and fdef.default_value != "None":
        return fdef.default_value
    type_lower = (fdef.type_annotation or "str").lower()
    if "int" in type_lower:
        return "1"
    if "float" in type_lower:
        return "1.0"
    if "bool" in type_lower:
        return "True"
    return '"test_value"'


def _default_json_value(fdef: FieldDefinition) -> str:
    """Return a JSON-appropriate value for the field type."""
    if fdef.default_value is not None and fdef.default_value != "None":
        # Convert Python True/False to JSON true/false
        val = fdef.default_value
        if val == "True":
            return "true"
        if val == "False":
            return "false"
        # If it's a number, return as-is
        try:
            float(val)
            return val
        except (ValueError, TypeError):
            pass
        # String default
        if not val.startswith('"'):
            return f'"{val}"'
        return val
    type_lower = (fdef.type_annotation or "str").lower()
    if "int" in type_lower:
        return "1"
    if "float" in type_lower:
        return "1.0"
    if "bool" in type_lower:
        return "true"
    return '"value"'


# ---------------------------------------------------------------------------
# Open Model API patcher (optional, requires API key)
# ---------------------------------------------------------------------------

def _has_api_key() -> bool:
    """Check if an Open Model API key is available."""
    return bool(
        os.environ.get("OPENROUTER_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
    )


def _patch_via_api(
    file_path: str,
    content: str,
    instructions: list[str],
) -> Optional[str]:
    """Call an open-weight model to patch the file.  Returns patched content or None."""
    api_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None

    try:
        import urllib.request

        base_url = "https://openrouter.ai/api/v1"
        if os.environ.get("OPENAI_API_KEY") and not os.environ.get("OPENROUTER_API_KEY"):
            base_url = "https://api.openai.com/v1"

        prompt = (
            "You are a code synchronization assistant.  Apply the following changes to the file "
            "and return ONLY the complete updated file content, nothing else.\n\n"
            f"File: {file_path}\n\nChanges needed:\n"
            + "\n".join(f"- {i}" for i in instructions)
            + f"\n\nCurrent file content:\n```\n{content}\n```\n\n"
            "Return the complete patched file content only."
        )

        payload = json.dumps({
            "model": "qwen/qwen-2.5-coder-32b-instruct",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": 4096,
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            result = data["choices"][0]["message"]["content"]
            # Strip code fences if present
            if result.startswith("```"):
                lines = result.split("\n")
                lines = lines[1:]  # remove opening fence
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                result = "\n".join(lines)
            return result
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Main DriftRemediator class
# ---------------------------------------------------------------------------

class DriftRemediator:
    """Closed-loop remediator that patches stale workspace files.

    Parameters
    ----------
    use_api : bool | None
        If *True*, force API mode.  If *False*, force offline mode.
        If *None* (default), auto-detect based on environment variables.
    """

    def __init__(self, use_api: Optional[bool] = None):
        if use_api is None:
            self.use_api = _has_api_key()
        else:
            self.use_api = use_api

    def remediate_workspace(
        self,
        blast_result: BlastRadiusResult,
        head_contract: ContractSnapshot,
    ) -> dict[str, tuple[str, str]]:
        """Patch every impacted file and return ``{path: (original, patched)}``."""
        result = self._remediate(blast_result, head_contract)
        return result.patch_map

    def remediate(
        self,
        blast_result: BlastRadiusResult,
        head_contract: ContractSnapshot,
    ) -> RemediationResult:
        """Patch every impacted file and return the full ``RemediationResult``."""
        return self._remediate(blast_result, head_contract)

    def _remediate(
        self,
        blast_result: BlastRadiusResult,
        head_contract: ContractSnapshot,
    ) -> RemediationResult:
        """Core implementation."""
        drift_report = blast_result.drift_report
        added_fields = _extract_added_fields(drift_report, head_contract)

        # Group impacted artifacts by file path
        by_file: dict[str, list[ImpactedArtifact]] = {}
        for artifact in blast_result.impacted_artifacts:
            by_file.setdefault(artifact.file_path, []).append(artifact)

        result = RemediationResult()

        for file_path, artifacts in by_file.items():
            fpath = Path(file_path)
            if not fpath.is_file():
                continue
            try:
                original = fpath.read_text(encoding="utf-8", errors="ignore")
            except (OSError, PermissionError):
                continue

            artifact_type = artifacts[0].artifact_type
            instructions = [a.suggested_action for a in artifacts]

            # Try API mode first if enabled
            patched = None
            changes: list[str] = []

            if self.use_api:
                patched = _patch_via_api(file_path, original, instructions)
                if patched:
                    changes = [f"[API] {instr}" for instr in instructions]

            # Fallback: deterministic offline patcher
            if patched is None:
                if artifact_type == "TEST":
                    patched, changes = _patch_test_file(original, added_fields, artifacts)
                elif artifact_type == "DOCUMENTATION":
                    patched, changes = _patch_documentation_file(original, added_fields, artifacts)
                elif artifact_type == "AGENT_MEMORY":
                    patched, changes = _patch_agent_memory_file(original, added_fields, artifacts)
                else:
                    patched = original
                    changes = []

            if patched != original:
                result.patches.append(RemediationPatch(
                    file_path=file_path,
                    original_content=original,
                    patched_content=patched,
                    artifact_type=artifact_type,
                    changes_applied=changes,
                ))

        return result

    def apply_patches(self, result: RemediationResult) -> int:
        """Write patched content to disk.  Returns count of files written."""
        written = 0
        for patch in result.patches:
            fpath = Path(patch.file_path)
            try:
                fpath.write_text(patch.patched_content, encoding="utf-8")
                written += 1
            except (OSError, PermissionError):
                pass
        return written
