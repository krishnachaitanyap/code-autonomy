"""
Auto-discovery of JISI REST and SOAP endpoints from XML servlet configuration.

Parses rest-servlet.xml (Spring beans) and cxf-servlet.xml (CXF JAX-WS)
to discover service endpoints, then reads Java source files to extract
request/response DTO fields and build complete ServiceSpec objects.

Usage::

    from src.bdd.servlet_discovery import discover_service_specs
    specs = discover_service_specs("/path/to/repo")
"""

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.bdd.service_spec import ServiceSpec, Operation, FieldDefinition, _class_to_path
from src.constants import SKIP_DIRS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# XML namespace maps
# ---------------------------------------------------------------------------
_SPRING_NS = "http://www.springframework.org/schema/beans"
_JAXWS_NS = "http://cxf.apache.org/jaxws"

# Annotation names that indicate HTTP method
_METHOD_ANNOTATIONS = {
    "GetMapping": "GET",
    "PostMapping": "POST",
    "PutMapping": "PUT",
    "DeleteMapping": "DELETE",
    "PatchMapping": "PATCH",
    "RequestMapping": "",  # method determined from attribute
}

# Java type → ServiceSpec type mapping
_JAVA_TYPE_MAP = {
    "String": "String", "int": "Integer", "Integer": "Integer",
    "long": "Long", "Long": "Long", "double": "Double", "Double": "Double",
    "float": "Float", "Float": "Float", "boolean": "Boolean", "Boolean": "Boolean",
    "BigDecimal": "BigDecimal", "BigInteger": "BigInteger", "Date": "Date",
    "short": "Integer", "byte": "Integer", "char": "String",
}


# ---------------------------------------------------------------------------
# Intermediate data model
# ---------------------------------------------------------------------------
@dataclass
class DiscoveredEndpoint:
    """Raw endpoint discovered from XML before Java analysis."""
    bean_id: str
    fqcn: str              # Fully qualified class name
    address: str = ""      # SOAP endpoint path (empty for REST)
    protocol: str = "REST" # "REST" or "SOAP"


# ======================================================================
# A. XML file discovery
# ======================================================================

def _find_servlet_xml_files(repo_path: str) -> tuple[list[Path], list[Path]]:
    """Find rest-servlet.xml and cxf-servlet.xml files in the repo.

    Returns (rest_files, cxf_files).
    """
    repo = Path(repo_path)
    rest_files: list[Path] = []
    cxf_files: list[Path] = []

    for xml_path in repo.rglob("*.xml"):
        if not xml_path.is_file():
            continue
        if any(p in xml_path.relative_to(repo).parts for p in SKIP_DIRS):
            continue

        name_lower = xml_path.name.lower()
        if "rest" in name_lower and "servlet" in name_lower:
            rest_files.append(xml_path)
        elif "cxf" in name_lower and "servlet" in name_lower:
            cxf_files.append(xml_path)

    return rest_files, cxf_files


# ======================================================================
# B. REST XML parsing
# ======================================================================

def _parse_rest_servlet_xml(xml_path: Path) -> list[DiscoveredEndpoint]:
    """Parse a Spring beans XML to extract REST controller/invoker beans."""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    endpoints: list[DiscoveredEndpoint] = []

    # Find <bean> elements — handle both namespaced and bare tags
    for elem in root.iter():
        tag = elem.tag
        # Strip namespace if present
        if "}" in tag:
            tag = tag.split("}", 1)[1]
        if tag != "bean":
            continue

        fqcn = elem.get("class", "")
        bean_id = elem.get("id", "")
        if not fqcn:
            continue

        # Only keep beans that look like controllers or invokers
        simple_name = fqcn.rsplit(".", 1)[-1]
        if any(kw in simple_name for kw in ("Controller", "Invoker", "Resource", "RestService")):
            endpoints.append(DiscoveredEndpoint(
                bean_id=bean_id,
                fqcn=fqcn,
                protocol="REST",
            ))

    return endpoints


# ======================================================================
# C. CXF / SOAP XML parsing
# ======================================================================

def _parse_cxf_servlet_xml(xml_path: Path) -> list[DiscoveredEndpoint]:
    """Parse a CXF JAX-WS XML to extract SOAP endpoints."""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    endpoints: list[DiscoveredEndpoint] = []

    # Find <jaxws:endpoint> elements
    for elem in root.iter():
        tag = elem.tag
        # Match both {namespace}endpoint and bare endpoint
        if "}" in tag:
            ns, local = tag.split("}", 1)
            ns = ns.lstrip("{")
        else:
            ns, local = "", tag

        if local != "endpoint":
            continue
        # Confirm it's a jaxws endpoint (namespace contains "jaxws" or "cxf")
        if ns and "jaxws" not in ns and "cxf" not in ns:
            continue

        implementor = elem.get("implementor", "")
        bean_id = elem.get("id", "")
        address = elem.get("address", "")
        if not implementor:
            continue

        endpoints.append(DiscoveredEndpoint(
            bean_id=bean_id,
            fqcn=implementor,
            address=address,
            protocol="SOAP",
        ))

    return endpoints


# ======================================================================
# D. Service name derivation
# ======================================================================

def _derive_service_name(bean_id: str, fqcn: str, protocol: str) -> str:
    """Derive a service name from bean ID and fully qualified class name.

    REST: strips Controller/Resource suffix, appends RESTSvc.
    SOAP: strips Impl suffix and version suffix (e.g. _20160313).
    """
    # Start from the simple class name
    simple = fqcn.rsplit(".", 1)[-1] if fqcn else bean_id

    if protocol == "SOAP":
        # Strip Impl suffix (keep Svc if present, e.g. CISCustomerSvcImpl → CISCustomerSvc)
        if simple.endswith("Impl"):
            simple = simple[: -len("Impl")]
        # The bean_id may contain a version suffix like _20160313 — strip it
        # but keep the base service name from the class (more reliable)
        return simple if simple else bean_id

    # REST
    for suffix in ("Controller", "RestController", "Resource"):
        if simple.endswith(suffix):
            simple = simple[: -len(suffix)]
            break

    # Append RESTSvc if not already ending with Svc
    if not simple.endswith("Svc"):
        simple += "RESTSvc"

    return simple


# ======================================================================
# E. Java source analysis
# ======================================================================

def _find_java_source(repo_path: str, fqcn: str) -> Optional[Path]:
    """Locate the Java source file for a fully qualified class name."""
    if not fqcn:
        return None
    repo = Path(repo_path)
    # Standard Maven layout
    rel_path = _class_to_path(fqcn)  # "src/main/java/com/.../Foo.java"
    candidate = repo / rel_path
    if candidate.is_file():
        return candidate

    # Fallback: search by simple class name
    simple = fqcn.rsplit(".", 1)[-1] + ".java"
    for hit in repo.rglob(simple):
        if hit.is_file() and not any(p in hit.relative_to(repo).parts for p in SKIP_DIRS):
            return hit

    return None


def _build_import_map(source_content: str) -> dict[str, str]:
    """Build simple_name → fqcn map from Java import statements."""
    import_map: dict[str, str] = {}
    for m in re.finditer(r"^\s*import\s+([\w.]+)\s*;", source_content, re.MULTILINE):
        fqcn = m.group(1)
        simple = fqcn.rsplit(".", 1)[-1]
        import_map[simple] = fqcn
    return import_map


def _extract_endpoint_from_annotations(tree, source_content: str) -> tuple[str, str]:
    """Extract base endpoint path and default HTTP method from class-level annotations.

    Returns (path, method). Path defaults to empty, method defaults to "POST".
    """
    try:
        import javalang
    except ImportError:
        return "", "POST"

    path = ""
    method = "POST"

    for _, node in tree:
        if not isinstance(node, (javalang.tree.ClassDeclaration,)):
            continue
        for ann in (node.annotations or []):
            if ann.name not in _METHOD_ANNOTATIONS:
                continue
            # Extract value from annotation
            ann_path = _extract_annotation_value(ann)
            if ann_path:
                path = ann_path
            # Determine method
            if ann.name != "RequestMapping":
                method = _METHOD_ANNOTATIONS[ann.name]
            else:
                # Check for method= attribute
                method_val = _extract_annotation_attribute(ann, "method")
                if method_val:
                    method = method_val.replace("RequestMethod.", "").upper()
        break  # Only look at the first class declaration

    return path, method


def _extract_annotation_value(ann) -> str:
    """Extract the string value from an annotation (handles value= and bare string)."""
    try:
        import javalang
    except ImportError:
        return ""

    if ann.element is None:
        return ""

    # Bare literal: @RequestMapping("/path")
    if isinstance(ann.element, javalang.tree.Literal):
        return ann.element.value.strip('"')

    # ElementValuePair list: @RequestMapping(value="/path", method=...)
    if isinstance(ann.element, list):
        for pair in ann.element:
            if hasattr(pair, "name") and pair.name == "value":
                if hasattr(pair, "value") and isinstance(pair.value, javalang.tree.Literal):
                    return pair.value.value.strip('"')
                # Array initializer: value={"/path"}
                if hasattr(pair, "value") and isinstance(pair.value, javalang.tree.ElementArrayValue):
                    if pair.value.values:
                        first = pair.value.values[0]
                        if isinstance(first, javalang.tree.Literal):
                            return first.value.strip('"')

    return ""


def _extract_annotation_attribute(ann, attr_name: str) -> str:
    """Extract a named attribute from an annotation's element list."""
    try:
        import javalang
    except ImportError:
        return ""

    if not isinstance(ann.element, list):
        return ""

    for pair in ann.element:
        if hasattr(pair, "name") and pair.name == attr_name:
            if hasattr(pair, "value"):
                if isinstance(pair.value, javalang.tree.Literal):
                    return pair.value.value.strip('"')
                if isinstance(pair.value, javalang.tree.MemberReference):
                    return pair.value.member
    return ""


def _extract_operations_from_methods(tree, base_path: str) -> list[dict]:
    """Extract operations from method-level mapping annotations.

    Returns list of {"name": ..., "path": ..., "method": ...}.
    """
    try:
        import javalang
    except ImportError:
        return []

    ops: list[dict] = []
    for _, node in tree:
        if not isinstance(node, javalang.tree.MethodDeclaration):
            continue
        for ann in (node.annotations or []):
            if ann.name not in _METHOD_ANNOTATIONS:
                continue
            ann_path = _extract_annotation_value(ann) or ""
            full_path = f"{base_path}/{ann_path}".rstrip("/") if ann_path else base_path
            if ann.name == "RequestMapping":
                method_val = _extract_annotation_attribute(ann, "method")
                http_method = method_val.replace("RequestMethod.", "").upper() if method_val else "POST"
            else:
                http_method = _METHOD_ANNOTATIONS[ann.name]

            ops.append({
                "name": node.name,
                "path": full_path,
                "method": http_method,
            })
            break  # One annotation per method is enough

    return ops


def _find_delegate_classes(tree, source_content: str) -> tuple[str, str]:
    """Find Invoker and Handler class references from field declarations.

    Returns (invoker_fqcn, handler_fqcn).
    """
    try:
        import javalang
    except ImportError:
        return "", ""

    import_map = _build_import_map(source_content)
    invoker_fqcn = ""
    handler_fqcn = ""

    for _, node in tree:
        if not isinstance(node, javalang.tree.FieldDeclaration):
            continue
        type_name = ""
        if hasattr(node.type, "name"):
            type_name = node.type.name
        if not type_name:
            continue

        if type_name.endswith("Invoker") and not invoker_fqcn:
            invoker_fqcn = import_map.get(type_name, type_name)
        elif type_name.endswith("Handler") and not handler_fqcn:
            handler_fqcn = import_map.get(type_name, type_name)

    return invoker_fqcn, handler_fqcn


def _extract_dto_fields(repo_path: str, fqcn: str) -> list[FieldDefinition]:
    """Parse a DTO/POJO Java class and extract its fields as FieldDefinitions."""
    if not fqcn:
        return []

    try:
        import javalang
    except ImportError:
        return []

    source_path = _find_java_source(repo_path, fqcn)
    if not source_path:
        return []

    content = source_path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = javalang.parse.parse(content)
    except Exception:
        logger.debug("Failed to parse Java source: %s", source_path)
        return []

    fields: list[FieldDefinition] = []
    for _, node in tree:
        if not isinstance(node, javalang.tree.FieldDeclaration):
            continue

        type_name = node.type.name if hasattr(node.type, "name") else "String"
        annotations = [a.name for a in (node.annotations or [])]
        required = "NotNull" in annotations or "Required" in annotations

        # Check for @JsonProperty to get the serialized name
        json_name = ""
        for ann in (node.annotations or []):
            if ann.name == "JsonProperty":
                val = _extract_annotation_value(ann)
                if val:
                    json_name = val

        for decl in node.declarators:
            name = json_name or decl.name
            # Skip static or final constants (likely not DTO fields)
            modifiers = set(node.modifiers or [])
            if "static" in modifiers and "final" in modifiers:
                continue
            fields.append(FieldDefinition(
                name=name,
                type=_JAVA_TYPE_MAP.get(type_name, type_name),
                required=required,
            ))

    return fields


# ======================================================================
# F. Domain extraction
# ======================================================================

def _derive_domain_from_package(fqcn: str) -> str:
    """Extract the domain from the package structure.

    Skips common prefixes (com, chase, digital, enterprise) and
    non-domain segments (api, ws, web, service, impl).
    """
    parts = fqcn.rsplit(".", 1)[0].split(".")  # package parts only
    skip = {"com", "org", "net", "chase", "digital", "enterprise",
            "api", "ws", "web", "service", "services", "impl",
            "rest", "controller", "v1", "v2", "v3"}
    for p in parts:
        if p.lower() not in skip and not re.match(r"^v\d+", p.lower()):
            return p.lower()
    return "profilecore"  # sensible default for JISI apps


# ======================================================================
# G. Spec assembly
# ======================================================================

def _build_spec_from_endpoint(
    repo_path: str,
    ep: DiscoveredEndpoint,
) -> Optional[ServiceSpec]:
    """Build a complete ServiceSpec from a discovered endpoint."""
    service_name = _derive_service_name(ep.bean_id, ep.fqcn, ep.protocol)
    domain = _derive_domain_from_package(ep.fqcn)

    invoker_fqcn = ""
    handler_fqcn = ""

    if ep.protocol == "SOAP":
        endpoint = ep.address or f"/ws/{service_name}"
        operations = [Operation(
            name=service_name,
            path=endpoint,
            method="POST",
        )]
    else:
        # REST: try to read Java source for annotations and delegates
        endpoint = f"/{domain}/services/{service_name}"
        raw_ops: list[dict] = []

        source_path = _find_java_source(repo_path, ep.fqcn)
        if source_path:
            try:
                import javalang
                content = source_path.read_text(encoding="utf-8", errors="replace")
                tree = javalang.parse.parse(content)

                ann_path, _default_method = _extract_endpoint_from_annotations(tree, content)
                if ann_path:
                    endpoint = ann_path

                raw_ops = _extract_operations_from_methods(tree, endpoint)
                invoker_fqcn, handler_fqcn = _find_delegate_classes(tree, content)
            except Exception as exc:
                logger.debug("Failed to analyze %s: %s", ep.fqcn, exc)

        if not raw_ops:
            # Fallback: single operation named after the service
            raw_ops = [{"name": service_name, "path": endpoint, "method": "POST"}]

        # Extract DTO fields from invoker (request) and handler (response)
        request_fields = _extract_dto_fields(repo_path, invoker_fqcn)
        response_fields = _extract_dto_fields(repo_path, handler_fqcn)

        # Build response_fields_map from response fields (DISPLAY_NAME → jsonKey)
        response_fields_map = {f.name.upper(): f.name for f in response_fields}

        operations = []
        for raw in raw_ops:
            operations.append(Operation(
                name=raw["name"],
                path=raw["path"],
                method=raw.get("method", "POST"),
                request_fields=request_fields,
                response_fields=response_fields,
                response_fields_map=response_fields_map,
                invoker_class=invoker_fqcn,
                handler_class=handler_fqcn,
            ))

    if not operations:
        return None

    # Derive package name from the FQCN's package
    pkg = ep.fqcn.rsplit(".", 1)[0] if "." in ep.fqcn else "com.enterprise.test.services"

    return ServiceSpec(
        service_name=service_name,
        endpoint=endpoint,
        team="",  # Cannot be auto-discovered
        operations=operations,
        domain=domain,
        package_name=pkg,
        invoker_class=invoker_fqcn,
        handler_class=handler_fqcn,
    )


# ======================================================================
# H. Public entry point
# ======================================================================

def discover_service_specs(
    repo_path: str,
    *,
    service_filter: Optional[str] = None,
    protocol_filter: Optional[str] = None,
) -> list[ServiceSpec]:
    """Auto-discover JISI service specs from servlet XML configuration files.

    Args:
        repo_path: Root path of the cloned repository.
        service_filter: Optional regex to filter by service name.
        protocol_filter: Optional ``"REST"`` or ``"SOAP"`` to limit discovery.

    Returns:
        List of ServiceSpec objects. May be empty if no XML files found.
    """
    rest_files, cxf_files = _find_servlet_xml_files(repo_path)

    if not rest_files and not cxf_files:
        logger.info("No servlet XML files found in %s", repo_path)
        return []

    endpoints: list[DiscoveredEndpoint] = []

    if protocol_filter != "SOAP":
        for xml_path in rest_files:
            try:
                endpoints.extend(_parse_rest_servlet_xml(xml_path))
            except ET.ParseError as e:
                logger.warning("Failed to parse %s: %s", xml_path, e)

    if protocol_filter != "REST":
        for xml_path in cxf_files:
            try:
                endpoints.extend(_parse_cxf_servlet_xml(xml_path))
            except ET.ParseError as e:
                logger.warning("Failed to parse %s: %s", xml_path, e)

    logger.info("Discovered %d endpoint(s) from XML", len(endpoints))

    specs: list[ServiceSpec] = []
    for ep in endpoints:
        spec = _build_spec_from_endpoint(repo_path, ep)
        if spec is None:
            continue
        if service_filter and not re.search(service_filter, spec.service_name, re.IGNORECASE):
            continue
        errors = spec.validate()
        if errors:
            logger.debug("Spec %s has validation issues: %s", spec.service_name, errors)
        specs.append(spec)

    logger.info("Built %d ServiceSpec(s)", len(specs))
    return specs
