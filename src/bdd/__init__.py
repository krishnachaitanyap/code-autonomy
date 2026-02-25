"""
JISI BDD Testing module.

Provides structured service specification loading, enterprise BDD prompt
construction, and output parsing/validation for Cucumber test generation.
"""

from src.bdd.service_spec import ServiceSpec, Operation, FieldDefinition
from src.bdd.prompt_builder import build_jisi_bdd_prompt
from src.bdd.output_parser import BDDOutputBundle, parse_bdd_output, validate_bdd_files

try:
    from src.bdd.servlet_discovery import discover_service_specs
except ImportError:
    discover_service_specs = None  # type: ignore[assignment]

__all__ = [
    "ServiceSpec",
    "Operation",
    "FieldDefinition",
    "build_jisi_bdd_prompt",
    "BDDOutputBundle",
    "parse_bdd_output",
    "validate_bdd_files",
    "discover_service_specs",
]
