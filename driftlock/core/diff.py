"""Contract diff engine: deterministic comparison of two ContractSnapshots.

Detects schema field additions/removals/type changes and route additions/removals/
signature changes, classifying each as breaking or non-breaking.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from driftlock.core.models import ContractSnapshot, FieldDefinition, RouteDefinition


@dataclass
class ContractDrift:
    """A single detected contract drift between base and head snapshots."""

    category: str  # e.g. FIELD_ADDED, FIELD_REMOVED, FIELD_TYPE_CHANGED, ROUTE_ADDED, ...
    identifier: str  # e.g. "UserCreate.tier" or "POST /v1/users"
    details: str  # Human-readable description of the change
    is_breaking: bool  # True if this change can break consumers


@dataclass
class DriftReport:
    """Aggregated report of all detected contract drifts."""

    drifts: list[ContractDrift] = field(default_factory=list)

    @property
    def has_drift(self) -> bool:
        """True if any drifts were detected."""
        return len(self.drifts) > 0

    @property
    def has_breaking_drift(self) -> bool:
        """True if any breaking drifts were detected."""
        return any(d.is_breaking for d in self.drifts)

    @property
    def breaking_drifts(self) -> list[ContractDrift]:
        """Return only breaking drifts."""
        return [d for d in self.drifts if d.is_breaking]

    @property
    def non_breaking_drifts(self) -> list[ContractDrift]:
        """Return only non-breaking drifts."""
        return [d for d in self.drifts if not d.is_breaking]


def compute_contract_diff(
    base_contract: ContractSnapshot,
    head_contract: ContractSnapshot,
) -> DriftReport:
    """Deterministically compare two ContractSnapshots and return a DriftReport.

    Detects:
    - FIELD_ADDED: New field on a schema (breaking if required and no default).
    - FIELD_REMOVED: Field removed from a schema (always breaking).
    - FIELD_TYPE_CHANGED: Field type annotation changed (always breaking).
    - FIELD_DEFAULT_CHANGED: Field default value changed (non-breaking).
    - FIELD_REQUIRED_CHANGED: Field required status changed (breaking if now required).
    - ROUTE_ADDED: New route endpoint (non-breaking).
    - ROUTE_REMOVED: Route endpoint removed (always breaking).
    - ROUTE_RETURN_TYPE_CHANGED: Route return type changed (breaking).
    - ROUTE_METHOD_CHANGED: Route HTTP method changed (breaking).
    - ROUTE_PARAM_ADDED: New required parameter on a route (breaking if required).
    - ROUTE_PARAM_REMOVED: Parameter removed from a route (breaking).
    - ROUTE_PARAM_TYPE_CHANGED: Parameter type changed (breaking).
    """
    drifts: list[ContractDrift] = []

    # --- Schema Diffs ---
    _diff_schemas(base_contract, head_contract, drifts)

    # --- Route Diffs ---
    _diff_routes(base_contract, head_contract, drifts)

    return DriftReport(drifts=drifts)


def _diff_schemas(
    base: ContractSnapshot,
    head: ContractSnapshot,
    drifts: list[ContractDrift],
) -> None:
    """Compare schemas between base and head snapshots."""
    base_schema_map = {s.name: s for s in base.schemas}
    head_schema_map = {s.name: s for s in head.schemas}

    # Schemas added in head
    for name, schema in head_schema_map.items():
        if name not in base_schema_map:
            drifts.append(ContractDrift(
                category="SCHEMA_ADDED",
                identifier=name,
                details=f"Schema '{name}' added with {len(schema.fields)} field(s)",
                is_breaking=False,
            ))

    # Schemas removed in head
    for name in base_schema_map:
        if name not in head_schema_map:
            drifts.append(ContractDrift(
                category="SCHEMA_REMOVED",
                identifier=name,
                details=f"Schema '{name}' removed",
                is_breaking=True,
            ))

    # Schemas present in both -- diff fields
    for name in sorted(set(base_schema_map) & set(head_schema_map)):
        base_schema = base_schema_map[name]
        head_schema = head_schema_map[name]
        _diff_fields(name, base_schema.fields, head_schema.fields, drifts)


def _diff_fields(
    schema_name: str,
    base_fields: list[FieldDefinition],
    head_fields: list[FieldDefinition],
    drifts: list[ContractDrift],
) -> None:
    """Compare fields within a single schema."""
    base_field_map = {f.name: f for f in base_fields}
    head_field_map = {f.name: f for f in head_fields}

    # Fields added in head
    for fname, hfield in head_field_map.items():
        if fname not in base_field_map:
            is_breaking = hfield.is_required and hfield.default_value is None
            drifts.append(ContractDrift(
                category="FIELD_ADDED",
                identifier=f"{schema_name}.{fname}",
                details=(
                    f"Field '{fname}' added to '{schema_name}' "
                    f"(type={hfield.type_annotation}, required={hfield.is_required}, "
                    f"default={hfield.default_value})"
                ),
                is_breaking=is_breaking,
            ))

    # Fields removed in head
    for fname in base_field_map:
        if fname not in head_field_map:
            drifts.append(ContractDrift(
                category="FIELD_REMOVED",
                identifier=f"{schema_name}.{fname}",
                details=f"Field '{fname}' removed from '{schema_name}'",
                is_breaking=True,
            ))

    # Fields present in both -- check for type / default / required changes
    for fname in sorted(set(base_field_map) & set(head_field_map)):
        bfield = base_field_map[fname]
        hfield = head_field_map[fname]

        if bfield.type_annotation != hfield.type_annotation:
            drifts.append(ContractDrift(
                category="FIELD_TYPE_CHANGED",
                identifier=f"{schema_name}.{fname}",
                details=(
                    f"Field '{fname}' type changed from "
                    f"'{bfield.type_annotation}' to '{hfield.type_annotation}'"
                ),
                is_breaking=True,
            ))

        if bfield.default_value != hfield.default_value:
            drifts.append(ContractDrift(
                category="FIELD_DEFAULT_CHANGED",
                identifier=f"{schema_name}.{fname}",
                details=(
                    f"Field '{fname}' default changed from "
                    f"'{bfield.default_value}' to '{hfield.default_value}'"
                ),
                is_breaking=False,
            ))

        if bfield.is_required != hfield.is_required:
            # Breaking if field became required (was optional, now mandatory)
            is_breaking = hfield.is_required and not bfield.is_required
            drifts.append(ContractDrift(
                category="FIELD_REQUIRED_CHANGED",
                identifier=f"{schema_name}.{fname}",
                details=(
                    f"Field '{fname}' required status changed from "
                    f"{bfield.is_required} to {hfield.is_required}"
                ),
                is_breaking=is_breaking,
            ))


def _diff_routes(
    base: ContractSnapshot,
    head: ContractSnapshot,
    drifts: list[ContractDrift],
) -> None:
    """Compare routes between base and head snapshots."""
    base_route_map = {r.endpoint_id: r for r in base.routes}
    head_route_map = {r.endpoint_id: r for r in head.routes}

    # Routes added in head
    for eid, route in head_route_map.items():
        if eid not in base_route_map:
            drifts.append(ContractDrift(
                category="ROUTE_ADDED",
                identifier=eid,
                details=f"Route '{eid}' added (function={route.function_name})",
                is_breaking=False,
            ))

    # Routes removed in head
    for eid in base_route_map:
        if eid not in head_route_map:
            drifts.append(ContractDrift(
                category="ROUTE_REMOVED",
                identifier=eid,
                details=f"Route '{eid}' removed",
                is_breaking=True,
            ))

    # Routes present in both -- diff signatures
    for eid in sorted(set(base_route_map) & set(head_route_map)):
        broute = base_route_map[eid]
        hroute = head_route_map[eid]

        # Return type changes
        if broute.return_type != hroute.return_type:
            drifts.append(ContractDrift(
                category="ROUTE_RETURN_TYPE_CHANGED",
                identifier=eid,
                details=(
                    f"Route '{eid}' return type changed from "
                    f"'{broute.return_type}' to '{hroute.return_type}'"
                ),
                is_breaking=True,
            ))

        # Response model changes
        if broute.response_model != hroute.response_model:
            drifts.append(ContractDrift(
                category="ROUTE_RESPONSE_MODEL_CHANGED",
                identifier=eid,
                details=(
                    f"Route '{eid}' response model changed from "
                    f"'{broute.response_model}' to '{hroute.response_model}'"
                ),
                is_breaking=True,
            ))

        # Status code changes
        if broute.status_code != hroute.status_code:
            drifts.append(ContractDrift(
                category="ROUTE_STATUS_CODE_CHANGED",
                identifier=eid,
                details=(
                    f"Route '{eid}' status code changed from "
                    f"'{broute.status_code}' to '{hroute.status_code}'"
                ),
                is_breaking=True,
            ))

        # Parameter diffs
        _diff_route_params(eid, broute, hroute, drifts)


def _diff_route_params(
    endpoint_id: str,
    base_route: RouteDefinition,
    head_route: RouteDefinition,
    drifts: list[ContractDrift],
) -> None:
    """Compare parameters between two versions of the same route."""
    base_param_map = {p.name: p for p in base_route.parameters}
    head_param_map = {p.name: p for p in head_route.parameters}

    for pname, hparam in head_param_map.items():
        if pname not in base_param_map:
            is_breaking = hparam.is_required
            drifts.append(ContractDrift(
                category="ROUTE_PARAM_ADDED",
                identifier=f"{endpoint_id} param:{pname}",
                details=(
                    f"Parameter '{pname}' added to route '{endpoint_id}' "
                    f"(type={hparam.type_annotation}, required={hparam.is_required})"
                ),
                is_breaking=is_breaking,
            ))

    for pname in base_param_map:
        if pname not in head_param_map:
            drifts.append(ContractDrift(
                category="ROUTE_PARAM_REMOVED",
                identifier=f"{endpoint_id} param:{pname}",
                details=f"Parameter '{pname}' removed from route '{endpoint_id}'",
                is_breaking=True,
            ))

    for pname in sorted(set(base_param_map) & set(head_param_map)):
        bparam = base_param_map[pname]
        hparam = head_param_map[pname]

        if bparam.type_annotation != hparam.type_annotation:
            drifts.append(ContractDrift(
                category="ROUTE_PARAM_TYPE_CHANGED",
                identifier=f"{endpoint_id} param:{pname}",
                details=(
                    f"Parameter '{pname}' type changed from "
                    f"'{bparam.type_annotation}' to '{hparam.type_annotation}'"
                ),
                is_breaking=True,
            ))
