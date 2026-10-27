# /driftlock — Alan AI Skill

## Skill Description

The `/driftlock` skill empowers Alan AI coding agents to detect and deterministically remediate contract drift between backend API schemas (Pydantic, FastAPI, Flask), test suites (`[TEST]`), documentation (`[DOCS]`), and AI agent context/memory files (`[AGENT_MEMORY]`). 

It invokes DriftLock's zero-execution AST parser and multi-artifact Blast Radius mapper to pinpoint stale references, and applies closed-loop automated patching via `--fix` to eliminate agent hallucinations and CI breakages.

## Trigger Conditions

Activate this skill when:
- An API schema (`BaseModel`) or route signature has been added, modified, or removed.
- A pull request review touches backend schemas and requires downstream verification.
- You need to guarantee that `AGENT_CONTEXT.md` / `CLAUDE.md` reflect current contracts before generating new features.
- The user prompts: "check for drift", "audit contracts", "fix drift", or "/driftlock".

---

## Autonomous Agent Workflow

### Step 1: Execute the AST Audit

Run the DriftLock CLI against the base and head contract files:

```bash
python -m driftlock.cli.main audit \
  --base <path_to_base_contract.py> \
  --head <path_to_head_contract.py> \
  --repo <repository_root>
```

For quick verification on built-in fixtures:
```bash
python -m driftlock.cli.main demo
```

### Step 2: Inspect Blast Radius by Artifact Category

DriftLock groups impacted artifacts into three distinct blast radius categories:

1. **`[TEST]` Artifacts (`tests/test_*.py`)**
   - **Risk:** Stale test payloads missing newly required fields or missing assertions on new endpoints.
   - **Agent Action:** Inject missing required attributes into fixture dictionaries, request payloads, and add assertion checks.

2. **`[DOCS]` Artifacts (`README.md`, `docs/*.md`)**
   - **Risk:** Outdated markdown schema tables, stale curl/JSON examples, desynchronized endpoint paths.
   - **Agent Action:** Update markdown attribute tables, JSON examples, and endpoint documentation.

3. **`[AGENT_MEMORY]` Artifacts (`AGENT_CONTEXT.md`, `CLAUDE.md`, `.cursorrules`)**
   - **Risk:** **Agent Amnesia** — Downstream coding agents read outdated memory files and continuously generate deprecated payload structures.
   - **Agent Action:** Update system prompt constraints, schema specification tables, and validation instructions so all future agent iterations operate on the truth.

### Step 3: Run Closed-Loop Auto-Remediation (`--fix`)

DriftLock can automatically patch all stale artifacts across the blast radius:

```bash
# Auto-patch files in a real repository and verify 0 drift remaining:
python -m driftlock.cli.main audit \
  --base <path_to_base_contract.py> \
  --head <path_to_head_contract.py> \
  --repo <repository_root> \
  --fix
```

```bash
# Verify the remediation workflow safely in a sandboxed temp environment:
python -m driftlock.cli.main demo --fix
```

When `--fix` executes:
1. It analyzes contract changes and generates unified diffs for every impacted file.
2. It writes deterministic updates to test dictionaries, markdown tables, and agent rules.
3. It performs an immediate re-audit of the repository.
4. It reports `✓ REPOSITORY SYNCHRONIZED — 0 Stale Artifacts Remaining (N/N Fixed)`.

### Step 4: CI Gatekeeper Integration (`--ci`)

When integrating DriftLock into CI/CD pipelines or pre-commit hooks, pass `--ci`:

```bash
python -m driftlock.cli.main audit \
  --base main_contract.py \
  --head pr_contract.py \
  --repo . \
  --ci
```

- **Exit Code `0`:** Contracts are in sync and 0 stale artifacts exist.
- **Exit Code `1`:** Breaking contract drift or stale artifacts detected (blocks PR merge).

### Step 5: Verify Suite and Commit

After applying `--fix`, verify no regressions:

```bash
pytest tests/ -v
git add -A
git commit -m "fix(contract): synchronize tests, documentation, and agent memory via DriftLock"
```
