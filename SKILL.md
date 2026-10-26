# DriftLock Skill

DriftLock is an autonomous AST drift and contract consistency engine. Use this skill to detect and remediate contract drift between API schemas, tests, documentation, and AI agent memory files.

## When to Use

- After modifying a Pydantic schema or FastAPI/Flask route
- Before committing changes that touch API contracts
- When reviewing PRs that may have introduced breaking schema changes
- When agent context files (`AGENT_CONTEXT.md`, `CLAUDE.md`) may be stale

## Quick Commands

### Audit two contract versions

```bash
python -m driftlock.cli.main audit --base path/to/old_api.py --head path/to/new_api.py --repo .
```

### Run the built-in demo

```bash
python -m driftlock.cli.main demo
```

### Auto-remediate stale files

```bash
python -m driftlock.cli.main demo --fix
```

### Get JSON output for CI/CD pipelines

```bash
python -m driftlock.cli.main audit --base old.py --head new.py --repo . --json
```

## How It Works

1. **Parse** — DriftLock uses Python's native `ast` module (zero-LLM) to extract routes and Pydantic schemas from both the base and head contract files.
2. **Diff** — Deterministically compares both snapshots to classify drifts as `FIELD_ADDED`, `FIELD_REMOVED`, `FIELD_TYPE_CHANGED`, `ROUTE_ADDED`, `ROUTE_REMOVED`, etc., with breaking vs. non-breaking classification.
3. **Blast Radius** — Walks the repository to find `TEST`, `DOCUMENTATION`, and `AGENT_MEMORY` files that reference drifted schemas but are missing the updated fields.
4. **Remediation Brief** — Generates structured, actionable remediation instructions.
5. **Auto-Fix** — With `--fix`, patches stale files deterministically (or via Open Model API if a key is set) and verifies zero remaining drift.

## Interpreting Results

- **BREAKING** drifts (red) require immediate action — they will cause runtime failures for API consumers.
- **NON-BREAKING** drifts (yellow) are safe but should still be documented.
- The **Blast Radius Tree** shows exactly which test files, docs, and agent context files need updating.
- The **Remediation Brief** can be fed directly to an AI coding agent for automated patching.
