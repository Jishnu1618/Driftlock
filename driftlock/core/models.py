"""Data models representing extracted AST API contracts and Pydantic schemas."""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field


class ParamDefinition(BaseModel):
    """Represents a parameter in a route endpoint definition."""

    name: str
    type_annotation: Optional[str] = None
    default_value: Optional[str] = None
    is_required: bool = True
    kind: str = "query"  # "path", "query", "body", "header", "cookie", "dependency"
    description: Optional[str] = None


class RouteDefinition(BaseModel):
    """Represents an extracted API route / endpoint."""

    path: str
    http_methods: list[str] = Field(default_factory=list)
    function_name: str
    parameters: list[ParamDefinition] = Field(default_factory=list)
    return_type: Optional[str] = None
    response_model: Optional[str] = None
    status_code: Optional[str | int] = None
    summary: Optional[str] = None
    description: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    line_number: int
    end_line_number: int
    is_async: bool = False
    decorator_raw: Optional[str] = None

    @property
    def endpoint_id(self) -> str:
        """Returns a normalized unique identifier for the route (e.g., 'GET /users/{id}')."""
        method = self.http_methods[0] if self.http_methods else "ANY"
        return f"{method.upper()} {self.path}"


class FieldDefinition(BaseModel):
    """Represents a single field inside a Pydantic schema model."""

    name: str
    type_annotation: str
    default_value: Optional[str] = None
    is_required: bool = True
    description: Optional[str] = None
    constraints: dict[str, Any] = Field(default_factory=dict)
    line_number: int


class SchemaDefinition(BaseModel):
    """Represents an extracted Pydantic schema model."""

    name: str
    base_classes: list[str] = Field(default_factory=list)
    fields: list[FieldDefinition] = Field(default_factory=list)
    docstring: Optional[str] = None
    line_number: int
    end_line_number: int
    is_pydantic: bool = True

    def get_field(self, field_name: str) -> Optional[FieldDefinition]:
        """Lookup a field by name."""
        for f in self.fields:
            if f.name == field_name:
                return f
        return None


class ContractSnapshot(BaseModel):
    """Snapshot of all extracted routes, schemas, and contract elements from an AST."""

    file_path: Optional[str] = None
    routes: list[RouteDefinition] = Field(default_factory=list)
    schemas: list[SchemaDefinition] = Field(default_factory=list)
    imports: list[str] = Field(default_factory=list)

    def get_route(self, method: str, path: str) -> Optional[RouteDefinition]:
        """Find a route by HTTP method and path."""
        method_upper = method.upper()
        for r in self.routes:
            if method_upper in [m.upper() for m in r.http_methods] and r.path == path:
                return r
        return None

    def get_schema(self, name: str) -> Optional[SchemaDefinition]:
        """Find a schema by class name."""
        for s in self.schemas:
            if s.name == name:
                return s
        return None
