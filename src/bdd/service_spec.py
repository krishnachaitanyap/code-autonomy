"""
Service specification data model for JISI BDD test generation.

Defines the structured input for enterprise Cucumber test generation:
service name, endpoint, operations with request/response fields.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


def _class_to_path(class_name: str) -> str:
    """Convert a fully qualified Java class name to a source file path.

    Example: "com.enterprise.services.FooInvoker" → "src/main/java/com/enterprise/services/FooInvoker.java"
    """
    return "src/main/java/" + class_name.replace(".", "/") + ".java"


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
    account_types: list[str] = field(default_factory=lambda: ["CHK", "SAV"])
    response_fields_map: dict[str, str] = field(default_factory=dict)
    request_payload_fields: list[tuple[str, str]] = field(default_factory=list)
    test_types: list[str] = field(default_factory=list)
    invoker_class: str = ""
    handler_class: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "Operation":
        payload_fields = [
            (item[0], item[1]) for item in data.get("request_payload_fields", [])
        ]
        return cls(
            name=data["name"],
            path=data.get("path", ""),
            method=data.get("method", "POST").upper(),
            request_fields=[FieldDefinition.from_dict(f) for f in data.get("request_fields", [])],
            response_fields=[FieldDefinition.from_dict(f) for f in data.get("response_fields", [])],
            account_types=data.get("account_types", ["CHK", "SAV"]),
            response_fields_map=data.get("response_fields_map", {}),
            request_payload_fields=payload_fields,
            test_types=data.get("test_types", []),
            invoker_class=data.get("invoker_class", ""),
            handler_class=data.get("handler_class", ""),
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
    package_name: str = "com.enterprise.test.services"
    feature_name: str = ""
    response_type_name: str = ""
    domain: str = "profilecore"
    channel_types: list[str] = field(default_factory=lambda: ["C30"])
    user_types: list[str] = field(default_factory=lambda: ["PR"])
    invoker_class: str = ""
    handler_class: str = ""

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
            package_name=data.get("package_name", "com.enterprise.test.services"),
            feature_name=data.get("feature_name", ""),
            response_type_name=data.get("response_type_name", ""),
            domain=data.get("domain", "profilecore"),
            channel_types=data.get("channel_types", ["C30"]),
            user_types=data.get("user_types", ["PR"]),
            invoker_class=data.get("invoker_class", ""),
            handler_class=data.get("handler_class", ""),
        )

    @classmethod
    def from_file(cls, path: str) -> "ServiceSpec":
        """Load a ServiceSpec from a JSON file."""
        file_path = Path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"BDD spec file not found: {path}")
        data = json.loads(file_path.read_text(encoding="utf-8"))
        return cls.from_dict(data)

    _VALID_TEST_TYPES = frozenset({
        "regression", "compare", "pvt", "heartbeat", "end_to_end",
    })

    def validate(self) -> list[str]:
        """Return a list of validation errors (empty if valid)."""
        errors: list[str] = []
        if not self.service_name:
            errors.append("service_name is required")
        if not self.endpoint:
            errors.append("endpoint is required")
        if not self.operations:
            errors.append("at least one operation is required")
        if not self.package_name:
            errors.append("package_name is required")
        if not self.domain:
            errors.append("domain is required")
        if not self.channel_types:
            errors.append("at least one channel_type is required")
        if not self.user_types:
            errors.append("at least one user_type is required")
        for op in self.operations:
            if not op.name:
                errors.append("operation name is required")
            if not op.method:
                errors.append(f"operation '{op.name}': method is required")
            if op.method not in ("GET", "POST", "PUT", "DELETE", "PATCH"):
                errors.append(f"operation '{op.name}': unsupported method '{op.method}'")
            for tt in op.test_types:
                if tt not in self._VALID_TEST_TYPES:
                    errors.append(f"operation '{op.name}': unsupported test_type '{tt}'")
        for tt in self.test_types:
            if tt not in self._VALID_TEST_TYPES:
                errors.append(f"unsupported test_type: '{tt}'")
        return errors
