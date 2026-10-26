# DriftLock

Autonomous AST drift and contract consistency engine.

## Overview
DriftLock statically extracts API contracts (FastAPI, Flask, Starlette route decorators and Pydantic schema models) using Python's native `ast` module—completely deterministic and zero-LLM—to detect drift between routes, schemas, tests, and documentation.

## Core Features (Phase 1)
- **Deterministic Zero-LLM Parser**: Safe static analysis using Python's native `ast` without executing or importing target modules.
- **Route Extraction**: Detects route decorators (`@app.get`, `@router.post`, `@bp.route`), URL paths, HTTP verbs, response models, status codes, and docstrings.
- **Parameter & Dependency Inference**: Extracts parameter types, defaults, and kinds (`path`, `query`, `body`, `dependency`, `header`, `cookie`).
- **Pydantic Schema Extraction**: Extracts typed fields, constraints (`min_length`, `ge`, etc.), defaults, attribute docstrings, and `typing.Annotated[T, Field(...)]` metadata for Pydantic v1 & v2.

## Quickstart

```bash
# Create virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Run test suite
pytest tests/ -v
```
