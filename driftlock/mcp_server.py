"""Thin MCP adapter for DriftLock (stdio transport).

The adapter deliberately does not reimplement any drift logic. Audits and the
fixture demo are executed through the existing CLI so the machine-readable
report and CI exit semantics are identical to the command line. Authorized
remediation reuses :class:`driftlock.sync.remediator.DriftRemediator` in
offline mode (no LLM, no network).

Filesystem access is limited to ``DRIFTLOCK_MCP_WORKSPACE``. All supplied
paths are resolved and must remain inside that workspace, which rejects path
traversal and symlink escapes.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Any

import anyio
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from driftlock import __version__
from driftlock.blast_radius.graph import BlastRadiusMapper
from driftlock.core.diff import compute_contract_diff
from driftlock.core.parser import parse_file
from driftlock.sync.remediator import DriftRemediator

WORKSPACE_ENV = "DRIFTLOCK_MCP_WORKSPACE"
AUDIT_TIMEOUT_SECONDS = 120
FIX_TIMEOUT_SECONDS = 120
MAX_DIAGNOSTICS = 200

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = PACKAGE_ROOT / "fixtures" / "demo_repo"

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

server = MCPServer(
    name="driftlock",
    version=__version__,
    instructions=(
        "DriftLock detects deterministic API contract drift between a base and "
        "head contract and maps stale [TEST], [DOCS], and [AGENT_MEMORY] files. "
        "Audit and demo tools are read-only. Fixing requires explicit "
        f"authorization. Filesystem access is limited to ${WORKSPACE_ENV}."
    ),
)


# ---------------------------------------------------------------------------
# Workspace and process helpers
# ---------------------------------------------------------------------------


def _clean(text: str) -> str:
    return _ANSI.sub("", text)


def _diagnostics(stderr: str) -> list[str]:
    lines = [_clean(line).rstrip() for line in stderr.splitlines()]
    return [line for line in lines if line.strip()][:MAX_DIAGNOSTICS]


def authorized_workspace() -> Path:
    """Return the single workspace this server may touch."""
    raw = os.environ.get(WORKSPACE_ENV, "").strip()
    if not raw:
        raise ToolError(
            f"{WORKSPACE_ENV} is not set. Start the server with an absolute "
            "project workspace, for example "
            f"{WORKSPACE_ENV}=/path/to/project python -m driftlock.mcp_server"
        )
    root = Path(raw).expanduser()
    if not root.is_dir():
        raise ToolError(f"{WORKSPACE_ENV} does not point to a directory: {raw}")
    return root.resolve()


def _resolve_within(
    workspace: Path,
    value: str,
    *,
    label: str,
    kind: str,
    relative_to: Path | None = None,
) -> Path:
    """Canonicalize *value* and require it to stay inside *workspace*.

    Relative paths are interpreted from *relative_to* (usually the repository
    root) and still checked against the workspace after resolution.
    """
    if not isinstance(value, str) or not value.strip():
        raise ToolError(f"{label} must be a non-empty path")
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = (relative_to or workspace) / candidate
    resolved = candidate.resolve()
    if resolved != workspace and workspace not in resolved.parents:
        raise ToolError(
            f"{label} resolves outside the authorized workspace: {resolved}"
        )
    if kind == "file" and not resolved.is_file():
        raise ToolError(f"{label} is not a file: {resolved}")
    if kind == "dir" and not resolved.is_dir():
        raise ToolError(f"{label} is not a directory: {resolved}")
    return resolved


def _run_cli(args: list[str], *, cwd: Path, timeout: float) -> subprocess.CompletedProcess:
    """Run the DriftLock CLI as an argument list (never a shell string)."""
    env = os.environ.copy()
    parts = [str(PACKAGE_ROOT)]
    if env.get("PYTHONPATH"):
        parts.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(parts)
    env.setdefault("PYTHONIOENCODING", "utf-8")

    try:
        return subprocess.run(
            [sys.executable, "-m", "driftlock.cli.main", *args],
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ToolError(
            f"DriftLock command timed out after {timeout:g}s: {' '.join(args)}"
        ) from exc
    except OSError as exc:
        raise ToolError(f"Could not start the DriftLock CLI: {exc}") from exc


def _timeout_error(action: str, seconds: float) -> ToolError:
    return ToolError(f"{action} timed out after {seconds:g}s")


def _parse_report(proc: subprocess.CompletedProcess, *, action: str) -> dict[str, Any]:
    raw = proc.stdout or ""
    try:
        report = json.loads(raw)
    except json.JSONDecodeError as exc:
        detail = _clean(proc.stderr or "").strip()
        raise ToolError(
            f"{action} did not produce a valid JSON report "
            f"(exit {proc.returncode}): {detail or exc}"
        ) from exc
    if not isinstance(report, dict):
        raise ToolError(f"{action} returned JSON that is not an object")
    return report


def _audit_via_cli(
    *,
    repository_root: Path,
    base_contract: Path,
    head_contract: Path,
    ci: bool,
    mode: str,
) -> dict[str, Any]:
    args = [
        "audit",
        "--base", str(base_contract),
        "--head", str(head_contract),
        "--repo", str(repository_root),
        "--json",
    ]
    if ci:
        args.append("--ci")

    # Run from the DriftLock checkout so a target repository cannot shadow the package.
    proc = _run_cli(args, cwd=PACKAGE_ROOT, timeout=AUDIT_TIMEOUT_SECONDS)
    report = _parse_report(proc, action="DriftLock audit")
    return {
        "mode": mode,
        "is_production_audit": mode == "production_audit",
        "repository_root": str(repository_root),
        "exit_code": proc.returncode,
        "report": report,
        "diagnostics": _diagnostics(proc.stderr or ""),
    }


def _diff_text(original: str, patched: str, path: Path) -> str:
    return "".join(difflib.unified_diff(
        original.splitlines(keepends=True),
        patched.splitlines(keepends=True),
        fromfile=f"a/{path.name}",
        tofile=f"b/{path.name}",
        lineterm="",
    ))


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@server.tool(
    name="driftlock_audit",
    title="DriftLock audit (read-only)",
    annotations=ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
    ),
    description=(
        "Read-only deterministic API contract audit. Compares a base and head "
        "Python contract file and reports drifts plus stale TEST, DOCS, and "
        "AGENT_MEMORY artifacts. Returns the same versioned JSON report as the "
        "CLI. With ci=true, exit_code follows the CI gate (1 on breaking drift "
        "or stale artifacts, 0 otherwise). Never modifies files."
    ),
)
async def driftlock_audit(
    repository_root: Annotated[
        str,
        Field(description="Repository root to scan; must be inside the authorized workspace."),
    ],
    base_contract: Annotated[
        str,
        Field(description="Old/base Python contract file; must be inside the authorized workspace."),
    ],
    head_contract: Annotated[
        str,
        Field(description="New/head Python contract file; must be inside the authorized workspace."),
    ],
    ci: Annotated[
        bool,
        Field(description="Apply CI gate semantics to exit_code. Does not modify files."),
    ] = False,
) -> dict[str, Any]:
    workspace = authorized_workspace()
    repo = _resolve_within(workspace, repository_root, label="repository_root", kind="dir")
    base = _resolve_within(workspace, base_contract, label="base_contract", kind="file", relative_to=repo)
    head = _resolve_within(workspace, head_contract, label="head_contract", kind="file", relative_to=repo)

    try:
        with anyio.fail_after(AUDIT_TIMEOUT_SECONDS + 5):
            return await anyio.to_thread.run_sync(
                lambda: _audit_via_cli(
                    repository_root=repo,
                    base_contract=base,
                    head_contract=head,
                    ci=ci,
                    mode="production_audit",
                ),
                abandon_on_cancel=True,
            )
    except TimeoutError as exc:
        raise _timeout_error("driftlock_audit", AUDIT_TIMEOUT_SECONDS) from exc


@server.tool(
    name="driftlock_demo",
    title="DriftLock fixture demo (read-only)",
    annotations=ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
    ),
    description=(
        "Run the bundled fixture demonstration. This is a labeled fixture demo, "
        "NOT a production audit. Read-only; uses fixtures/demo_repo."
    ),
)
async def driftlock_demo() -> dict[str, Any]:
    if not FIXTURE_DIR.is_dir():
        raise ToolError(
            f"Bundled fixtures are missing at {FIXTURE_DIR}. Run the adapter from "
            "a DriftLock source checkout."
        )
    base = FIXTURE_DIR / "api_base.py"
    head = FIXTURE_DIR / "api_head.py"
    if not base.is_file() or not head.is_file():
        raise ToolError(f"Fixture contracts are missing under {FIXTURE_DIR}")

    try:
        with anyio.fail_after(AUDIT_TIMEOUT_SECONDS + 5):
            result = await anyio.to_thread.run_sync(
                lambda: _audit_via_cli(
                    repository_root=FIXTURE_DIR,
                    base_contract=base,
                    head_contract=head,
                    ci=False,
                    mode="fixture_demo",
                ),
                abandon_on_cancel=True,
            )
    except TimeoutError as exc:
        raise _timeout_error("driftlock_demo", AUDIT_TIMEOUT_SECONDS) from exc
    result["label"] = (
        "Bundled fixture demonstration (fixtures/demo_repo); not a production audit"
    )
    return result


@server.tool(
    name="driftlock_apply_fix",
    title="DriftLock apply fix (writes files)",
    annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False
    ),
    description=(
        "MUTATES FILES. Applies DriftLock's deterministic offline remediation to "
        "stale TEST, DOCS, and AGENT_MEMORY files, then re-audits. Requires "
        "authorize=true. Returns unified diffs, changed files, and verification "
        "status. Never called by driftlock_audit."
    ),
)
async def driftlock_apply_fix(
    repository_root: Annotated[
        str,
        Field(description="Repository root whose artifacts will be rewritten."),
    ],
    base_contract: Annotated[
        str,
        Field(description="Old/base Python contract file inside the authorized workspace."),
    ],
    head_contract: Annotated[
        str,
        Field(description="New/head Python contract file inside the authorized workspace."),
    ],
    authorize: Annotated[
        bool,
        Field(description="Must be true to modify files. False returns an error."),
    ] = False,
) -> dict[str, Any]:
    if authorize is not True:
        raise ToolError(
            "driftlock_apply_fix modifies workspace files. Pass authorize=true "
            "after reviewing the audit report."
        )

    workspace = authorized_workspace()
    repo = _resolve_within(workspace, repository_root, label="repository_root", kind="dir")
    base = _resolve_within(workspace, base_contract, label="base_contract", kind="file", relative_to=repo)
    head = _resolve_within(workspace, head_contract, label="head_contract", kind="file", relative_to=repo)

    try:
        with anyio.fail_after(FIX_TIMEOUT_SECONDS):
            return await anyio.to_thread.run_sync(
                lambda: _apply_fix(repo, base, head), abandon_on_cancel=True
            )
    except TimeoutError as exc:
        raise _timeout_error("driftlock_apply_fix", FIX_TIMEOUT_SECONDS) from exc


def _apply_fix(repo: Path, base: Path, head: Path) -> dict[str, Any]:
    base_contract = parse_file(base)
    head_contract = parse_file(head)
    drift_report = compute_contract_diff(base_contract, head_contract)
    blast = BlastRadiusMapper(str(repo)).scan_blast_radius(drift_report)

    summary = {
        "total_drifts": len(drift_report.drifts),
        "breaking_drifts": len(drift_report.breaking_drifts),
        "impacted_files_before": blast.total_impacted_files,
    }

    if not blast.impacted_artifacts:
        return {
            "mode": "apply_fix",
            "authorized": True,
            "exit_code": 0,
            "files_changed": [],
            "diffs": [],
            "finding_summary": summary,
            "verification": {
                "remaining_impacted_files": 0,
                "synchronized": True,
                "files_written": 0,
            },
            "diagnostics": ["No stale artifacts to remediate."],
        }

    # Force offline remediation: no LLM and no network calls.
    remediator = DriftRemediator(use_api=False)
    remediation = remediator.remediate(blast, head_contract)

    diffs: list[dict[str, Any]] = []
    validated: list[tuple[Any, Path]] = []
    for patch in remediation.patches:
        target = _resolve_within(
            repo, patch.file_path, label="remediation target", kind="file"
        )
        patch.file_path = str(target)  # write only the canonical, validated path
        validated.append((patch, target))
        diffs.append({
            "file_path": str(target),
            "artifact_type": patch.artifact_type,
            "changes_applied": list(patch.changes_applied),
            "unified_diff": _diff_text(patch.original_content, patch.patched_content, target),
        })

    written = remediator.apply_patches(remediation)

    changed: list[str] = []
    diagnostics = [f"Applied {written} patch(es) with the deterministic offline remediator."]
    for patch, target in validated:
        try:
            if target.read_text(encoding="utf-8") == patch.patched_content:
                changed.append(str(target))
            else:
                diagnostics.append(f"Patch verification mismatch: {target}")
        except OSError as exc:
            diagnostics.append(f"Could not verify {target}: {exc}")

    remaining = BlastRadiusMapper(str(repo)).scan_blast_radius(drift_report).total_impacted_files
    synchronized = remaining == 0
    diagnostics.append(
        f"Post-remediation re-audit: {remaining} stale artifact(s) remaining."
    )

    return {
        "mode": "apply_fix",
        "authorized": True,
        "exit_code": 0 if synchronized else 1,
        "files_changed": changed,
        "diffs": diffs,
        "finding_summary": summary,
        "verification": {
            "remaining_impacted_files": remaining,
            "synchronized": synchronized,
            "files_written": written,
        },
        "diagnostics": diagnostics,
    }


def main() -> None:
    """Run the MCP server over stdio (the supported transport)."""
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
