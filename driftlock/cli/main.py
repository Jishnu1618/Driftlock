"""DriftLock CLI: Rich terminal UI for contract drift auditing.

Commands:
  audit  - Compare base and head contract files, compute diff, and scan blast radius.
  demo   - Run audit against a built-in demo fixture with zero arguments.
"""

from __future__ import annotations

import difflib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Optional

# Force UTF-8 output on Windows to avoid cp1252 encoding errors with Rich
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

import typer
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from driftlock.blast_radius.graph import BlastRadiusMapper, BlastRadiusResult
from driftlock.core.diff import ContractDrift, DriftReport, compute_contract_diff
from driftlock.core.parser import parse_file

app = typer.Typer(
    name="driftlock",
    help="DriftLock: Autonomous AST drift and contract consistency engine.",
    add_completion=False,
)
console = Console(force_terminal=True)

# ---------------------------------------------------------------------------
# Rich rendering helpers
# ---------------------------------------------------------------------------

STATUS_BADGE_DRIFT = "[bold white on red] X DRIFT DETECTED [/]"
STATUS_BADGE_SYNC = "[bold white on green] OK CONTRACTS IN SYNC [/]"

CATEGORY_ICONS = {
    "FIELD_ADDED": "[green]+[/green]",
    "FIELD_REMOVED": "[red]-[/red]",
    "FIELD_TYPE_CHANGED": "[yellow]~[/yellow]",
    "FIELD_DEFAULT_CHANGED": "[cyan]~[/cyan]",
    "FIELD_REQUIRED_CHANGED": "[yellow]![/yellow]",
    "SCHEMA_ADDED": "[green]+[/green]",
    "SCHEMA_REMOVED": "[red]-[/red]",
    "ROUTE_ADDED": "[green]+[/green]",
    "ROUTE_REMOVED": "[red]-[/red]",
    "ROUTE_RETURN_TYPE_CHANGED": "[yellow]~[/yellow]",
    "ROUTE_RESPONSE_MODEL_CHANGED": "[yellow]~[/yellow]",
    "ROUTE_STATUS_CODE_CHANGED": "[yellow]~[/yellow]",
    "ROUTE_METHOD_CHANGED": "[yellow]~[/yellow]",
    "ROUTE_PARAM_ADDED": "[green]+[/green]",
    "ROUTE_PARAM_REMOVED": "[red]-[/red]",
    "ROUTE_PARAM_TYPE_CHANGED": "[yellow]~[/yellow]",
}

ARTIFACT_TYPE_LABELS = {
    "TEST": "[bold yellow]TEST[/bold yellow]",
    "DOCUMENTATION": "[bold cyan]DOCS[/bold cyan]",
    "AGENT_MEMORY": "[bold magenta]AGENT MEMORY[/bold magenta]",
}


def _render_drift_tree(result: BlastRadiusResult) -> None:
    """Render the full audit result as a Rich tree in the terminal."""
    report = result.drift_report

    # Header
    if report.has_drift:
        console.print(STATUS_BADGE_DRIFT)
    else:
        console.print(STATUS_BADGE_SYNC)
        console.print("\n[green]No contract drifts detected. All files are in sync.[/green]")
        return

    console.print()

    # -- Contract Changes --
    changes_tree = Tree("[bold]Contract Changes[/bold]")

    if report.breaking_drifts:
        breaking_branch = changes_tree.add("[bold red]BREAKING Changes[/bold red]")
        for d in report.breaking_drifts:
            icon = CATEGORY_ICONS.get(d.category, "*")
            breaking_branch.add(
                f"{icon} [red]{escape(d.category)}[/red] -> "
                f"[bold]{escape(d.identifier)}[/bold]\n"
                f"   {escape(d.details)}"
            )

    if report.non_breaking_drifts:
        non_breaking_branch = changes_tree.add("[bold yellow]NON-BREAKING Changes[/bold yellow]")
        for d in report.non_breaking_drifts:
            icon = CATEGORY_ICONS.get(d.category, "*")
            non_breaking_branch.add(
                f"{icon} [yellow]{escape(d.category)}[/yellow] -> "
                f"[bold]{escape(d.identifier)}[/bold]\n"
                f"   {escape(d.details)}"
            )

    console.print(changes_tree)
    console.print()

    # -- Blast Radius --
    if not result.impacted_artifacts:
        console.print("[green]No stale files detected in the blast radius.[/green]")
        return

    blast_tree = Tree(
        f"[bold]Blast Radius[/bold] -- "
        f"[red]{result.total_impacted_files} file(s) impacted[/red]"
    )

    # Group by artifact type
    for atype, label in ARTIFACT_TYPE_LABELS.items():
        artifacts = [a for a in result.impacted_artifacts if a.artifact_type == atype]
        if not artifacts:
            continue
        type_branch = blast_tree.add(f"{label} ({len(artifacts)} hit{'s' if len(artifacts) > 1 else ''})")
        for artifact in artifacts:
            node = type_branch.add(f"[dim]{escape(artifact.file_path)}[/dim]")
            node.add(f"[italic]{escape(artifact.reason)}[/italic]")
            node.add(f"[green]-> {escape(artifact.suggested_action)}[/green]")

    console.print(blast_tree)
    console.print()

    # -- Remediation Brief --
    _render_remediation_brief(result)


def _render_remediation_brief(result: BlastRadiusResult) -> None:
    """Render a structured remediation brief that an AI coding agent can parse."""
    report = result.drift_report

    lines = []
    lines.append("# DriftLock Remediation Brief")
    lines.append("")
    lines.append("## Contract Drifts Detected")
    for i, d in enumerate(report.drifts, 1):
        severity = "BREAKING" if d.is_breaking else "NON-BREAKING"
        lines.append(f"{i}. [{severity}] {d.category}: {d.identifier}")
        lines.append(f"   Detail: {d.details}")
    lines.append("")

    if result.impacted_artifacts:
        lines.append("## Stale Files Requiring Update")
        for artifact in result.impacted_artifacts:
            lines.append(f"- [{artifact.artifact_type}] {artifact.file_path}")
            lines.append(f"  - Reason: {artifact.reason}")
            lines.append(f"  - Action: {artifact.suggested_action}")
        lines.append("")

    lines.append("## Instructions for AI Agent")
    lines.append("1. Read each stale file listed above.")
    lines.append("2. Apply the suggested action to synchronize the file with the new contract.")
    lines.append("3. Run the test suite to verify no regressions.")
    lines.append("4. Commit the synchronized files.")

    brief_text = "\n".join(lines)

    console.print(Panel(
        brief_text,
        title="[bold blue]Remediation Brief for Alan Agent[/bold blue]",
        border_style="blue",
        padding=(1, 2),
    ))


def _render_json(result: BlastRadiusResult) -> None:
    """Output the audit result as structured JSON."""
    report = result.drift_report
    output = {
        "has_drift": report.has_drift,
        "has_breaking_drift": report.has_breaking_drift,
        "total_drifts": len(report.drifts),
        "breaking_drifts": len(report.breaking_drifts),
        "non_breaking_drifts": len(report.non_breaking_drifts),
        "drifts": [
            {
                "category": d.category,
                "identifier": d.identifier,
                "details": d.details,
                "is_breaking": d.is_breaking,
            }
            for d in report.drifts
        ],
        "blast_radius": {
            "total_impacted_files": result.total_impacted_files,
            "impacted_artifacts": [
                {
                    "file_path": a.file_path,
                    "artifact_type": a.artifact_type,
                    "reason": a.reason,
                    "stale_reference": a.stale_reference,
                    "suggested_action": a.suggested_action,
                }
                for a in result.impacted_artifacts
            ],
        },
    }
    console.print_json(json.dumps(output, indent=2))


def _render_unified_diff(patch) -> None:
    """Render a unified diff panel for a single remediation patch."""
    from driftlock.sync.remediator import RemediationPatch

    fname = Path(patch.file_path).name
    diff_lines = list(difflib.unified_diff(
        patch.original_content.splitlines(keepends=True),
        patch.patched_content.splitlines(keepends=True),
        fromfile=f"a/{fname}",
        tofile=f"b/{fname}",
        lineterm="",
    ))

    if diff_lines:
        diff_text = "\n".join(diff_lines)
        console.print(Panel(
            Syntax(diff_text, "diff", theme="monokai", line_numbers=False),
            title=f"[bold yellow]Patch: {escape(fname)}[/bold yellow]",
            border_style="yellow",
            padding=(0, 1),
        ))
    console.print()


# ---------------------------------------------------------------------------
# CLI Commands
# ---------------------------------------------------------------------------


@app.command()
def audit(
    base: str = typer.Option(..., "--base", "-b", help="Path to the base (old) Python contract file."),
    head: str = typer.Option(..., "--head", "-H", help="Path to the head (new) Python contract file."),
    repo: str = typer.Option(".", "--repo", "-r", help="Repository root directory to scan for blast radius."),
    output_json: bool = typer.Option(False, "--json", "-j", help="Output results as structured JSON."),
    fix: bool = typer.Option(False, "--fix", "-f", help="Auto-remediate stale files and verify sync."),
) -> None:
    """Compare base and head contract files, compute drift, and scan blast radius."""
    base_path = Path(base)
    head_path = Path(head)
    repo_path = Path(repo)

    if not base_path.is_file():
        console.print(f"[red]Error: Base file not found: {base}[/red]")
        raise typer.Exit(code=1)
    if not head_path.is_file():
        console.print(f"[red]Error: Head file not found: {head}[/red]")
        raise typer.Exit(code=1)
    if not repo_path.is_dir():
        console.print(f"[red]Error: Repository directory not found: {repo}[/red]")
        raise typer.Exit(code=1)

    # Parse contracts
    console.print(f"[dim]Parsing base contract: {base_path}[/dim]")
    base_contract = parse_file(base_path)
    console.print(f"[dim]Parsing head contract: {head_path}[/dim]")
    head_contract = parse_file(head_path)

    # Compute diff
    console.print("[dim]Computing contract diff...[/dim]")
    drift_report = compute_contract_diff(base_contract, head_contract)

    # Scan blast radius
    console.print(f"[dim]Scanning blast radius in: {repo_path.resolve()}[/dim]")
    mapper = BlastRadiusMapper(str(repo_path.resolve()))
    result = mapper.scan_blast_radius(drift_report)

    console.print()

    if output_json:
        _render_json(result)
    else:
        _render_drift_tree(result)

    # --fix: auto-remediate
    if fix and result.impacted_artifacts:
        _run_fix(result, head_contract, repo_path)


@app.command()
def demo(
    fix: bool = typer.Option(False, "--fix", "-f", help="Auto-remediate stale files and verify sync."),
) -> None:
    """Run a built-in demo audit against fixtures/demo_repo/ with zero arguments."""
    # Locate the demo fixtures relative to the project root
    cli_dir = Path(__file__).resolve().parent
    project_root = cli_dir.parent.parent  # driftlock/cli -> driftlock -> project root

    demo_dir = project_root / "fixtures" / "demo_repo"

    if not demo_dir.is_dir():
        console.print(f"[red]Error: Demo fixtures not found at {demo_dir}[/red]")
        console.print("[dim]Expected directory: fixtures/demo_repo/[/dim]")
        raise typer.Exit(code=1)

    base_file = demo_dir / "api_base.py"
    head_file = demo_dir / "api_head.py"

    if not base_file.is_file() or not head_file.is_file():
        console.print("[red]Error: Missing api_base.py or api_head.py in demo fixtures.[/red]")
        raise typer.Exit(code=1)

    console.print(Panel(
        "[bold]DriftLock Demo[/bold]\n\n"
        "Simulating a contract drift scenario:\n"
        "  Base: UserCreate with [username, email]\n"
        "  Head: UserCreate adds [tier (required), organization_id (optional)]\n\n"
        "Scanning demo_repo/ for stale tests, docs, and agent context...",
        title="[bold blue]DriftLock[/bold blue]",
        border_style="blue",
    ))
    console.print()

    # Parse contracts
    base_contract = parse_file(base_file)
    head_contract = parse_file(head_file)

    # Compute diff
    drift_report = compute_contract_diff(base_contract, head_contract)

    if fix:
        # --fix mode: work on a temporary copy so fixtures/ is NEVER mutated
        _run_demo_fix(demo_dir, base_contract, head_contract, drift_report)
    else:
        # Normal demo: scan blast radius within the demo repo
        mapper = BlastRadiusMapper(str(demo_dir))
        result = mapper.scan_blast_radius(drift_report)
        _render_drift_tree(result)


# ---------------------------------------------------------------------------
# --fix implementation
# ---------------------------------------------------------------------------


def _run_fix(
    result: BlastRadiusResult,
    head_contract,
    repo_path: Path,
) -> None:
    """Execute auto-remediation on the actual repo (for ``audit --fix``)."""
    from driftlock.sync.remediator import DriftRemediator

    console.print()
    console.print("[bold blue]Running DriftLock Auto-Remediation...[/bold blue]")
    console.print()

    remediator = DriftRemediator(use_api=None)
    rem_result = remediator.remediate(result, head_contract)

    if rem_result.files_patched == 0:
        console.print("[yellow]No patches could be generated.[/yellow]")
        return

    # Show diffs
    for patch in rem_result.patches:
        _render_unified_diff(patch)

    # Apply patches
    written = remediator.apply_patches(rem_result)
    console.print(f"[dim]Wrote {written} patched file(s) to disk.[/dim]")

    # Re-scan to verify
    mapper = BlastRadiusMapper(str(repo_path.resolve()))
    new_result = mapper.scan_blast_radius(result.drift_report)
    remaining = new_result.total_impacted_files

    console.print()
    if remaining == 0:
        total = rem_result.files_patched
        console.print(Panel(
            f"[bold green]REPOSITORY SYNCHRONIZED -- "
            f"0 Stale Artifacts Remaining ({total}/{total} Fixed)[/bold green]",
            border_style="green",
            padding=(1, 2),
        ))
    else:
        console.print(Panel(
            f"[bold yellow]Partial Remediation -- "
            f"{remaining} Stale Artifact(s) Remaining[/bold yellow]",
            border_style="yellow",
            padding=(1, 2),
        ))


def _run_demo_fix(
    demo_dir: Path,
    base_contract,
    head_contract,
    drift_report: DriftReport,
) -> None:
    """Run --fix on a temp copy of fixtures/demo_repo/ to never mutate originals."""
    from driftlock.sync.remediator import DriftRemediator

    with tempfile.TemporaryDirectory(prefix="driftlock_demo_") as tmp:
        tmp_dir = Path(tmp) / "demo_repo"
        shutil.copytree(str(demo_dir), str(tmp_dir))

        # Step 1: Initial blast radius scan on temp copy
        mapper = BlastRadiusMapper(str(tmp_dir))
        initial_result = mapper.scan_blast_radius(drift_report)

        console.print("[bold red]--- BEFORE Remediation ---[/bold red]")
        console.print()
        _render_drift_tree(initial_result)

        # Step 2: Run remediator
        console.print()
        console.print("[bold blue]Running DriftLock Auto-Remediation...[/bold blue]")
        console.print()

        remediator = DriftRemediator(use_api=False)  # Always offline for demo
        rem_result = remediator.remediate(initial_result, head_contract)

        if rem_result.files_patched == 0:
            console.print("[yellow]No patches could be generated.[/yellow]")
            return

        # Step 3: Show unified diffs
        for patch in rem_result.patches:
            _render_unified_diff(patch)

        # Step 4: Write patches to temp dir
        written = remediator.apply_patches(rem_result)
        console.print(f"[dim]Applied {written} patch(es) to temporary workspace.[/dim]")
        console.print()

        # Step 5: Re-scan to verify synchronization
        post_mapper = BlastRadiusMapper(str(tmp_dir))
        post_result = post_mapper.scan_blast_radius(drift_report)
        remaining = post_result.total_impacted_files

        console.print("[bold green]--- AFTER Remediation ---[/bold green]")
        console.print()

        if remaining == 0:
            total = rem_result.files_patched
            console.print(Panel(
                f"[bold green]REPOSITORY SYNCHRONIZED -- "
                f"0 Stale Artifacts Remaining ({total}/{total} Fixed)[/bold green]",
                border_style="green",
                padding=(1, 2),
            ))
        else:
            console.print(Panel(
                f"[bold yellow]Partial Remediation -- "
                f"{remaining} Stale Artifact(s) Remaining[/bold yellow]",
                border_style="yellow",
                padding=(1, 2),
            ))


def main() -> None:
    """Entry point for the DriftLock CLI."""
    app()


if __name__ == "__main__":
    main()
