"""
Enterprise Framework Detector — detects internal/enterprise frameworks in a project.

This is a pluggable detection module used by the migration analysis pipeline.
It extends the static stack_analyzer framework detection with deeper heuristics:
  - Parent POM / BOM analysis
  - Custom annotation scanning
  - Proprietary XML config detection
  - Internal library fingerprinting
  - Build plugin detection

Results are merged into the migration project's source_profile and gap_analysis.
"""

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from src.constants import SKIP_DIRS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Detection result
# ---------------------------------------------------------------------------

@dataclass
class EnterpriseFrameworkResult:
    """Result of enterprise framework detection for a single project."""
    frameworks_detected: list[dict] = field(default_factory=list)
    # Each: {"name", "version", "confidence", "evidence": [...], "category"}

    annotations_found: list[dict] = field(default_factory=list)
    # Each: {"annotation", "file", "line", "framework"}

    proprietary_configs: list[dict] = field(default_factory=list)
    # Each: {"file", "type", "framework", "keys": [...]}

    internal_libraries: list[dict] = field(default_factory=list)
    # Each: {"group", "artifact", "version", "framework"}

    build_plugins: list[dict] = field(default_factory=list)
    # Each: {"plugin", "framework", "config_keys": [...]}

    migration_impact: dict = field(default_factory=dict)
    # {"complexity": "high|medium|low", "blockers": [...], "recommendations": [...]}


# ---------------------------------------------------------------------------
# Detection rules — extend this for your organization
# ---------------------------------------------------------------------------

ENTERPRISE_FRAMEWORK_RULES: list[dict] = [
    {
        "name": "Nucleus",
        "category": "internal",
        "detect_by": {
            "parent_pom_keywords": ["nucleus"],
            "dependency_groups": ["com.enterprise.nucleus", "nucleus"],
            "annotations": [
                r"@NucleusService", r"@NucleusConfig", r"@NucleusBean",
                r"@NucleusEndpoint", r"@NucleusFilter",
            ],
            "config_files": [
                "nucleus-config.xml", "nucleus-context.xml",
                "nucleus-servlet.xml", "nucleus.properties",
            ],
            "build_plugins": ["nucleus-maven-plugin"],
        },
        "migration_notes": {
            "target": "Spring Boot (Photon)",
            "complexity": "high",
            "key_changes": [
                "XML bean definitions → @Component/@Service annotations",
                "Nucleus servlet config → Spring Boot auto-configuration",
                "WAR packaging → executable JAR",
                "Custom annotations → Spring Boot equivalents",
                "JNDI lookups → Spring Boot externalized config",
            ],
        },
    },
    {
        "name": "JISI (WAS GWS)",
        "category": "internal",
        "detect_by": {
            "parent_pom_keywords": ["jisi", "wasgws", "was-gws"],
            "dependency_groups": ["com.enterprise.jisi", "wasgwsframework", "jisi"],
            "annotations": [
                r"@JisiService", r"@GWSEndpoint", r"@WASConfig",
            ],
            "config_files": [
                "jisi-config.xml", "gws-servlet.xml",
                "was-config.xml", "jisi.properties",
            ],
            "build_plugins": ["jisi-maven-plugin", "gws-maven-plugin"],
        },
        "migration_notes": {
            "target": "Spring Boot (Photon)",
            "complexity": "high",
            "key_changes": [
                "CXF/JAX-RS endpoints → @RestController",
                "WAS JNDI → Spring Boot config properties",
                "Servlet XML → Spring Boot auto-configuration",
                "EAR packaging → JAR + Docker",
                "WAS-specific logging → Spring Boot Actuator",
            ],
        },
    },
    {
        "name": "Photon",
        "category": "internal",
        "detect_by": {
            "parent_pom_keywords": ["photon"],
            "dependency_groups": ["com.enterprise.photon", "photon"],
            "annotations": [
                r"@PhotonApplication", r"@PhotonService",
            ],
            "config_files": ["photon.yml", "photon-config.yml"],
            "build_plugins": ["photon-maven-plugin"],
        },
        "migration_notes": {
            "target": "Already on Photon",
            "complexity": "low",
            "key_changes": ["May need version upgrade only"],
        },
    },
    {
        "name": "Spring Boot",
        "category": "open-source",
        "detect_by": {
            "parent_pom_keywords": ["spring-boot"],
            "dependency_groups": ["org.springframework.boot"],
            "annotations": [
                r"@SpringBootApplication", r"@EnableAutoConfiguration",
            ],
            "config_files": ["application.yml", "application.properties", "application.yaml"],
            "build_plugins": ["spring-boot-maven-plugin"],
        },
        "migration_notes": {
            "target": "N/A",
            "complexity": "low",
            "key_changes": ["Already using Spring Boot"],
        },
    },
    {
        "name": "Jakarta EE / Java EE",
        "category": "standard",
        "detect_by": {
            "parent_pom_keywords": [],
            "dependency_groups": ["jakarta.", "javax."],
            "annotations": [
                r"@ManagedBean", r"@Stateless", r"@Stateful",
                r"@Entity", r"@WebServlet", r"@EJB",
            ],
            "config_files": [
                "web.xml", "ejb-jar.xml", "persistence.xml",
                "beans.xml", "faces-config.xml",
            ],
            "build_plugins": [],
        },
        "migration_notes": {
            "target": "Spring Boot (Photon)",
            "complexity": "medium",
            "key_changes": [
                "EJB → Spring @Service/@Component",
                "JPA config via persistence.xml → Spring Boot auto-config",
                "web.xml → Spring Boot embedded server",
                "CDI @Inject → Spring @Autowired",
            ],
        },
    },
]


# ---------------------------------------------------------------------------
# Core detection logic
# ---------------------------------------------------------------------------

def detect_enterprise_frameworks(
    repo_path: str | Path,
    extra_rules: list[dict] | None = None,
) -> EnterpriseFrameworkResult:
    """Scan a repository for enterprise framework usage.

    Args:
        repo_path: Path to the repository root
        extra_rules: Additional detection rules (same format as ENTERPRISE_FRAMEWORK_RULES)

    Returns:
        EnterpriseFrameworkResult with all detected frameworks, evidence, and migration impact
    """
    repo = Path(repo_path)
    result = EnterpriseFrameworkResult()

    rules = list(ENTERPRISE_FRAMEWORK_RULES)
    if extra_rules:
        rules.extend(extra_rules)

    # 1. Parse POM for parent/dependencies/plugins
    pom_data = _parse_pom(repo)

    # 2. Scan for annotation patterns across source files
    annotation_hits = _scan_annotations(repo, rules)

    # 3. Scan for proprietary config files
    config_hits = _scan_config_files(repo, rules)

    # 4. Evaluate each rule
    for rule in rules:
        evidence = []
        confidence = 0
        version = ""
        detect = rule["detect_by"]

        # Parent POM match
        if pom_data.get("parent"):
            parent_art = (pom_data["parent"].get("artifact") or "").lower()
            parent_grp = (pom_data["parent"].get("group") or "").lower()
            for kw in detect.get("parent_pom_keywords", []):
                if kw in parent_art or kw in parent_grp:
                    evidence.append(f"Parent POM matches '{kw}': {parent_grp}:{parent_art}")
                    confidence += 40
                    version = pom_data["parent"].get("version", "")
                    break

        # Dependency group match
        for dep in pom_data.get("dependencies", []):
            grp = (dep.get("group") or "").lower()
            for dep_kw in detect.get("dependency_groups", []):
                if dep_kw.lower() in grp:
                    evidence.append(f"Dependency: {grp}:{dep.get('artifact', '')}:{dep.get('version', '')}")
                    confidence += 20
                    if not version:
                        version = dep.get("version", "")

        # Annotation match
        for hit in annotation_hits.get(rule["name"], []):
            evidence.append(f"Annotation {hit['annotation']} in {hit['file']}:{hit['line']}")
            confidence += 15
            result.annotations_found.append({**hit, "framework": rule["name"]})

        # Config file match
        for hit in config_hits.get(rule["name"], []):
            evidence.append(f"Config file: {hit['file']}")
            confidence += 15
            result.proprietary_configs.append({**hit, "framework": rule["name"]})

        # Build plugin match
        for plugin in pom_data.get("plugins", []):
            plugin_art = (plugin.get("artifact") or "").lower()
            for plugin_kw in detect.get("build_plugins", []):
                if plugin_kw.lower() in plugin_art:
                    evidence.append(f"Build plugin: {plugin_art}")
                    confidence += 20
                    result.build_plugins.append({
                        "plugin": plugin_art,
                        "framework": rule["name"],
                        "config_keys": [],
                    })

        # Internal library tracking
        for dep in pom_data.get("dependencies", []):
            grp = (dep.get("group") or "").lower()
            for dep_kw in detect.get("dependency_groups", []):
                if dep_kw.lower() in grp:
                    result.internal_libraries.append({
                        "group": dep.get("group", ""),
                        "artifact": dep.get("artifact", ""),
                        "version": dep.get("version", ""),
                        "framework": rule["name"],
                    })

        if confidence > 0:
            result.frameworks_detected.append({
                "name": rule["name"],
                "version": version,
                "confidence": min(confidence, 100),
                "category": rule.get("category", "unknown"),
                "evidence": evidence[:10],  # cap evidence list
            })

    # 5. Compute migration impact
    result.migration_impact = _compute_migration_impact(result, rules)

    return result


# ---------------------------------------------------------------------------
# POM parsing
# ---------------------------------------------------------------------------

def _parse_pom(repo: Path) -> dict:
    """Parse pom.xml for parent, dependencies, and plugins."""
    pom_file = repo / "pom.xml"
    if not pom_file.is_file():
        return {"parent": None, "dependencies": [], "plugins": []}

    try:
        tree = ET.parse(str(pom_file))
        root = tree.getroot()
        ns = ""
        if root.tag.startswith("{"):
            ns = root.tag.split("}")[0] + "}"
    except Exception:
        return {"parent": None, "dependencies": [], "plugins": []}

    # Parent
    parent = None
    parent_el = root.find(f"{ns}parent")
    if parent_el is not None:
        parent = {
            "group": (parent_el.findtext(f"{ns}groupId") or "").strip(),
            "artifact": (parent_el.findtext(f"{ns}artifactId") or "").strip(),
            "version": (parent_el.findtext(f"{ns}version") or "").strip(),
        }

    # Dependencies
    deps = []
    for dep_el in root.iter(f"{ns}dependency"):
        deps.append({
            "group": (dep_el.findtext(f"{ns}groupId") or "").strip(),
            "artifact": (dep_el.findtext(f"{ns}artifactId") or "").strip(),
            "version": (dep_el.findtext(f"{ns}version") or "").strip(),
        })

    # Plugins
    plugins = []
    for plugin_el in root.iter(f"{ns}plugin"):
        art = (plugin_el.findtext(f"{ns}artifactId") or "").strip()
        if art:
            plugins.append({
                "group": (plugin_el.findtext(f"{ns}groupId") or "").strip(),
                "artifact": art,
            })

    return {"parent": parent, "dependencies": deps, "plugins": plugins}


# ---------------------------------------------------------------------------
# Annotation scanning
# ---------------------------------------------------------------------------

def _scan_annotations(repo: Path, rules: list[dict]) -> dict[str, list[dict]]:
    """Scan Java/Kotlin source files for framework-specific annotations."""
    # Build combined pattern → rule name mapping
    pattern_map: list[tuple[re.Pattern, str]] = []
    for rule in rules:
        for ann_pattern in rule["detect_by"].get("annotations", []):
            try:
                pattern_map.append((re.compile(ann_pattern), rule["name"]))
            except re.error:
                pass

    if not pattern_map:
        return {}

    hits: dict[str, list[dict]] = {}

    for src_file in _iter_source_files(repo, {".java", ".kt", ".scala"}):
        try:
            lines = src_file.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue

        rel_path = str(src_file.relative_to(repo))
        for line_num, line in enumerate(lines, 1):
            for pattern, rule_name in pattern_map:
                if pattern.search(line):
                    hits.setdefault(rule_name, []).append({
                        "annotation": pattern.pattern,
                        "file": rel_path,
                        "line": line_num,
                    })

    return hits


# ---------------------------------------------------------------------------
# Config file scanning
# ---------------------------------------------------------------------------

def _scan_config_files(repo: Path, rules: list[dict]) -> dict[str, list[dict]]:
    """Scan for proprietary configuration files."""
    hits: dict[str, list[dict]] = {}

    for rule in rules:
        for config_name in rule["detect_by"].get("config_files", []):
            # Search recursively (some config files are in src/main/resources, etc.)
            for found in repo.rglob(config_name):
                # Skip build output and hidden dirs
                parts = found.relative_to(repo).parts
                if any(p in SKIP_DIRS or p.startswith(".") for p in parts):
                    continue

                rel_path = str(found.relative_to(repo))

                # Extract keys from XML/properties files
                keys: list[str] = []
                config_type = "unknown"
                if config_name.endswith(".xml"):
                    config_type = "xml"
                    keys = _extract_xml_keys(found)
                elif config_name.endswith(".properties"):
                    config_type = "properties"
                    keys = _extract_properties_keys(found)
                elif config_name.endswith((".yml", ".yaml")):
                    config_type = "yaml"

                hits.setdefault(rule["name"], []).append({
                    "file": rel_path,
                    "type": config_type,
                    "keys": keys[:20],  # cap
                })

    return hits


# ---------------------------------------------------------------------------
# Migration impact computation
# ---------------------------------------------------------------------------

def _compute_migration_impact(
    result: EnterpriseFrameworkResult,
    rules: list[dict],
) -> dict:
    """Compute overall migration impact from detected frameworks."""
    if not result.frameworks_detected:
        return {
            "complexity": "low",
            "blockers": [],
            "recommendations": ["No enterprise frameworks detected. Standard migration."],
        }

    # Find highest-confidence internal framework
    internal = [f for f in result.frameworks_detected if f["category"] == "internal"]
    if not internal:
        return {
            "complexity": "low",
            "blockers": [],
            "recommendations": ["Only open-source/standard frameworks detected."],
        }

    primary = max(internal, key=lambda f: f["confidence"])
    rule = next((r for r in rules if r["name"] == primary["name"]), None)
    notes = rule.get("migration_notes", {}) if rule else {}

    blockers = []
    recommendations = []

    # Proprietary configs are blockers
    for cfg in result.proprietary_configs:
        if cfg["framework"] == primary["name"]:
            blockers.append(f"Proprietary config: {cfg['file']} must be migrated")

    # Custom annotations need migration
    unique_annotations = set()
    for ann in result.annotations_found:
        if ann["framework"] == primary["name"]:
            unique_annotations.add(ann["annotation"])
    if unique_annotations:
        blockers.append(
            f"{len(unique_annotations)} custom annotation(s) need migration: "
            + ", ".join(sorted(unique_annotations)[:5])
        )

    # Internal libraries
    unique_libs = set()
    for lib in result.internal_libraries:
        if lib["framework"] == primary["name"]:
            unique_libs.add(f"{lib['group']}:{lib['artifact']}")
    if unique_libs:
        recommendations.append(
            f"{len(unique_libs)} internal library/ies to replace: "
            + ", ".join(sorted(unique_libs)[:5])
        )

    # From migration notes
    for change in notes.get("key_changes", []):
        recommendations.append(change)

    return {
        "complexity": notes.get("complexity", "medium"),
        "primary_framework": primary["name"],
        "target_framework": notes.get("target", "Unknown"),
        "blockers": blockers,
        "recommendations": recommendations,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _iter_source_files(repo: Path, extensions: set[str]):
    """Yield source files matching extensions, skipping SKIP_DIRS."""
    for ext in extensions:
        for f in repo.rglob(f"*{ext}"):
            parts = f.relative_to(repo).parts
            if any(p in SKIP_DIRS or p.startswith(".") for p in parts):
                continue
            if f.is_file():
                yield f


def _extract_xml_keys(path: Path) -> list[str]:
    """Extract top-level element/bean names from an XML config."""
    try:
        tree = ET.parse(str(path))
        root = tree.getroot()
        keys = []
        for child in root:
            tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            name = child.get("id") or child.get("name") or tag
            keys.append(name)
        return keys
    except Exception:
        return []


def _extract_properties_keys(path: Path) -> list[str]:
    """Extract property keys from a .properties file."""
    try:
        keys = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                keys.append(line.split("=", 1)[0].strip())
        return keys
    except Exception:
        return []
