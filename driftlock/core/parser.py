"""Deterministic AST-based contract extractor for routes and Pydantic schemas.

Uses Python's native `ast` module to perform pure static analysis without
importing or executing target modules.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any, Optional, Union

from driftlock.core.models import (
    ContractSnapshot,
    FieldDefinition,
    ParamDefinition,
    RouteDefinition,
    SchemaDefinition,
)

# Standard HTTP verbs supported by FastAPI, Starlette, Flask, Litestar, etc.
HTTP_VERBS = {
    "get",
    "post",
    "put",
    "delete",
    "patch",
    "options",
    "head",
    "trace",
}

# Methods that designate routing
ROUTE_METHODS = HTTP_VERBS | {"route", "api_route"}

# Known base class names indicative of Pydantic models
PYDANTIC_BASE_INDICATORS = {
    "basemodel",
    "baseschema",
    "rootmodel",
    "genericmodel",
    "model",
    "schema",
}


class ASTContractParser(ast.NodeVisitor):
    """AST visitor that deterministically extracts route decorators and Pydantic schema models."""

    def __init__(self, filename: Optional[str] = None):
        self.filename = filename or "<string>"
        self.routes: list[RouteDefinition] = []
        self.schemas: list[SchemaDefinition] = []
        self.imports: list[str] = []
        self._class_depth = 0

    def visit_Import(self, node: ast.Import) -> None:
        """Record module imports."""
        for alias in node.names:
            name = alias.name
            if alias.asname:
                name += f" as {alias.asname}"
            self.imports.append(f"import {name}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Record from-module imports."""
        mod = node.module or ""
        aliases = []
        for alias in node.names:
            name = alias.name
            if alias.asname:
                name += f" as {alias.asname}"
            aliases.append(name)
        self.imports.append(f"from {mod} import {', '.join(aliases)}")
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Extract Pydantic schema models and their field definitions."""
        self._class_depth += 1
        base_classes = [ast.unparse(b) for b in node.bases]

        is_pydantic = self._is_pydantic_model(node, base_classes)

        if is_pydantic:
            fields = self._extract_schema_fields(node)
            docstring = ast.get_docstring(node)

            schema = SchemaDefinition(
                name=node.name,
                base_classes=base_classes,
                fields=fields,
                docstring=docstring,
                line_number=node.lineno,
                end_line_number=getattr(node, "end_lineno", node.lineno),
                is_pydantic=is_pydantic,
            )
            self.schemas.append(schema)

        # Continue traversing inner classes/methods if any
        self.generic_visit(node)
        self._class_depth -= 1

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Inspect functions for route decorators."""
        self._inspect_function(node, is_async=False)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Inspect async functions for route decorators."""
        self._inspect_function(node, is_async=True)
        self.generic_visit(node)

    # -------------------------------------------------------------------------
    # Route Extraction Logic
    # -------------------------------------------------------------------------

    def _inspect_function(
        self,
        node: Union[ast.FunctionDef, ast.AsyncFunctionDef],
        is_async: bool,
    ) -> None:
        """Extract routes for any matching route decorator on the function."""
        # Check decorators for routing patterns
        for decorator in node.decorator_list:
            route_info = self._parse_route_decorator(decorator)
            if not route_info:
                continue

            path, http_methods, extra_kwargs = route_info
            parameters = self._extract_function_parameters(node, path, http_methods)
            return_type = ast.unparse(node.returns) if node.returns else None
            docstring = ast.get_docstring(node)

            # Resolve summary
            summary = extra_kwargs.get("summary")
            if not summary and docstring:
                summary = docstring.strip().split("\n")[0].strip()

            route = RouteDefinition(
                path=path,
                http_methods=http_methods,
                function_name=node.name,
                parameters=parameters,
                return_type=return_type,
                response_model=extra_kwargs.get("response_model"),
                status_code=extra_kwargs.get("status_code"),
                summary=summary,
                description=extra_kwargs.get("description") or docstring,
                tags=extra_kwargs.get("tags", []),
                line_number=node.lineno,
                end_line_number=getattr(node, "end_lineno", node.lineno),
                is_async=is_async,
                decorator_raw=ast.unparse(decorator),
            )
            self.routes.append(route)

    def _parse_route_decorator(
        self, decorator: ast.expr
    ) -> Optional[tuple[str, list[str], dict[str, Any]]]:
        """Parse an AST decorator node to check if it's an API route decorator.

        Returns (path, [http_methods], extra_kwargs) or None.
        """
        if not isinstance(decorator, ast.Call):
            return None

        func = decorator.func
        method_name = ""

        # Case 1: @router.get(...) or @app.post(...)
        if isinstance(func, ast.Attribute):
            method_name = func.attr.lower()
        # Case 2: @get(...) or @post(...)
        elif isinstance(func, ast.Name):
            method_name = func.id.lower()
        else:
            return None

        if method_name not in ROUTE_METHODS:
            return None

        # Extract path & keyword arguments
        path = ""
        extra_kwargs: dict[str, Any] = {}
        http_methods: list[str] = []

        # Check positional args: arg 0 is path
        if decorator.args:
            path_node = decorator.args[0]
            if isinstance(path_node, ast.Constant) and isinstance(path_node.value, str):
                path = path_node.value
            else:
                path = ast.unparse(path_node).strip("'\"")

        # Process keyword arguments
        for kw in decorator.keywords:
            if not kw.arg:
                continue
            if kw.arg in {"path", "rule"} and not path:
                if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    path = kw.value.value
                else:
                    path = ast.unparse(kw.value).strip("'\"")
            elif kw.arg == "methods":
                # e.g. methods=["GET", "POST"]
                methods_extracted = self._extract_literal_list(kw.value)
                http_methods.extend([m.upper() for m in methods_extracted])
            elif kw.arg == "response_model":
                extra_kwargs["response_model"] = ast.unparse(kw.value)
            elif kw.arg == "status_code":
                if isinstance(kw.value, ast.Constant):
                    extra_kwargs["status_code"] = kw.value.value
                else:
                    extra_kwargs["status_code"] = ast.unparse(kw.value)
            elif kw.arg == "summary":
                if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    extra_kwargs["summary"] = kw.value.value
                else:
                    extra_kwargs["summary"] = ast.unparse(kw.value)
            elif kw.arg == "description":
                if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    extra_kwargs["description"] = kw.value.value
                else:
                    extra_kwargs["description"] = ast.unparse(kw.value)
            elif kw.arg == "tags":
                extra_kwargs["tags"] = self._extract_literal_list(kw.value)

        # Determine HTTP methods
        if method_name in HTTP_VERBS:
            if not http_methods:
                http_methods = [method_name.upper()]
        elif method_name in {"route", "api_route"}:
            if not http_methods:
                http_methods = ["GET"]

        if not path and not http_methods:
            return None

        return path, http_methods, extra_kwargs

    def _extract_function_parameters(
        self,
        node: Union[ast.FunctionDef, ast.AsyncFunctionDef],
        path: str,
        http_methods: list[str],
    ) -> list[ParamDefinition]:
        """Extract parameter definitions, type annotations, defaults, and kinds."""
        parameters: list[ParamDefinition] = []

        # Positional args (posonlyargs + args)
        all_pos_args = node.args.posonlyargs + node.args.args
        num_defaults = len(node.args.defaults)
        # Defaults align to the right of positional arguments
        first_default_idx = len(all_pos_args) - num_defaults

        for i, arg in enumerate(all_pos_args):
            # Skip self/cls in method definitions
            if arg.arg in {"self", "cls"} and self._class_depth > 0:
                continue

            default_node = None
            if i >= first_default_idx:
                default_node = node.args.defaults[i - first_default_idx]

            param = self._build_param(arg, default_node, path, http_methods)
            parameters.append(param)

        # Keyword-only args
        for arg, default_node in zip(node.args.kwonlyargs, node.args.kw_defaults):
            param = self._build_param(arg, default_node, path, http_methods)
            parameters.append(param)

        return parameters

    def _unpack_annotated(self, annotation_node: Optional[ast.expr]) -> tuple[Optional[str], list[ast.expr]]:
        """Unpack typing.Annotated[BaseType, Metadata...] if present."""
        if not annotation_node or not isinstance(annotation_node, ast.Subscript):
            return (ast.unparse(annotation_node) if annotation_node else None, [])

        val_str = ast.unparse(annotation_node.value).split(".")[-1]
        if val_str != "Annotated":
            return (ast.unparse(annotation_node), [])

        # Subscript slice in Python 3.9+ AST
        slice_node = annotation_node.slice
        if isinstance(slice_node, ast.Tuple) and slice_node.elts:
            base_type_str = ast.unparse(slice_node.elts[0])
            metadata_nodes = slice_node.elts[1:]
            return (base_type_str, metadata_nodes)

        return (ast.unparse(annotation_node), [])

    def _build_param(
        self,
        arg: ast.arg,
        default_node: Optional[ast.expr],
        path: str,
        http_methods: list[str],
    ) -> ParamDefinition:
        """Construct a ParamDefinition from an AST argument and default expression."""
        name = arg.arg
        type_annotation, metadata_nodes = self._unpack_annotated(arg.annotation)
        default_value: Optional[str] = None
        is_required = True
        kind = "query"
        description: Optional[str] = None

        # Inspect any metadata in Annotated[T, ...]
        for meta in metadata_nodes:
            if isinstance(meta, ast.Call):
                call_func = ast.unparse(meta.func).lower()
                if "depends" in call_func:
                    kind = "dependency"
                elif "path" in call_func:
                    kind = "path"
                elif "body" in call_func:
                    kind = "body"
                elif "header" in call_func:
                    kind = "header"
                elif "cookie" in call_func:
                    kind = "cookie"
                elif "query" in call_func:
                    kind = "query"

                for kw in meta.keywords:
                    if kw.arg == "description" and isinstance(kw.value, ast.Constant):
                        description = str(kw.value.value)

        if default_node is not None:
            default_str = ast.unparse(default_node)

            # Check if default is Ellipsis (...)
            if (
                isinstance(default_node, ast.Constant)
                and default_node.value is ...
            ) or default_str == "...":
                is_required = True
                default_value = None
            else:
                default_value = default_str
                is_required = False

            # Inspect calls like Query(...), Path(...), Depends(...), Body(...)
            if isinstance(default_node, ast.Call):
                call_func = ast.unparse(default_node.func).lower()
                if "depends" in call_func:
                    kind = "dependency"
                elif "path" in call_func:
                    kind = "path"
                elif "body" in call_func:
                    kind = "body"
                elif "header" in call_func:
                    kind = "header"
                elif "cookie" in call_func:
                    kind = "cookie"
                elif "query" in call_func:
                    kind = "query"

                # Check if first arg or default keyword is Ellipsis
                if default_node.args:
                    first_arg_str = ast.unparse(default_node.args[0])
                    if first_arg_str == "...":
                        is_required = True

                for kw in default_node.keywords:
                    if kw.arg == "description" and isinstance(kw.value, ast.Constant):
                        description = str(kw.value.value)
                    elif kw.arg == "default":
                        if ast.unparse(kw.value) == "...":
                            is_required = True
                        else:
                            is_required = False

        # If not explicitly marked as a special kind, apply heuristics:
        if kind == "query":
            # 1. Path parameter check (e.g., '/items/{item_id}' or '<item_id>')
            if re.search(rf"\{{{name}(?::[a-zA-Z0-9_]+)?\}}", path) or re.search(
                rf"<(?:\w+:)?{name}>", path
            ):
                kind = "path"
                # Path parameters in FastAPI are always required
                is_required = True
            # 2. Body parameter heuristic: In POST/PUT/PATCH, complex types default to body
            elif any(m in {"POST", "PUT", "PATCH"} for m in http_methods):
                if type_annotation and self._is_probable_body_type(type_annotation):
                    kind = "body"

        return ParamDefinition(
            name=name,
            type_annotation=type_annotation,
            default_value=default_value,
            is_required=is_required,
            kind=kind,
            description=description,
        )

    def _is_probable_body_type(self, type_str: str) -> bool:
        """Heuristic check whether a type annotation refers to a Pydantic schema or body model."""
        clean = type_str.strip()
        # Primitive or common scalar types are typically query/path params
        scalars = {
            "str",
            "int",
            "float",
            "bool",
            "bytes",
            "datetime",
            "date",
            "time",
            "uuid",
            "uuid.UUID",
            "Optional[str]",
            "Optional[int]",
            "Optional[float]",
            "Optional[bool]",
        }
        if clean in scalars:
            return False
        # Capitalized custom types like UserCreate, ItemPayload, dict, etc.
        if clean[0].isupper() or clean.startswith("dict") or clean.startswith("list"):
            return True
        return False

    # -------------------------------------------------------------------------
    # Schema Extraction Logic
    # -------------------------------------------------------------------------

    def _is_pydantic_model(self, node: ast.ClassDef, base_classes: list[str]) -> bool:
        """Determine whether a class definition is a Pydantic model."""
        # 1. Check base class names
        for base in base_classes:
            clean_base = base.lower().split(".")[-1]
            if clean_base in PYDANTIC_BASE_INDICATORS:
                return True
            if clean_base.endswith("schema") or clean_base.endswith("model"):
                return True

        # 2. Check if body defines Config or model_config or has Field assignments
        for stmt in node.body:
            if isinstance(stmt, ast.AnnAssign):
                if isinstance(stmt.value, ast.Call):
                    func_str = ast.unparse(stmt.value.func).lower()
                    if "field" in func_str:
                        return True
            elif isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if isinstance(target, ast.Name) and target.id == "model_config":
                        return True
            elif isinstance(stmt, ast.ClassDef) and stmt.name == "Config":
                return True

        return False

    def _extract_schema_fields(self, node: ast.ClassDef) -> list[FieldDefinition]:
        """Extract typed fields from a Pydantic model AST."""
        fields: list[FieldDefinition] = []

        for i, stmt in enumerate(node.body):
            if not isinstance(stmt, ast.AnnAssign):
                continue

            # Target must be a simple variable name (skip dunder/private attributes)
            if not isinstance(stmt.target, ast.Name):
                continue

            field_name = stmt.target.id
            if field_name.startswith("__") and field_name.endswith("__"):
                continue

            type_annotation, metadata_nodes = self._unpack_annotated(stmt.annotation)
            default_value: Optional[str] = None
            is_required = True
            description: Optional[str] = None
            constraints: dict[str, Any] = {}

            # Parse any Field(...) calls found inside Annotated[T, Field(...)]
            for meta in metadata_nodes:
                if isinstance(meta, ast.Call):
                    func_name = ast.unparse(meta.func).lower().split(".")[-1]
                    if func_name == "field":
                        field_info = self._parse_field_call(meta)
                        if field_info["description"]:
                            description = field_info["description"]
                        if field_info["constraints"]:
                            constraints.update(field_info["constraints"])
                        if field_info["default_value"] is not None:
                            default_value = field_info["default_value"]
                            is_required = field_info["is_required"]

            if stmt.value is None:
                # If required wasn't altered by Annotated metadata
                if default_value is None:
                    is_required = True
            else:
                val_node = stmt.value
                val_str = ast.unparse(val_node)

                # Ellipsis constant
                if (
                    isinstance(val_node, ast.Constant) and val_node.value is ...
                ) or val_str == "...":
                    is_required = True
                    default_value = None
                elif isinstance(val_node, ast.Call):
                    func_name = ast.unparse(val_node.func).lower().split(".")[-1]
                    if func_name == "field":
                        # Parse Field(...) call
                        field_info = self._parse_field_call(val_node)
                        is_required = field_info["is_required"]
                        default_value = field_info["default_value"]
                        description = field_info["description"]
                        constraints = field_info["constraints"]
                    else:
                        default_value = val_str
                        is_required = False
                else:
                    default_value = val_str
                    is_required = False

            # Check if immediately followed by an attribute docstring
            if not description and i + 1 < len(node.body):
                next_stmt = node.body[i + 1]
                if (
                    isinstance(next_stmt, ast.Expr)
                    and isinstance(next_stmt.value, ast.Constant)
                    and isinstance(next_stmt.value.value, str)
                ):
                    description = next_stmt.value.value.strip()

            fields.append(
                FieldDefinition(
                    name=field_name,
                    type_annotation=type_annotation,
                    default_value=default_value,
                    is_required=is_required,
                    description=description,
                    constraints=constraints,
                    line_number=stmt.lineno,
                )
            )

        return fields

    def _parse_field_call(self, call_node: ast.Call) -> dict[str, Any]:
        """Extract metadata, defaults, descriptions, and constraints from Field(...)."""
        is_required = True
        default_value: Optional[str] = None
        description: Optional[str] = None
        constraints: dict[str, Any] = {}

        # Known constraint kwargs in Pydantic v1 & v2
        constraint_keys = {
            "gt",
            "ge",
            "lt",
            "le",
            "min_length",
            "max_length",
            "regex",
            "pattern",
            "multiple_of",
            "max_digits",
            "decimal_places",
        }

        # Check positional arg 0 (default value or ...)
        if call_node.args:
            arg0 = call_node.args[0]
            arg0_str = ast.unparse(arg0)
            if (
                isinstance(arg0, ast.Constant) and arg0.value is ...
            ) or arg0_str == "...":
                is_required = True
                default_value = None
            else:
                is_required = False
                default_value = arg0_str

        # Check keyword arguments
        for kw in call_node.keywords:
            if not kw.arg:
                continue

            kw_val_str = ast.unparse(kw.value)

            if kw.arg == "default":
                if (
                    isinstance(kw.value, ast.Constant) and kw.value.value is ...
                ) or kw_val_str == "...":
                    is_required = True
                    default_value = None
                else:
                    is_required = False
                    default_value = kw_val_str
            elif kw.arg == "default_factory":
                is_required = False
                default_value = f"<factory: {kw_val_str}>"
            elif kw.arg == "description":
                if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    description = kw.value.value
                else:
                    description = kw_val_str
            elif kw.arg in constraint_keys:
                if isinstance(kw.value, ast.Constant):
                    constraints[kw.arg] = kw.value.value
                else:
                    constraints[kw.arg] = kw_val_str

        return {
            "is_required": is_required,
            "default_value": default_value,
            "description": description,
            "constraints": constraints,
        }

    # -------------------------------------------------------------------------
    # Utilities
    # -------------------------------------------------------------------------

    def _extract_literal_list(self, node: ast.expr) -> list[str]:
        """Extract a list of string values from a list or tuple AST node."""
        items: list[str] = []
        if isinstance(node, (ast.List, ast.Tuple)):
            for elt in node.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    items.append(elt.value)
                else:
                    items.append(ast.unparse(elt).strip("'\""))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            items.append(node.value)
        return items


def parse_code(source_code: str, filename: str = "<string>") -> ContractSnapshot:
    """Parse Python source code and return a deterministic ContractSnapshot."""
    tree = ast.parse(source_code, filename=filename)
    visitor = ASTContractParser(filename=filename)
    visitor.visit(tree)

    return ContractSnapshot(
        file_path=filename,
        routes=visitor.routes,
        schemas=visitor.schemas,
        imports=visitor.imports,
    )


def parse_file(file_path: Union[str, Path]) -> ContractSnapshot:
    """Read and parse a Python file, returning a deterministic ContractSnapshot."""
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")

    source_code = path.read_text(encoding="utf-8")
    return parse_code(source_code, filename=str(path))
