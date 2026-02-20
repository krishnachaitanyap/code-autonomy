"""
Service specification data model for JISI BDD test generation.

Defines the structured input for enterprise Cucumber test generation:
service name, endpoint, operations with request/response fields.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class FieldDefinition:
    """A single request or response field."""

    name: str
    type: str  # "String", "Integer", "Boolean", "BigDecimal", etc.
    required: bool = False
    description: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "FieldDefinition":
        return cls(
            name=data["name"],
            type=data.get("type", "String"),
            required=data.get("required", False),
            description=data.get("description", ""),
        )


@dataclass
class Operation:
    """A single REST operation (endpoint method)."""

    name: str        # e.g. "getAccountDetails"
    path: str        # e.g. "/profilecore/services/AccountLookup/getAccountDetails"
    method: str      # GET, POST, PUT, DELETE
    request_fields: list[FieldDefinition] = field(default_factory=list)
    response_fields: list[FieldDefinition] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "Operation":
        return cls(
            name=data["name"],
            path=data.get("path", ""),
            method=data.get("method", "POST").upper(),
            request_fields=[FieldDefinition.from_dict(f) for f in data.get("request_fields", [])],
            response_fields=[FieldDefinition.from_dict(f) for f in data.get("response_fields", [])],
        )


@dataclass
class ServiceSpec:
    """Full service specification for JISI BDD test generation."""

    service_name: str        # e.g. "AccountLookupRESTSvc"
    endpoint: str            # e.g. "/profilecore/services/AccountLookup"
    team: str                # e.g. "GWS-ProfileCore"
    operations: list[Operation] = field(default_factory=list)
    test_types: list[str] = field(default_factory=lambda: ["regression"])
    application_tag: str = "GWS"
    base_class: str = "ServiceBase"

    @classmethod
    def from_dict(cls, data: dict) -> "ServiceSpec":
        """Create a ServiceSpec from a dictionary (e.g. parsed JSON)."""
        return cls(
            service_name=data["service_name"],
            endpoint=data["endpoint"],
            team=data.get("team", ""),
            operations=[Operation.from_dict(op) for op in data.get("operations", [])],
            test_types=data.get("test_types", ["regression"]),
            application_tag=data.get("application_tag", "GWS"),
            base_class=data.get("base_class", "ServiceBase"),
        )

    @classmethod
    def from_file(cls, path: str) -> "ServiceSpec":
        """Load a ServiceSpec from a JSON file."""
        file_path = Path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"BDD spec file not found: {path}")
        data = json.loads(file_path.read_text(encoding="utf-8"))
        return cls.from_dict(data)

    def validate(self) -> list[str]:
        """Return a list of validation errors (empty if valid)."""
        errors: list[str] = []
        if not self.service_name:
            errors.append("service_name is required")
        if not self.endpoint:
            errors.append("endpoint is required")
        if not self.operations:
            errors.append("at least one operation is required")
        for op in self.operations:
            if not op.name:
                errors.append("operation name is required")
            if not op.method:
                errors.append(f"operation '{op.name}': method is required")
            if op.method not in ("GET", "POST", "PUT", "DELETE", "PATCH"):
                errors.append(f"operation '{op.name}': unsupported method '{op.method}'")
        for tt in self.test_types:
            if tt not in ("regression", "compare", "pvt", "heartbeat"):
                errors.append(f"unsupported test_type: '{tt}'")
        return errors
