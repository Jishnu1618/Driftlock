# DriftLock 🔒

**Autonomous AST Drift and Contract Consistency Engine**  
*Deterministically synchronizing API contracts, tests, documentation, and AI agent memory.*

[![Python Version](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-35%20passed-brightgreen.svg)](tests/)
[![Analysis](https://img.shields.io/badge/AST%20Parser-Zero--LLM%20Deterministic-orange.svg)](#core-engine)
[![Frameworks](https://img.shields.io/badge/supports-FastAPI%20%7C%20Flask%20%7C%20Pydantic%20v1%2Fv2-purple.svg)](#supported-frameworks)
[![UI](https://img.shields.io/badge/Dashboard-Streamlit%20Dark-ff4b4b.svg)](#-interactive-web-dashboard)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## ⚡ The Problem

Modern software development moves at breakneck speed. When human developers or AI coding agents update API schemas or endpoints—such as adding a required field to a Pydantic model or modifying a route signature—silent contract drift occurs:

1. **🧪 Tests Silently Rot**: Test fixtures and assertions omit newly required fields, leading to runtime failures or false positives.
2. **📖 Documentation Desynchronizes**: Markdown specs, READMEs, and API references describe outdated schemas.
3. **🤖 AI Agent Hallucinations**: Agent memory files (`AGENT_CONTEXT.md`, system prompts, instructions) preserve stale contract assumptions. The agent continues generating code for outdated schemas, causing cascading bugs.
4. **💥 Unsafe Runtime Introspection**: Traditional tools import or execute target modules, triggering environment variable crashes, database connection failures, and missing dependency errors.

---

## 🎯 The Solution: DriftLock

**DriftLock** provides a zero-execution, deterministic consistency engine that guarantees your codebase and AI agent memory stay aligned with your API contracts:

- **Deterministic Zero-LLM Parser**: Analyzes Python code using the native `ast` module. Never imports or executes code—completely side-effect free, instant, and secure.
- **Contract Diffing Engine**: Compares base and head contracts, classifying changes into breaking vs. non-breaking drifts (`FIELD_ADDED`, `FIELD_REMOVED`, `FIELD_TYPE_CHANGED`, `ROUTE_ADDED`, `ROUTE_REMOVED`).
- **Blast Radius Mapper**: Traverses the repository to detect impacted files across **Tests**, **Documentation**, and **Agent Memory** (`AGENT_CONTEXT.md`).
- **Remediation Brief Synthesis**: Automatically generates structured action briefs with precise instructions for AI agents (e.g. Alan AI, Claude, Qwen) or developers to repair stale references.
- **⚡ Closed-Loop Remediation Engine (`--fix`)**: Automatically patches impacted test files, markdown documentation tables, and agent context instructions, then performs an immediate re-audit to verify 0 stale artifacts remain.
- **🌐 Interactive Web Dashboard (`app.py`)**: A modern dark-themed Streamlit dashboard with side-by-side AST comparisons, live contract playground, and 1-click self-healing.
- **🤖 Alan AI Native Skill (`/driftlock`)**: Integrated skill specification in `.alan/skills/driftlock.md` and root `SKILL.md` enabling coding agents to audit and remediate repositories autonomously.

---

## 🏗 Architecture Overview

```mermaid
flowchart TD
    subgraph Input ["Source Code"]
        Base["Base API Contract\n(git base / branch)"]
        Head["Head API Contract\n(worktree / PR)"]
    end

    subgraph CoreEngine ["DriftLock Engine"]
        ASTParser["Deterministic AST Parser\n(Zero-LLM, Native ast)"]
        DiffEngine["Contract Diff Engine\n(Breaking vs Non-Breaking)"]
        BlastMapper["Blast Radius Mapper\n(Repo Dependency Graph)"]
        Remediator["Closed-Loop Remediator\n(Deterministic + Open Model API)"]
    end

    subgraph Output ["Impact & Self-Healing"]
        Tests["🧪 Tests (test_*.py)"]
        Docs["📖 Docs (*.md)"]
        AgentContext["🤖 Agent Memory (AGENT_CONTEXT.md)"]
        CLI["💻 Rich Terminal UI / JSON / --fix"]
        WebUI["🌐 Streamlit Dashboard (app.py)"]
        AlanSkill["🤖 Alan AI Skill (/driftlock)"]
    end

    Base --> ASTParser
    Head --> ASTParser
    ASTParser --> DiffEngine
    DiffEngine --> BlastMapper
    BlastMapper --> Tests
    BlastMapper --> Docs
    BlastMapper --> AgentContext
    BlastMapper --> Remediator
    Remediator --> Tests
    Remediator --> Docs
    Remediator --> AgentContext
    DiffEngine --> CLI
    BlastMapper --> CLI
    Remediator --> CLI
    Remediator --> WebUI
    Remediator --> AlanSkill
```

---

## 🚀 Quickstart

### 1. Prerequisites
- Python 3.11+
- Git

### 2. Installation

```bash
# Clone repository
git clone https://github.com/Jishnu1618/Driftlock.git
cd Driftlock

# Set up virtual environment
python -m venv .venv

# On Linux / macOS:
source .venv/bin/activate

# On Windows (PowerShell):
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
pip install streamlit
```

### 3. Run the Test Suite

```bash
pytest tests/ -v
```

All 35 deterministic unit and integration tests will execute cleanly:
- 8 parser unit tests
- 19 diff, blast radius, and CLI tests
- 8 remediation and closed-loop verification tests

---

## 💻 CLI Usage

DriftLock provides a Typer-powered CLI with Rich terminal formatting, machine-readable JSON exports, and self-healing.

### Run End-to-End Demo

Experience DriftLock's full audit lifecycle on the included demonstration fixtures:

```bash
python -m driftlock.cli.main demo
```

### Run Closed-Loop Self-Healing (`--fix`)

Detect drift, patch impacted files, and verify zero stale artifacts remain:

```bash
python -m driftlock.cli.main demo --fix
```

When run with `--fix`:
1. Isolated copy of `fixtures/demo_repo` is created in a temporary directory (original fixtures are never mutated).
2. Initial audit executes and displays the `X DRIFT DETECTED` output and Blast Radius tree.
3. `DriftRemediator` patches `test_users.py`, `README.md`, and `AGENT_CONTEXT.md`.
4. Unified Git diff panels are rendered showing exact lines added.
5. Re-scan confirms: `✓ REPOSITORY SYNCHRONIZED — 0 Stale Artifacts Remaining (3/3 Fixed)`.

### Audit Real API Contracts

Audit two versions of an API contract against a target repository:

```bash
python -m driftlock.cli.main audit path/to/base_api.py path/to/head_api.py --repo .
```

Options:
- `--repo PATH`: Root directory to scan for blast radius dependencies (default: `.`)
- `--fix`: Automatically remediate impacted files after auditing
- `--json`: Output report as formatted JSON instead of terminal tables and trees

---

## 🌐 Interactive Web Dashboard

Launch the interactive dark-themed web dashboard for live demos and hackathon judging:

```bash
streamlit run app.py
```

### Dashboard Features:
1. **Scenario Selector**:
   - `PR #42: UserCreate Schema Expansion` (preloaded scenario from `fixtures/demo_repo`)
   - `Live Contract Playground` (interactive side-by-side Python code editor for custom contracts)
2. **Metric Cards**: Real-time counter of Breaking Changes, Non-Breaking Changes, Stale Tests, Stale Docs, and Stale Agent Memory.
3. **Side-by-Side AST Diff**: Deep structural comparison of schemas, fields, routes, and decorators.
4. **Blast Radius Breakdown**: Visual inspection of downstream dependencies and risk ratings.
5. **Alan AI Brief**: Instant generation of structured remediation prompts for AI agents.
6. **⚡ 1-Click Auto-Remediation**: Executes `DriftRemediator`, renders syntax-highlighted unified Git diffs, and flips status from `DRIFT DETECTED` to `✓ ALL CONTRACTS IN SYNC`.

---

## 🤖 Alan AI Agent Integration (`/driftlock`)

DriftLock provides native skill specifications:
- Root [SKILL.md](SKILL.md)
- Custom Alan skill [.alan/skills/driftlock.md](.alan/skills/driftlock.md)

### Agent Workflow:
```
1. Developer triggers: "/driftlock audit"
2. Alan Agent runs: "python -m driftlock.cli.main audit <base> <head> --repo ."
3. Alan Agent consumes the structured Remediation Brief.
4. Alan Agent applies patches or executes: "python -m driftlock.cli.main demo --fix"
5. Alan Agent verifies repository synchronization with zero regressions.
```

---

## 🔍 Supported Frameworks & AST Capabilities

DriftLock operates without code execution, parsing abstract syntax trees via Python's `ast` module:

| Framework / Feature | Supported Patterns | Extracted Metadata |
| :--- | :--- | :--- |
| **FastAPI** | `@app.get`, `@app.post`, `@router.put`, `@router.delete` | URL path, HTTP verb, status code, response model, path parameters, query params, `Depends`, `Header`, request body |
| **Flask / Starlette** | `@app.route(...)`, `@bp.route(...)` | Endpoint path, allowed methods, view function docstrings |
| **Pydantic v1 & v2** | `class Model(BaseModel):` | Field names, type annotations, defaults, required vs. optional status |
| **Pydantic Constraints** | `Field(..., ge=0, min_length=3)` | Numeric bounds (`ge`, `gt`, `le`, `lt`), string lengths, regex patterns |
| **Annotated Metadata** | `Annotated[str, Field(min_length=1)]` | Unpacks nested typing wrappers and extracts inner metadata |
| **Stacked Decorators** | Multiple route decorators on a single function | Discovers all distinct URL endpoints and verbs |
| **Docstrings** | Function docstrings & PEP 257 attribute docstrings | Contextual documentation associated with models and endpoints |

---

## 📂 Project Structure

```
Driftlock/
├── .alan/
│   └── skills/
│       └── driftlock.md        # Alan AI skill specification
├── driftlock/
│   ├── core/
│   │   ├── models.py           # Pydantic contract definitions (Routes, Schemas, Fields)
│   │   ├── parser.py           # Native AST parser (Zero-LLM static extractor)
│   │   └── diff.py             # Contract diffing engine (Breaking vs. Safe classification)
│   ├── blast_radius/
│   │   └── graph.py            # Blast radius mapper (Tests, Docs, Agent Memory)
│   ├── sync/
│   │   └── remediator.py       # Closed-loop self-healing engine (AST/Regex + Open Model API)
│   └── cli/
│       └── main.py             # Typer + Rich terminal UI & --fix automation
├── fixtures/
│   └── demo_repo/              # Complete drift scenario fixtures
│       ├── api_base.py         # Original contract
│       ├── api_head.py         # Modified contract (drifted)
│       ├── AGENT_CONTEXT.md    # Stale AI agent context
│       ├── README.md           # Stale documentation
│       └── tests/
│           └── test_users.py   # Stale unit test
├── tests/
│   ├── test_parser.py          # 8 parser unit tests
│   ├── test_diff_and_blast.py  # 19 diff, blast radius, and CLI integration tests
│   └── test_remediation.py     # 8 closed-loop remediation & --fix verification tests
├── app.py                      # Interactive Streamlit Web Dashboard
├── SKILL.md                    # Root AI agent skill specification
├── DRIFTLOCK_STATE.md          # Architecture log & phase tracker
├── dev_phases.md               # Phase roadmap specification
├── pyproject.toml              # Project configuration & pytest settings
├── requirements.txt            # Project dependencies
└── README.md                   # Project documentation
```

---

## 🗺 Roadmap & Phase Progression

| Phase | Milestone | Deliverables | Status |
| :---: | :--- | :--- | :---: |
| **1** | **AST Contract Parser** | Deterministic route & schema extraction with zero-LLM overhead | 🟢 Complete |
| **2** | **Blast Radius Graph** | Map AST diffs to impacted tests, docs, and `AGENT_CONTEXT.md` | 🟢 Complete |
| **3** | **Remediation Brief** | Synthesize actionable repair instructions for AI agents | 🟢 Complete |
| **4** | **Terminal Visualizer & CLI** | Rich tree & table UI with JSON output for CI/CD | 🟢 Complete |
| **5** | **Closed-Loop Remediation** | Self-healing engine with `--fix` and git diff generation | 🟢 Complete |
| **6** | **Interactive Web Dashboard**| Streamlit dark-theme UI with 1-click self-healing & custom editor | 🟢 Complete |
| **7** | **Alan AI Skill** | Native `/driftlock` skill for automated agent consistency workflows | 🟢 Complete |

---

## 🤝 Contributing

Contributions are welcome! Please open an issue or submit a pull request:

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Ensure all tests pass (`pytest tests/ -v`)
4. Commit your changes (`git commit -m 'feat: add amazing feature'`)
5. Push to the branch (`git push origin feature/amazing-feature`)
6. Open a Pull Request

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
