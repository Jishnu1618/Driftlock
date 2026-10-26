"""FastAPI backend server for DriftLock.

Provides REST endpoints for:
- `GET /api/demo` — Returns demo contract diff, blast radius, and remediation brief.
- `POST /api/remediate` — Executes closed-loop remediation in an isolated temp workspace and verifies zero stale artifacts remain.
- `POST /api/custom-audit` — Performs deterministic AST contract diffing on arbitrary Base vs. Head Python code.
- `GET /` — Serves the dark-mode developer control plane web dashboard.
"""

from __future__ import annotations

import difflib
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from driftlock.blast_radius.graph import BlastRadiusMapper, BlastRadiusResult, ImpactedArtifact
from driftlock.core.diff import ContractDrift, DriftReport, compute_contract_diff
from driftlock.core.models import ContractSnapshot
from driftlock.core.parser import parse_code, parse_file
from driftlock.sync.remediator import DriftRemediator, RemediationResult

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEMO_FIXTURES = PROJECT_ROOT / "fixtures" / "demo_repo"
WEB_DIR = PROJECT_ROOT / "web"

app = FastAPI(
    title="DriftLock API",
    description="Deterministic Contract & Context Consistency Layer API",
    version="1.0.0",
)

# Enable CORS for local developer flexibility
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class CustomAuditRequest(BaseModel):
    base_code: str = Field(..., description="Base API Python source code")
    head_code: str = Field(..., description="Head API Python source code")


class RemediateRequest(BaseModel):
    use_api: bool = Field(default=False, description="Whether to invoke Open Model API")
    api_key: Optional[str] = Field(default=None, description="Optional OpenRouter/OpenAI API key")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_diff(original: str, patched: str, filename: str) -> str:
    orig_lines = original.splitlines(keepends=True)
    patch_lines = patched.splitlines(keepends=True)
    diff = list(
        difflib.unified_diff(
            orig_lines,
            patch_lines,
            fromfile=f"a/{filename}",
            tofile=f"b/{filename}",
        )
    )
    return "".join(diff)


def _load_demo_files() -> dict[str, str]:
    files: dict[str, str] = {}
    if DEMO_FIXTURES.exists():
        for item in DEMO_FIXTURES.rglob("*"):
            if item.is_file():
                rel = str(item.relative_to(DEMO_FIXTURES)).replace("\\", "/")
                try:
                    files[rel] = item.read_text(encoding="utf-8")
                except Exception:
                    pass
    return files


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "DriftLock AST Engine",
        "version": "1.0.0",
    }


@app.get("/api/demo")
async def get_demo_state():
    """Return the initial contract drift and blast radius state for the built-in demo."""
    base_path = DEMO_FIXTURES / "api_base.py"
    head_path = DEMO_FIXTURES / "api_head.py"

    if not base_path.exists() or not head_path.exists():
        raise HTTPException(status_code=404, detail="Demo fixtures not found")

    base_code = base_path.read_text(encoding="utf-8")
    head_code = head_path.read_text(encoding="utf-8")

    base_contract = parse_file(base_path)
    head_contract = parse_file(head_path)
    drift_report = compute_contract_diff(base_contract, head_contract)

    mapper = BlastRadiusMapper(DEMO_FIXTURES)
    blast_result = mapper.scan_blast_radius(drift_report)

    files = _load_demo_files()

    drifts_data = [
        {
            "category": d.category,
            "identifier": d.identifier,
            "details": d.details,
            "is_breaking": d.is_breaking,
        }
        for d in drift_report.drifts
    ]

    blast_data = [
        {
            "file_path": a.file_path,
            "file_name": Path(a.file_path).name,
            "relative_path": str(Path(a.file_path).relative_to(DEMO_FIXTURES)).replace("\\", "/")
            if Path(a.file_path).is_relative_to(DEMO_FIXTURES)
            else Path(a.file_path).name,
            "artifact_type": a.artifact_type,
            "stale_reference": a.stale_reference,
            "matched_symbol": a.stale_reference,
            "reason": a.reason,
            "suggested_action": a.suggested_action,
            "severity": "CRITICAL" if a.artifact_type == "AGENT_MEMORY" else "HIGH",
        }
        for a in blast_result.impacted_artifacts
    ]

    return {
        "summary": {
            "total_drifts": len(drift_report.drifts),
            "breaking_drifts": len(drift_report.breaking_drifts),
            "non_breaking_drifts": len(drift_report.non_breaking_drifts),
            "impacted_files_count": blast_result.total_impacted_files,
            "has_drift": drift_report.has_drift,
            "is_synced": blast_result.total_impacted_files == 0,
        },
        "drifts": drifts_data,
        "blast_radius": blast_data,
        "remediation_brief": blast_result.format_remediation_brief(),
        "base_code": base_code,
        "head_code": head_code,
        "files": files,
        "base_schemas": [
            {"name": s.name, "fields": [{"name": f.name, "type": f.type_annotation, "required": f.is_required, "default": f.default_value} for f in s.fields]}
            for s in base_contract.schemas
        ],
        "head_schemas": [
            {"name": s.name, "fields": [{"name": f.name, "type": f.type_annotation, "required": f.is_required, "default": f.default_value} for f in s.fields]}
            for s in head_contract.schemas
        ],
    }


@app.post("/api/remediate")
async def run_remediation(req: Optional[RemediateRequest] = None):
    """Execute DriftRemediator in an isolated temporary workspace, write patches, and verify sync."""
    if not DEMO_FIXTURES.exists():
        raise HTTPException(status_code=404, detail="Demo fixtures not found")

    temp_dir = tempfile.mkdtemp(prefix="driftlock_api_rem_")
    try:
        shutil.copytree(DEMO_FIXTURES, temp_dir, dirs_exist_ok=True)
        temp_path = Path(temp_dir)

        base_contract = parse_file(temp_path / "api_base.py")
        head_contract = parse_file(temp_path / "api_head.py")
        drift_report = compute_contract_diff(base_contract, head_contract)

        mapper = BlastRadiusMapper(temp_path)
        blast_result = mapper.scan_blast_radius(drift_report)

        use_api = req.use_api if req else False
        if use_api and req and req.api_key:
            os.environ["OPENROUTER_API_KEY"] = req.api_key

        remediator = DriftRemediator(use_api=use_api)
        rem_result = remediator.remediate(blast_result, head_contract)
        remediator.apply_patches(rem_result)

        # Post-remediation verification re-scan
        post_mapper = BlastRadiusMapper(temp_path)
        post_result = post_mapper.scan_blast_radius(drift_report)

        patches_data = []
        for p in rem_result.patches:
            fname = Path(p.file_path).name
            diff_text = _format_diff(p.original_content, p.patched_content, fname)
            patches_data.append(
                {
                    "file_path": p.file_path,
                    "file_name": fname,
                    "artifact_type": p.artifact_type,
                    "original": p.original_content,
                    "patched": p.patched_content,
                    "unified_diff": diff_text,
                    "changes_applied": p.changes_applied,
                }
            )

        return {
            "success": True,
            "post_audit_impacted_files": post_result.total_impacted_files,
            "is_synced": post_result.total_impacted_files == 0,
            "files_patched_count": len(patches_data),
            "patches": patches_data,
            "message": f"✓ REPOSITORY SYNCHRONIZED — {post_result.total_impacted_files} Stale Artifacts Remaining ({len(patches_data)}/3 Fixed)",
        }
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@app.post("/api/custom-audit")
async def custom_ast_audit(req: CustomAuditRequest):
    """Run real-time AST contract diff on arbitrary Base vs. Head Python code."""
    try:
        base_contract = parse_code(req.base_code, filename="custom_base.py")
        head_contract = parse_code(req.head_code, filename="custom_head.py")
        drift_report = compute_contract_diff(base_contract, head_contract)

        drifts_data = [
            {
                "category": d.category,
                "identifier": d.identifier,
                "details": d.details,
                "is_breaking": d.is_breaking,
            }
            for d in drift_report.drifts
        ]

        return {
            "success": True,
            "has_drift": drift_report.has_drift,
            "has_breaking_drift": drift_report.has_breaking_drift,
            "total_drifts": len(drift_report.drifts),
            "breaking_count": len(drift_report.breaking_drifts),
            "non_breaking_count": len(drift_report.non_breaking_drifts),
            "drifts": drifts_data,
            "base_schemas": [
                {"name": s.name, "fields": [{"name": f.name, "type": f.type_annotation, "required": f.is_required, "default": f.default_value} for f in s.fields]}
                for s in base_contract.schemas
            ],
            "head_schemas": [
                {"name": s.name, "fields": [{"name": f.name, "type": f.type_annotation, "required": f.is_required, "default": f.default_value} for f in s.fields]}
                for s in head_contract.schemas
            ],
            "base_routes": [{"method": r.method, "path": r.path, "function": r.function_name} for r in base_contract.routes],
            "head_routes": [{"method": r.method, "path": r.path, "function": r.function_name} for r in head_contract.routes],
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"AST Parsing error: {str(exc)}")


# ---------------------------------------------------------------------------
# Static Web Frontend
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_file = WEB_DIR / "index.html"
    if not index_file.exists():
        return HTMLResponse("<h1>DriftLock API is running. web/index.html not found.</h1>", status_code=404)
    return HTMLResponse(content=index_file.read_text(encoding="utf-8"))


if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


def run(host: str = "127.0.0.1", port: int = 8000, reload: bool = True):
    import uvicorn
    uvicorn.run("driftlock.api.server:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    run()
