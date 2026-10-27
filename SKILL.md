# DriftLock Skill

DriftLock is a deterministic AST drift and contract consistency engine. Use this skill to detect and remediate contract drift between API schemas, tests (`[TEST]`), documentation (`[DOCS]`), and AI agent memory (`[AGENT_MEMORY]`).

## When to Use

- After modifying a Pydantic schema or FastAPI/Flask route
- Before committing changes that touch API contracts or submitting PRs
- When agent context files (`AGENT_CONTEXT.md`, `CLAUDE.md`) may be stale
- In CI pipelines to block merges on breaking drift

## Preferred: MCP Tools

When the DriftLock MCP server is connected, call these tools instead of shelling out. They return the same versioned JSON report and keep stdout machine-readable.

- `driftlock_audit(repository_root, base_contract, head_contract, ci=false)` — read-only audit; `ci=true` maps to the gate exit code.
- `driftlock_demo()` — bundled fixture demonstration, labeled `fixture_demo` and **not** a production audit.
- `driftlock_apply_fix(repository_root, base_contract, head_contract, authorize=true)` — **modifies files**; use only with explicit user approval, then report the returned diffs and verification.

The server is stdio-only and requires `DRIFTLOCK_MCP_WORKSPACE` to be set to the project root. If the tools are unavailable, use the CLI fallback below.

## CLI Fallback

### 1. Run the Built-in Demo
```bash
python -m driftlock.cli.main demo
```

### 2. Auto-Remediate Stale Files
```bash
python -m driftlock.cli.main demo --fix
```

### 3. Audit Specific Base and Head Contracts
```bash
python -m driftlock.cli.main audit --base path/to/base.py --head path/to/head.py --repo .
```

### 4. CI Gatekeeper Check
```bash
python -m driftlock.cli.main audit --base base.py --head head.py --repo . --ci
```
*Exits with code 1 if breaking drift or stale artifacts exist; exits with code 0 if fully synchronized.*

### 5. Structured JSON Output
```bash
python -m driftlock.cli.main audit --base base.py --head head.py --repo . --json
```

## How It Works

1. **Deterministic AST Parser**: Uses Python's native `ast` module (zero-LLM, zero code execution) to extract routes and Pydantic schemas.
2. **Contract Diff Engine**: Classifies differences into breaking (`FIELD_ADDED` without default, `FIELD_REMOVED`, `FIELD_TYPE_CHANGED`, `ROUTE_REMOVED`) and non-breaking (`FIELD_ADDED` with default, `ROUTE_ADDED`).
3. **Multi-Artifact Blast Radius**: Traverses repository files to detect stale references across `[TEST]`, `[DOCS]`, and `[AGENT_MEMORY]`.
4. **Closed-Loop Remediation**: With `--fix`, deterministically patches stale files in an isolated temp workspace, re-verifies 0 remaining drift, and writes verified patches.
