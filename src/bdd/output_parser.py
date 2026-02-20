"""
Output parsing and validation for JISI BDD test generation.

Parses marker-delimited output from the AI into structured artifacts
and validates that generated files match expectations.
"""

import re
from dataclasses import dataclass


@dataclass
class BDDOutputBundle:
    """Parsed output from JISI BDD test generation."""

    feature_file: str = ""
    service_class: str = ""
    property_entry: str = ""

    @property
    def is_complete(self) -> bool:
        """True if all three artifacts are present."""
        return bool(self.feature_file and self.service_class and self.property_entry)

    def missing_artifacts(self) -> list[str]:
        """Return names of missing artifacts."""
        missing = []
        if not self.feature_file:
            missing.append("feature_file")
        if not self.service_class:
            missing.append("service_class")
        if not self.property_entry:
            missing.append("property_entry")
        return missing


def _extract_between_markers(text: str, start: str, end: str) -> str:
    """Extract content between start and end markers."""
    pattern = re.escape(start) + r"\s*\n?(.*?)\n?\s*" + re.escape(end)
    m = re.search(pattern, text, re.DOTALL)
    return m.group(1).strip() if m else ""


def parse_bdd_output(text: str) -> BDDOutputBundle:
    """
    Parse marker-delimited BDD output into a structured bundle.

    Expected markers:
      ===FEATURE_FILE_START=== ... ===FEATURE_FILE_END===
      ===SERVICE_CLASS_START=== ... ===SERVICE_CLASS_END===
      ===PROPERTY_ENTRY_START=== ... ===PROPERTY_ENTRY_END===
    """
    return BDDOutputBundle(
        feature_file=_extract_between_markers(text, "===FEATURE_FILE_START===", "===FEATURE_FILE_END==="),
        service_class=_extract_between_markers(text, "===SERVICE_CLASS_START===", "===SERVICE_CLASS_END==="),
        property_entry=_extract_between_markers(text, "===PROPERTY_ENTRY_START===", "===PROPERTY_ENTRY_END==="),
    )


def validate_bdd_files(files_changed: list[str], service_name: str) -> list[str]:
    """
    Advisory validation: check that expected BDD files were created.

    Returns a list of warning strings (empty if all expected files found).
    """
    warnings: list[str] = []

    # Check for feature file
    feature_pattern = f"{service_name}.feature"
    if not any(feature_pattern in f for f in files_changed):
        warnings.append(f"Expected feature file '{feature_pattern}' not found in changed files")

    # Check for service class
    class_pattern = f"{service_name}.java"
    if not any(class_pattern in f for f in files_changed):
        warnings.append(f"Expected service class '{class_pattern}' not found in changed files")

    return warnings
