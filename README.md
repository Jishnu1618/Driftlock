# DriftLock 🔒

**Deterministic Contract & Context Consistency Layer for AI-Assisted Development**  
*Guaranteed synchronization between API contracts, tests, documentation, and AI agent memory.*

[![Python Version](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://www.python.org/)
[![Tests Passing](https://img.shields.io/badge/tests-42%20passed%20%C2%B7%20100%25-emerald.svg)](tests/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Engine](https://img.shields.io/badge/AST%20Engine-Native%20Zero--LLM%20Deterministic-orange.svg)](#engineering-decisions--thought-process)
[![Alan AI Skill](https://img.shields.io/badge/Alan%20AI%20Skill-%2Fdriftlock-6366f1.svg)](.alan/skills/driftlock.md)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## ⚡ The Problem: Agent Amnesia & Silent Contract Drift

AI coding agents (Alan, Claude, Cursor, Copilot) are dramatically accelerating software delivery. However, faster code generation introduces a critical failure mode: **Silent Contract Drift**.

When a developer or AI agent alters an API schema—such as adding a required field to a Pydantic model or modifying a route signature—the changes ripple throughout the codebase:

```
[PR #42: Schema Expansion] 
       │
       ├──► 🧪 Tests Silently Rot (fixtures omit new required fields)
       ├──► 📖 Docs Desynchronize (README & API tables show deprecated contracts)
       └──► 🤖 Agent Amnesia (AGENT_CONTEXT.md retains stale constraints)
               │
               └──► Downstream Agent Hallucinations & Broken CI Builds!
```

### The "Agent Amnesia" Feedback Loop
1. **The Drift**: An agent updates `UserCreate` by adding a required `tier: str` field.
2. **The Amnesia**: The agent commits the endpoint change but neglects `AGENT_CONTEXT.md`, test fixtures, and markdown documentation.
3. **The Hallucination**: The next AI agent reads the stale `AGENT_CONTEXT.md`, assumes `UserCreate` only requires `username` and `email`, and generates code or tests with invalid payloads.
4. **The Crash**: CI fails, developer velocity collapses, and hours are spent debugging subtle desynchronizations.
5. **Runtime Pitfalls**: Traditional contract tools attempt to `import` or execute target modules, triggering environment variable errors, database connection failures, and unconfigured runtime crashes.

---

## 🎯 The Solution: DriftLock

**DriftLock** is a zero-execution, deterministic consistency engine designed specifically for modern AI-assisted engineering workflows:

- **Zero-Execution Native AST Parsing**: Uses Python's native `ast` module. Never imports or executes code—completely side-effect free, instant, and secure against unconfigured environments.
- **Deterministic Contract Diffing**: Categorizes schema and route changes into breaking and non-breaking drifts (`FIELD_ADDED`, `FIELD_REMOVED`, `FIELD_TYPE_CHANGED`, `ROUTE_ADDED`, `ROUTE_REMOVED`).
- **Multi-Artifact Blast Radius Mapper**: Automatically traverses the repository and maps dependencies across:
  - `[TEST]` (`tests/test_*.py`)
  - `[DOCS]` (`README.md`, `docs/*.md`)
  - `[AGENT_MEMORY]` (`AGENT_CONTEXT.md`, `CLAUDE.md`, `.cursorrules`)
- **Closed-Loop Auto-Remediation (`--fix`)**: Applies verified patches in an isolated sandbox, re-audits the workspace to verify 0 remaining drift, and updates files atomically.
- **CI Gatekeeper (`--ci`)**: Enforces strict contract synchronization in pull request workflows, blocking merges when contract drift is left unaddressed.
- **Alan AI Native Skill (`/driftlock`)**: A structured skill package allowing Alan AI agents to autonomously audit, interpret blast radius briefs, and patch repositories.
- **Precision Dark-Mode Web Control Plane**: A dark-mode developer dashboard (inspired by Linear and Vercel) served directly by FastAPI at `http://localhost:8000`.

---

## 🏗 Architecture

```mermaid
flowchart TD
    subgraph Inputs ["1. Contract Sources"]
        Base["Base API Contract\n(git base / main branch)"]
        Head["Head API Contract\n(feature branch / PR)"]
    end

    subgraph CoreEngine ["2. Deterministic AST Engine"]
        ASTParser["Python Native AST Parser\n(Zero-LLM · Zero-Execution)"]
        DiffEngine["Contract Diff Engine\n(Breaking vs Non-Breaking Drift)"]
    end

    subgraph BlastRadius ["3. Multi-Artifact Blast Radius"]
        Mapper["Blast Radius Mapper\n(AST & Regex Reference Graph)"]
        TestArtifacts["🧪 [TEST]\n(tests/test_*.py)"]
        DocArtifacts["📖 [DOCS]\n(README.md, docs/)"]
        AgentArtifacts["🤖 [AGENT_MEMORY]\n(AGENT_CONTEXT.md)"]
    end

    subgraph RemediationGate ["4. Closed-Loop Remediation & Verification"]
        Remediator["DriftRemediator\n(Temp Workspace Sandbox)"]
        VerifySync["Verification Gate\n(Re-Audit: 0 Stale Artifacts?)"]
        GatePass["✓ Ready to Merge (Exit 0)"]
        GateBlock["✗ CI Blocked (Exit 1)"]
    end

    subgraph Interfaces ["5. Developer Control Surfaces"]
        CLI["💻 Rich Terminal CLI\n(--fix · --json · --ci)"]
        WebUI["🌐 Dark-Mode Control Plane\n(FastAPI + Stitch UI)"]
        AlanSkill["🤖 Alan AI Skill\n(/driftlock)"]
    end

    Base --> ASTParser
    Head --> ASTParser
    ASTParser --> DiffEngine
    DiffEngine --> Mapper

    Mapper --> TestArtifacts
    Mapper --> DocArtifacts
    Mapper --> AgentArtifacts

    TestArtifacts --> Remediator
    DocArtifacts --> Remediator
    AgentArtifacts --> Remediator

    Remediator --> VerifySync
    VerifySync -->|Verified Clean| GatePass
    VerifySync -->|Drift Exists| GateBlock

    DiffEngine --> CLI
    DiffEngine --> WebUI
    DiffEngine --> AlanSkill
    Remediator --> CLI
    Remediator --> WebUI
    Remediator --> AlanSkill
```

---

## 🚀 Quickstart

### 1. Prerequisites & Installation

```bash
# Clone repository
git clone https://github.com/Jishnu1618/Driftlock.git
cd Driftlock

# Create and activate virtual environment
python -m venv .venv

# On Linux / macOS:
source .venv/bin/activate
# On Windows (PowerShell):
.\.venv\Scripts\Activate.ps1

# Install clean production dependencies
pip install -r requirements.txt
pip install pytest -e .
```

---

### 2. Core Commands

#### Command 1: Run Built-In CLI Audit
Experience DriftLock's full audit lifecycle on the included demonstration fixtures:
```bash
python -m driftlock.cli.main demo
```
*Outputs the Rich AST diff tree, categorized breaking changes, and multi-artifact blast radius.*

#### Command 2: Closed-Loop Auto-Fix (`--fix`)
Run self-healing on stale artifacts and verify zero remaining drift:
```bash
python -m driftlock.cli.main demo --fix
```
*Creates a sandboxed workspace, executes `DriftRemediator`, renders syntax-highlighted unified Git diffs, and re-audits the repository to confirm full synchronization.*

#### Command 3: Launch Precision Web Control Plane
Start the FastAPI server and open the developer dashboard:
```bash
uvicorn driftlock.api.server:app --reload
```
Open **`http://localhost:8000`** in your browser to interact with:
- Dynamic Live Status Banner (`DRIFT DETECTED` ⇄ `REPOSITORY SYNCHRONIZED`)
- 4-Metric Bento KPI Row
- Interactive Blast Radius Dependency Graph with category filtering
- Multi-Tab Inspector: Unified Git Diffs, Alan Agent Brief, AST Side-by-Side, and Live AST Sandbox

#### Command 4: CI Gatekeeper Mode (`--ci`)
Enforce contract consistency in your GitHub Actions or pre-commit pipelines:
```bash
python -m driftlock.cli.main audit \
  --base fixtures/demo_repo/api_base.py \
  --head fixtures/demo_repo/api_head.py \
  --repo fixtures/demo_repo \
  --ci
```
*Exits with code `1` if breaking drift or stale artifacts exist (blocking CI merge). Exits with code `0` when contracts and artifacts are verified clean.*

---

## 💡 Engineering Decisions & Thought Process

### 1. Why Native AST Instead of LLM-as-a-Judge for Detection?
| Criterion | Native Python `ast` (DriftLock) | LLM-as-a-Judge / Prompting |
| :--- | :--- | :--- |
| **Determinism** | **100% deterministic**; identical output every run | Non-deterministic; prone to subtle drift and temperature jitter |
| **Execution Latency** | **< 5ms**; instantaneous AST tokenization | 1,500ms - 8,000ms per API round-trip |
| **Security & Isolation** | **Zero code execution**; safely inspects untrusted PRs | Susceptible to prompt injection in docstrings or comments |
| **Token Cost** | **$0.00**; runs completely offline | High recurring API costs on every commit or CI run |
| **Environment Fragility**| **Zero imports**; never fails on missing DBs or env vars | Traditional runtime reflection crashes on missing dependencies |

### 2. Why `AGENT_MEMORY` Must Be Synchronized
Modern engineering teams increasingly rely on prompt-context files (`AGENT_CONTEXT.md`, `CLAUDE.md`, `.cursorrules`) to guide autonomous agents. When an API contract shifts:
- If only backend code is updated, the agent's memory becomes outdated.
- Downstream agent invocations reference stale schema structures, hallucinating attributes that no longer exist or omitting required ones.
- DriftLock treats `[AGENT_MEMORY]` as a first-class AST dependency alongside `[TEST]` and `[DOCS]`, ensuring agents always work from the exact truth.

### 3. Isolated Sandboxes for Safe Remediation
Automated code patching can be dangerous if applied directly to live worktrees without verification. DriftLock's `DriftRemediator`:
1. Clones the impacted scope into a temporary workspace (`tempfile.mkdtemp`).
2. Applies targeted patches using AST/regex transformations or Open Model completions.
3. Runs a second pass of `BlastRadiusMapper` on the temporary workspace.
4. Only commits changes to the repository once post-audit confirms `total_impacted_files == 0`.

---

## 🤖 Alan AI Native Skill Integration

DriftLock includes an Alan AI Skill definition in [`.alan/skills/driftlock.md`](.alan/skills/driftlock.md) and [`SKILL.md`](SKILL.md).

Coding agents can execute the `/driftlock` command to:
1. Parse API base and head revisions.
2. Read the auto-generated **Remediation Brief** detailing exact reasons and suggested actions.
3. Automatically patch test payloads, doc tables, and agent rules.
4. Verify repository health prior to opening or approving pull requests.

---

## 🧪 Comprehensive Test Suite

DriftLock maintains a 100% passing test suite across parser determinism, diff logic, blast radius mapping, closed-loop remediation, and REST API endpoints:

```bash
pytest tests/ -v
```

```
collected 42 items

tests/test_api.py::test_api_health PASSED
tests/test_api.py::test_api_demo PASSED
tests/test_api.py::test_api_remediate PASSED
tests/test_api.py::test_api_custom_audit PASSED
tests/test_api.py::test_serve_index PASSED
tests/test_diff_and_blast.py::TestComputeContractDiff::test_drift_detected PASSED
tests/test_diff_and_blast.py::TestComputeContractDiff::test_has_breaking_drift PASSED
tests/test_diff_and_blast.py::TestComputeContractDiff::test_field_added_breaking PASSED
tests/test_diff_and_blast.py::TestComputeContractDiff::test_field_added_non_breaking PASSED
tests/test_diff_and_blast.py::TestComputeContractDiff::test_field_type_changed PASSED
tests/test_diff_and_blast.py::TestComputeContractDiff::test_route_added PASSED
tests/test_diff_and_blast.py::TestBlastRadiusMapper::test_blast_radius_detects_stale_test PASSED
tests/test_diff_and_blast.py::TestBlastRadiusMapper::test_blast_radius_detects_stale_agent_context PASSED
tests/test_diff_and_blast.py::TestBlastRadiusMapper::test_blast_radius_detects_stale_docs PASSED
tests/test_diff_and_blast.py::TestCLIDemo::test_audit_command_ci_flag_drift_detected_fails PASSED
tests/test_diff_and_blast.py::TestCLIDemo::test_audit_command_ci_flag_clean_contract_passes PASSED
tests/test_remediation.py::TestDriftRemediator::test_remediation_reduces_impacted_to_zero PASSED
tests/test_remediation.py::TestDriftRemediator::test_remediation_patches_test_file PASSED
tests/test_remediation.py::TestDriftRemediator::test_remediation_patches_agent_memory PASSED
...
======================== 42 passed in 2.19s ========================
```

---

## ☁️ Deployment

### 1-Click Deployment on Render
A `render.yaml` blueprint and `Procfile` are included for effortless cloud deployment:

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com)

```bash
# Manual container or process launch:
uvicorn driftlock.api.server:app --host 0.0.0.0 --port ${PORT:-8000}
```

### GitHub Actions CI
The workflow in `.github/workflows/driftlock.yml` automatically validates pull requests on Python 3.11 and 3.12:
- Runs full `pytest` suite
- Verifies `python -m driftlock.cli.main demo`
- Verifies closed-loop self-healing with `python -m driftlock.cli.main demo --fix`

---

## 📂 Repository Structure

```
driftlock/
├── .alan/skills/
│   └── driftlock.md          # Alan AI Skill specification
├── .github/workflows/
│   └── driftlock.yml         # CI workflow for pytest and contract verification
├── driftlock/
│   ├── core/
│   │   ├── parser.py         # Zero-LLM AST visitor & contract extractor
│   │   ├── models.py         # Pydantic data models for schemas & routes
│   │   └── diff.py           # Contract diff engine (breaking vs non-breaking)
│   ├── blast_radius/
│   │   └── graph.py          # Multi-artifact blast radius mapper & briefs
│   ├── sync/
│   │   └── remediator.py     # Closed-loop auto-remediation engine
│   ├── api/
│   │   └── server.py         # FastAPI backend server with REST endpoints
│   └── cli/
│       └── main.py           # Typer CLI with Rich terminal formatting & --ci
├── fixtures/demo_repo/       # Built-in demo fixtures (API, tests, docs, agent memory)
├── tests/                    # 42 unit and integration tests
├── web/
│   └── index.html            # Dark-mode developer control plane (Stitch MCP design)
├── Procfile                  # Dyno process definition
├── render.yaml               # Render cloud deployment blueprint
├── requirements.txt          # Clean production dependencies
├── pyproject.toml            # Package definition and build configuration
└── SKILL.md                  # Root skill descriptor
```

---

## 📄 License

DriftLock is licensed under the [MIT License](LICENSE).
