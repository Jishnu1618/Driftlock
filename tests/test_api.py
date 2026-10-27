"""Unit tests for DriftLock FastAPI backend server."""

import pytest
from fastapi.testclient import TestClient

from driftlock.api.server import app

client = TestClient(app)


def test_api_health():
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"


def test_api_demo():
    res = client.get("/api/demo")
    assert res.status_code == 200
    data = res.json()
    assert "summary" in data
    assert data["summary"]["total_drifts"] >= 2
    assert data["summary"]["breaking_drifts"] >= 1
    assert data["summary"]["impacted_files_count"] == 3
    assert len({a["file_path"] for a in data["blast_radius"]}) == 3
    assert len(data["blast_radius"]) >= 3
    assert "remediation_brief" in data
    assert "base_code" in data
    assert "head_code" in data


def test_api_remediate():
    res = client.post("/api/remediate", json={"use_api": False})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["post_audit_impacted_files"] == 0
    assert data["is_synced"] is True
    assert len(data["patches"]) == 3
    for p in data["patches"]:
        assert "unified_diff" in p
        assert len(p["unified_diff"]) > 0


def test_api_custom_audit():
    base_code = """
class User(BaseModel):
    name: str
"""
    head_code = """
class User(BaseModel):
    name: str
    age: int
"""
    res = client.post("/api/custom-audit", json={"base_code": base_code, "head_code": head_code})
    assert res.status_code == 200
    data = res.json()
    assert data["has_drift"] is True
    assert data["total_drifts"] == 1
    assert data["drifts"][0]["category"] == "FIELD_ADDED"
    assert data["drifts"][0]["is_breaking"] is True


def test_api_custom_audit_with_routes():
    base_code = """
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class Item(BaseModel):
    title: str

@app.get("/items")
def get_items():
    return []
"""
    head_code = """
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class Item(BaseModel):
    title: str
    price: float

@app.get("/items")
def get_items():
    return []
"""
    res = client.post("/api/custom-audit", json={"base_code": base_code, "head_code": head_code})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["has_drift"] is True
    assert len(data["base_routes"]) == 1
    assert data["base_routes"][0]["method"] == "GET"
    assert data["base_routes"][0]["path"] == "/items"



def test_serve_index():
    res = client.get("/")
    assert res.status_code == 200
    assert "DriftLock" in res.text
    assert "Blast Radius Dependency Graph" in res.text
