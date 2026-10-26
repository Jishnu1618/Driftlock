"""Tests for DriftLock AST Contract Parser."""

import pytest
from driftlock.core.parser import parse_code, parse_file


SAMPLE_FASTAPI_APP = '''
from typing import Optional, List
from fastapi import FastAPI, APIRouter, Depends, Query, Header, status
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1")

class UserRole(BaseModel):
    name: str = Field(..., description="Role name", min_length=2)
    permissions: List[str] = Field(default_factory=list)

class UserCreate(BaseModel):
    """Payload to create a user."""
    username: str = Field(..., min_length=3, max_length=50, description="Unique username")
    email: str
    """User email address."""
    age: Optional[int] = Field(default=None, ge=0, le=120)
    role: UserRole

class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    is_active: bool = True

@router.get("/users/{user_id}", response_model=UserResponse, summary="Get User Details")
async def get_user(
    user_id: int,
    include_role: bool = Query(default=False, description="Include user role info"),
    auth_token: str = Header(..., description="Bearer token")
) -> UserResponse:
    """Retrieve user details by ID."""
    pass

@router.post("/users", response_model=UserResponse, status_code=201)
async def create_user(
    payload: UserCreate,
    notify: bool = True,
) -> UserResponse:
    """Create a new user in the system."""
    pass
'''

SAMPLE_FLASK_APP = '''
from flask import Blueprint

bp = Blueprint("auth", __name__)

@bp.route("/login", methods=["GET", "POST"])
def login(redirect_url: str = "/"):
    """Handle user login authentication."""
    pass
'''


def test_parse_pydantic_schemas():
    snapshot = parse_code(SAMPLE_FASTAPI_APP, filename="test_sample.py")

    assert len(snapshot.schemas) == 3

    # Check UserRole
    role_schema = snapshot.get_schema("UserRole")
    assert role_schema is not None
    assert role_schema.base_classes == ["BaseModel"]
    assert len(role_schema.fields) == 2

    name_field = role_schema.get_field("name")
    assert name_field is not None
    assert name_field.type_annotation == "str"
    assert name_field.is_required is True
    assert name_field.description == "Role name"
    assert name_field.constraints.get("min_length") == 2

    perms_field = role_schema.get_field("permissions")
    assert perms_field is not None
    assert perms_field.type_annotation == "List[str]"
    assert perms_field.is_required is False
    assert "<factory:" in perms_field.default_value

    # Check UserCreate
    user_create = snapshot.get_schema("UserCreate")
    assert user_create is not None
    assert user_create.docstring == "Payload to create a user."

    uname_field = user_create.get_field("username")
    assert uname_field.is_required is True
    assert uname_field.constraints.get("min_length") == 3
    assert uname_field.constraints.get("max_length") == 50

    email_field = user_create.get_field("email")
    assert email_field.is_required is True
    assert email_field.description == "User email address."

    age_field = user_create.get_field("age")
    assert age_field.is_required is False
    assert age_field.default_value == "None"
    assert age_field.constraints.get("ge") == 0
    assert age_field.constraints.get("le") == 120

    # Check UserResponse
    user_resp = snapshot.get_schema("UserResponse")
    assert user_resp is not None
    assert len(user_resp.fields) == 4
    active_field = user_resp.get_field("is_active")
    assert active_field.is_required is False
    assert active_field.default_value == "True"


def test_parse_fastapi_routes():
    snapshot = parse_code(SAMPLE_FASTAPI_APP, filename="test_sample.py")

    assert len(snapshot.routes) == 2

    # GET /users/{user_id}
    get_route = snapshot.get_route("GET", "/users/{user_id}")
    assert get_route is not None
    assert get_route.function_name == "get_user"
    assert get_route.is_async is True
    assert get_route.response_model == "UserResponse"
    assert get_route.summary == "Get User Details"
    assert get_route.description == "Retrieve user details by ID."
    assert get_route.return_type == "UserResponse"

    # Verify parameters
    params = {p.name: p for p in get_route.parameters}
    assert "user_id" in params
    assert params["user_id"].kind == "path"
    assert params["user_id"].is_required is True
    assert params["user_id"].type_annotation == "int"

    assert "include_role" in params
    assert params["include_role"].kind == "query"
    assert params["include_role"].is_required is False
    assert params["include_role"].description == "Include user role info"

    assert "auth_token" in params
    assert params["auth_token"].kind == "header"
    assert params["auth_token"].is_required is True
    assert params["auth_token"].description == "Bearer token"

    # POST /users
    post_route = snapshot.get_route("POST", "/users")
    assert post_route is not None
    assert post_route.function_name == "create_user"
    assert post_route.status_code == 201
    post_params = {p.name: p for p in post_route.parameters}
    assert "payload" in post_params
    assert post_params["payload"].kind == "body"
    assert post_params["payload"].type_annotation == "UserCreate"
    assert post_params["payload"].is_required is True

    assert "notify" in post_params
    assert post_params["notify"].kind == "query"
    assert post_params["notify"].is_required is False
    assert post_params["notify"].default_value == "True"


def test_parse_flask_route():
    snapshot = parse_code(SAMPLE_FLASK_APP, filename="flask_app.py")

    assert len(snapshot.routes) == 1
    route = snapshot.routes[0]
    assert route.path == "/login"
    assert set(route.http_methods) == {"GET", "POST"}
    assert route.function_name == "login"
    assert route.is_async is False
    assert route.parameters[0].name == "redirect_url"
    assert route.parameters[0].default_value == "'/'"


def test_parse_stacked_decorators():
    code = '''
@app.get("/items")
@app.post("/items")
def items():
    """Manage items."""
    pass
'''
    snapshot = parse_code(code)
    assert len(snapshot.routes) == 2
    paths = [(r.http_methods[0], r.path) for r in snapshot.routes]
    assert ("GET", "/items") in paths
    assert ("POST", "/items") in paths


def test_imports_extraction():
    snapshot = parse_code(SAMPLE_FASTAPI_APP)
    assert any("pydantic" in imp for imp in snapshot.imports)
    assert any("fastapi" in imp for imp in snapshot.imports)


def test_parse_file_roundtrip(tmp_path):
    test_file = tmp_path / "contracts.py"
    test_file.write_text(SAMPLE_FASTAPI_APP, encoding="utf-8")

    snapshot = parse_file(test_file)
    assert len(snapshot.routes) == 2
    assert len(snapshot.schemas) == 3
    assert snapshot.file_path == str(test_file)


def test_determinism():
    snap1 = parse_code(SAMPLE_FASTAPI_APP)
    snap2 = parse_code(SAMPLE_FASTAPI_APP)
    assert snap1.model_dump() == snap2.model_dump()


def test_parse_annotated_fastapi_and_pydantic():
    code = '''
from typing import Annotated
from fastapi import APIRouter, Header, Query
from pydantic import BaseModel, Field

router = APIRouter()

class ModernModel(BaseModel):
    bio: Annotated[str, Field(min_length=10, max_length=200, description="Bio summary")]
    score: Annotated[int, Field(ge=0, default=100)]

@router.get("/profile")
def get_profile(
    api_key: Annotated[str, Header(description="X-API-KEY")],
    page: Annotated[int, Query(description="Page index")] = 1
):
    pass
'''
    snapshot = parse_code(code)
    model = snapshot.get_schema("ModernModel")
    assert model is not None
    bio = model.get_field("bio")
    assert bio.type_annotation == "str"
    assert bio.is_required is True
    assert bio.description == "Bio summary"
    assert bio.constraints.get("min_length") == 10

    score = model.get_field("score")
    assert score.type_annotation == "int"
    assert score.is_required is False
    assert score.default_value == "100"
    assert score.constraints.get("ge") == 0

    route = snapshot.routes[0]
    api_key_param = [p for p in route.parameters if p.name == "api_key"][0]
    assert api_key_param.kind == "header"
    assert api_key_param.type_annotation == "str"
    assert api_key_param.description == "X-API-KEY"

    page_param = [p for p in route.parameters if p.name == "page"][0]
    assert page_param.kind == "query"
    assert page_param.default_value == "1"
    assert page_param.is_required is False

