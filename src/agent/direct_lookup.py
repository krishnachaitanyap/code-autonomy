"""
Direct file-lookup fast path — zero-LLM answers for simple questions.

For questions like "what is the project name from pom.xml", this module
parses the file directly and returns the answer without any LLM calls.
Gracefully returns None on any failure, allowing fallthrough to the LLM path.
"""

import configparser
import json
import re
import sys
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree


# ---------------------------------------------------------------------------
# 1. Extract target file from question
# ---------------------------------------------------------------------------

# Common config/build file names mentioned in questions
_FILE_REFS_RE = re.compile(
    r"\b(pom\.xml|build\.gradle(?:\.kts)?|package\.json|"
    r"application\.(?:yml|yaml|properties)|"
    r"bootstrap\.(?:yml|yaml|properties)|"
    r"env\.properties|settings\.gradle(?:\.kts)?|"
    r"Dockerfile|docker-compose\.ya?ml|"
    r"tsconfig\.json|\.env|Makefile|Cargo\.toml|go\.mod|"
    r"requirements\.txt|pyproject\.toml|setup\.py|setup\.cfg)\b",
    re.IGNORECASE,
)

# Generic file extension pattern (e.g., "from foo.properties", "in bar.xml")
_FILE_EXT_RE = re.compile(
    r"(?:from|in|of|file)\s+[\"']?([\w./-]+\.(?:xml|json|ya?ml|properties|toml|ini|cfg|env|conf))[\"']?",
    re.IGNORECASE,
)


def extract_target_file(
    question: str,
    repo_path: str,
    consciousness: "ProjectConsciousness | None" = None,
) -> Optional[str]:
    """Extract the target file path from the question.

    Returns the resolved absolute path if found, else None.
    """
    repo = Path(repo_path)

    # Try well-known file names first
    m = _FILE_REFS_RE.search(question)
    filename = m.group(1) if m else None

    # Try generic file extension pattern
    if not filename:
        m2 = _FILE_EXT_RE.search(question)
        filename = m2.group(1) if m2 else None

    if not filename:
        return None

    # Direct check at repo root
    candidate = repo / filename
    if candidate.is_file():
        return str(candidate)

    # Search in consciousness structure for full path
    if consciousness and hasattr(consciousness, "structure"):
        for entry in consciousness.structure:
            entry_path = entry if isinstance(entry, str) else entry.get("path", "")
            if entry_path.endswith(filename) or entry_path.endswith("/" + filename):
                full = repo / entry_path
                if full.is_file():
                    return str(full)

    # Fallback: walk common subdirs
    for subdir in ("src/main/resources", "src", "config", "conf", "."):
        candidate = repo / subdir / filename
        if candidate.is_file():
            return str(candidate)

    # Last resort: recursive search (limited depth)
    try:
        for f in repo.rglob(filename):
            if f.is_file():
                return str(f)
    except Exception:
        pass

    return None


# ---------------------------------------------------------------------------
# 2. Extract target key from question
# ---------------------------------------------------------------------------

# "value of X", "what is X", dotted identifiers, XML element names
_KEY_PATTERNS = [
    # "what is the project name" → "project name"
    re.compile(r"(?:value\s+of|what\s+is(?:\s+the)?)\s+[\"']?([\w.:/ -]+?)(?:\s+(?:from|in|of)\b|[\"']|\?|$)", re.IGNORECASE),
    re.compile(r"\b([\w]+(?:\.[\w]+){1,})\b"),  # dotted identifier: project.name, spring.datasource.url
    re.compile(r"<([\w:.-]+)>", re.IGNORECASE),  # XML element: <artifactId>
    re.compile(r"\b((?:project|artifact|group)\s*(?:name|id|version))\b", re.IGNORECASE),
]

_NOISE_WORDS = {"the", "is", "what", "from", "in", "of", "a", "an"}


def extract_target_key(question: str) -> Optional[str]:
    """Extract the target key/property name from the question."""
    for pattern in _KEY_PATTERNS:
        m = pattern.search(question)
        if m:
            key = m.group(1).strip()
            # Filter out noise
            if len(key) > 1 and key.lower() not in _NOISE_WORDS:
                return key
    return None


# ---------------------------------------------------------------------------
# 3. Parse structured files
# ---------------------------------------------------------------------------

def _flatten_dict(d: dict, prefix: str = "") -> dict[str, str]:
    """Flatten a nested dict with dot-separated keys."""
    items: dict[str, str] = {}
    for k, v in d.items():
        full_key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            items.update(_flatten_dict(v, full_key))
        elif isinstance(v, list):
            items[full_key] = json.dumps(v)
        else:
            items[full_key] = str(v)
    return items


def _parse_xml_to_dict(root: ElementTree.Element, prefix: str = "") -> dict[str, str]:
    """Recursively flatten XML element tree to dot-separated keys."""
    items: dict[str, str] = {}
    # Strip namespace
    tag = re.sub(r"\{[^}]+\}", "", root.tag)
    full_key = f"{prefix}.{tag}" if prefix else tag

    if root.text and root.text.strip():
        items[full_key] = root.text.strip()

    for child in root:
        items.update(_parse_xml_to_dict(child, full_key))

    return items


def parse_structured_file(file_path: str, file_type: Optional[str] = None) -> dict[str, str]:
    """Parse a structured file and return a flat dict of key→value.

    Supports: XML, JSON, YAML, .properties, .env, .ini/.cfg, .toml
    Returns empty dict on any parse failure.
    """
    path = Path(file_path)
    if not path.is_file():
        return {}

    if file_type is None:
        suffix = path.suffix.lower()
        name_lower = path.name.lower()
        if suffix == ".xml":
            file_type = "xml"
        elif suffix == ".json":
            file_type = "json"
        elif suffix in (".yml", ".yaml"):
            file_type = "yaml"
        elif suffix == ".properties" or name_lower.endswith(".properties"):
            file_type = "properties"
        elif suffix == ".env" or name_lower.startswith(".env"):
            file_type = "env"
        elif suffix in (".ini", ".cfg"):
            file_type = "ini"
        elif suffix == ".toml":
            file_type = "toml"
        else:
            return {}

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return {}

    try:
        if file_type == "xml":
            tree = ElementTree.fromstring(content)
            return _parse_xml_to_dict(tree)

        elif file_type == "json":
            data = json.loads(content)
            if isinstance(data, dict):
                return _flatten_dict(data)
            return {}

        elif file_type == "yaml":
            try:
                import yaml
                data = yaml.safe_load(content)
            except ImportError:
                return {}
            if isinstance(data, dict):
                return _flatten_dict(data)
            return {}

        elif file_type in ("properties", "env"):
            result: dict[str, str] = {}
            for line in content.splitlines():
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("!"):
                    continue
                # Split on first = or :
                for sep in ("=", ":"):
                    if sep in line:
                        k, v = line.split(sep, 1)
                        result[k.strip()] = v.strip()
                        break
            return result

        elif file_type == "ini":
            parser = configparser.ConfigParser()
            parser.read_string(content)
            result = {}
            for section in parser.sections():
                for k, v in parser.items(section):
                    result[f"{section}.{k}"] = v
            return result

        elif file_type == "toml":
            if sys.version_info >= (3, 11):
                import tomllib
                data = tomllib.loads(content)
            else:
                try:
                    import tomli as tomllib  # type: ignore[no-redef]
                    data = tomllib.loads(content)
                except ImportError:
                    return {}
            if isinstance(data, dict):
                return _flatten_dict(data)
            return {}

    except Exception:
        return {}

    return {}


# ---------------------------------------------------------------------------
# 4. Orchestrator
# ---------------------------------------------------------------------------

def direct_lookup(
    question: str,
    repo_path: str,
    consciousness: "ProjectConsciousness | None" = None,
) -> Optional[str]:
    """Attempt to answer a lookup question by directly parsing the target file.

    Returns a formatted answer string, or None if the lookup fails
    (triggering fallthrough to the LLM path).
    """
    # Step 1: Find the target file
    file_path = extract_target_file(question, repo_path, consciousness)
    if not file_path:
        return None

    # Step 2: Parse the file
    parsed = parse_structured_file(file_path)
    if not parsed:
        return None

    # Step 3: Extract the target key
    target_key = extract_target_key(question)

    if target_key:
        # Normalize for matching
        key_lower = target_key.lower().replace(" ", "").replace("_", "")

        # Try exact match first
        for k, v in parsed.items():
            if k.lower() == target_key.lower():
                rel_path = str(Path(file_path).relative_to(repo_path)) if repo_path else file_path
                return f"From `{rel_path}`: **{k}** = `{v}`"

        # Try suffix match (e.g., "project name" matches "project.name")
        for k, v in parsed.items():
            k_normalized = k.lower().replace(".", "").replace("-", "").replace("_", "")
            if key_lower in k_normalized or k_normalized.endswith(key_lower):
                rel_path = str(Path(file_path).relative_to(repo_path)) if repo_path else file_path
                return f"From `{rel_path}`: **{k}** = `{v}`"

        # Try partial match on last segment
        for k, v in parsed.items():
            last_segment = k.rsplit(".", 1)[-1].lower()
            if target_key.lower().replace(" ", "") in last_segment:
                rel_path = str(Path(file_path).relative_to(repo_path)) if repo_path else file_path
                return f"From `{rel_path}`: **{k}** = `{v}`"

    # If no specific key found but file was parsed, return summary of key fields
    rel_path = str(Path(file_path).relative_to(repo_path)) if repo_path else file_path

    # For build files, return the most relevant fields
    important_keys = [
        k for k in parsed
        if any(term in k.lower() for term in [
            "name", "version", "group", "artifact", "description",
            "packaging", "java.version", "spring.application",
        ])
    ]

    if important_keys:
        lines = [f"From `{rel_path}`:"]
        for k in important_keys[:10]:
            lines.append(f"- **{k}** = `{parsed[k]}`")
        return "\n".join(lines)

    return None
