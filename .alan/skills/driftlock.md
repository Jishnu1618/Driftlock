# /driftlock — Alan AI Skill

## Skill Description

The `/driftlock` skill enables Alan's coding agent to detect and remediate contract drift between API schemas, test suites, documentation, and agent memory files. It runs DriftLock's deterministic AST parser and blast radius mapper to identify stale references, then either auto-patches them or generates a remediation brief.

## Trigger

Activate this skill when:
- A Pydantic model or FastAPI/Flask route has been modified
- You need to verify consistency between API contracts, tests, docs, and agent context
- A PR review shows schema changes that may have downstream stale references
- The user says "check for drift", "run driftlock", or "audit contracts"

## Workflow

### Step 1: Run the audit

```bash
python -m driftlock.cli.main audit \
  --base <path_to_base_contract.py> \
  --head <path_to_head_contract.py> \
  --repo <repository_root>
```

If no specific files are given, use the demo:

```bash
python -m driftlock.cli.main demo
```

### Step 2: Read the Remediation Brief

The CLI outputs a structured **Remediation Brief** listing:
- Each detected contract drift (FIELD_ADDED, FIELD_REMOVED, FIELD_TYPE_CHANGED, ROUTE_ADDED, ROUTE_REMOVED)
- Whether each drift is BREAKING or NON-BREAKING
- Every impacted file with its artifact type (TEST, DOCUMENTATION, AGENT_MEMORY)
- A specific suggested action for each impacted file

### Step 3: Patch the impacted files

For each stale file listed in the Remediation Brief:

**TEST files** (`test_*.py`):
1. Add the missing field to test payload dictionaries
2. Add assertions verifying the new field is present
3. Update `expected_fields` lists

**DOCUMENTATION files** (`README.md`, `*.md`):
1. Add the new field to markdown schema tables
2. Update JSON examples with the new field
3. Add the field to any bullet-point API descriptions

**AGENT_MEMORY files** (`AGENT_CONTEXT.md`, `CLAUDE.md`):
1. Add the new field to schema definition tables
2. Update API contract bullet lists
3. Update validation instructions

### Step 4: Auto-fix and verify

Run the auto-remediation to patch all files and verify zero remaining drift:

```bash
python -m driftlock.cli.main demo --fix
```

Or for a real audit:

```bash
python -m driftlock.cli.main audit \
  --base <base.py> --head <head.py> \
  --repo <repo_root> --fix
```

The `--fix` flag will:
1. Display the initial drift audit (RED status)
2. Auto-patch all stale files
3. Show unified diffs of all changes
4. Re-scan and verify synchronization
5. Print GREEN status if all stale artifacts are fixed

### Step 5: Verify with tests

```bash
pytest tests/ -v
```

Ensure all tests pass after remediation.

### Step 6: Commit the synchronized files

```bash
git add -A
git commit -m "fix: synchronize tests, docs, and agent context with updated API contract"
```

## JSON Output for Pipelines

For CI/CD integration, use `--json`:

```bash
python -m driftlock.cli.main audit --base old.py --head new.py --repo . --json
```

This outputs structured JSON with `has_drift`, `breaking_drifts`, `blast_radius`, and `impacted_artifacts` suitable for automated pipeline gates.
