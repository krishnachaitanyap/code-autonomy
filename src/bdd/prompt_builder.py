"""
Enterprise BDD prompt construction for JISI Cucumber test generation.

Builds the full prompt that instructs the AI to generate:
1. Cucumber .feature file with enterprise tags
2. Java service class extending ServiceBase
3. Property configuration entry
"""

from src.bdd.service_spec import ServiceSpec, FieldDefinition

# Primitive types to keep; complex/nested types are filtered out
_PRIMITIVE_TYPES = frozenset({
    "String", "Integer", "Long", "Double", "Float", "Boolean",
    "BigDecimal", "BigInteger", "Date", "int", "long", "double",
    "float", "boolean", "short", "byte", "char",
})


def _filter_primitive_fields(fields: list[FieldDefinition]) -> list[FieldDefinition]:
    """Filter to only primitive/simple types, excluding complex nested objects."""
    return [f for f in fields if f.type in _PRIMITIVE_TYPES]


def _format_field_list(fields: list[FieldDefinition], label: str) -> str:
    """Format a list of fields as a readable bullet list."""
    if not fields:
        return f"  {label}: (none)\n"
    lines = [f"  {label}:"]
    for f in fields:
        req = " (REQUIRED)" if f.required else ""
        desc = f" - {f.description}" if f.description else ""
        lines.append(f"    - {f.name}: {f.type}{req}{desc}")
    return "\n".join(lines) + "\n"


def _build_tags_section(spec: ServiceSpec) -> str:
    """Build the enterprise tags section."""
    tags = [f"@Application-{spec.application_tag}"]
    tags.append(f"@Service-{spec.service_name}")
    if spec.team:
        tags.append(f"@Team-{spec.team}")
    for tt in spec.test_types:
        tags.append(f"@Test-{tt}")
    return " ".join(tags)


def _build_operations_section(spec: ServiceSpec) -> str:
    """Build per-operation detail sections."""
    parts = []
    for op in spec.operations:
        req_fields = _filter_primitive_fields(op.request_fields)
        resp_fields = _filter_primitive_fields(op.response_fields)
        section = (
            f"### Operation: {op.name}\n"
            f"  Method: {op.method}\n"
            f"  Path: {op.path}\n"
            f"{_format_field_list(req_fields, 'Request fields (primitives only)')}"
            f"{_format_field_list(resp_fields, 'Response fields (primitives only)')}"
        )
        parts.append(section)
    return "\n".join(parts)


def build_jisi_bdd_prompt(spec: ServiceSpec) -> str:
    """
    Build the full enterprise BDD prompt for the given service specification.

    Returns a multi-line string to inject into the agent context that instructs
    the AI to generate the three JISI BDD artifacts.
    """
    tags = _build_tags_section(spec)
    ops_section = _build_operations_section(spec)

    # Build createRequest method names for reference
    create_methods = ", ".join(
        f"createRequest_{op.name}()" for op in spec.operations
    )

    prompt = f"""\
## JISI BDD Testing — Enterprise Cucumber Test Generation

Generate **three** artifacts for the **{spec.service_name}** REST service.

### Service Details
- Service name: {spec.service_name}
- Endpoint: {spec.endpoint}
- Team: {spec.team}
- Application tag: {spec.application_tag}
- Base class: {spec.base_class}
- Enterprise tags: {tags}

{ops_section}

---

### Artifact 1: Cucumber Feature File

**Path**: `src/test/resources/features/{spec.service_name}.feature`

Requirements:
- Feature-level tags: {tags}
- Steps MUST use ONLY CommonSteps and GenericSteps — do NOT create custom step definitions
- Each scenario should test one operation with Given/When/Then
- Given: set up request using the service class methods
- When: execute the service call
- Then: validate response fields
- Include scenarios for each test type: {', '.join(spec.test_types)}

### Artifact 2: Java Service Class

**Path**: `src/test/java/com/enterprise/test/services/{spec.service_name}.java`

Requirements:
- Class extends `{spec.base_class}`
- Create methods: {create_methods}
- Each createRequest method builds the request object for that operation
- Call {spec.base_class} methods DIRECTLY — do NOT assign return values to variables
- Only use primitive field types (String, Integer, Boolean, BigDecimal, etc.)
- Method names MUST be unique across the entire test suite
- Follow AccountLookupRESTSvc as the reference pattern

### Artifact 3: Property Configuration Entry

**Format**:
```
{spec.service_name}.endpoint=${{${{env}}.profilecore.ws.url}}{spec.endpoint}
```

---

### CRITICAL RULES (Enterprise Constraints)
1. Steps MUST use ONLY CommonSteps/GenericSteps — NO custom step definitions
2. {spec.base_class} methods called DIRECTLY (not assigned to variables)
3. Complex types filtered to primitives only (String, Integer, Boolean, BigDecimal, Long, Double, Float, Date)
4. Step method names MUST be unique (prefix with service/operation name)
5. Follow AccountLookupRESTSvc as the canonical reference pattern
6. Feature tags must include ALL of: {tags}

### Output Format
Use these exact markers to delimit each artifact in your response:

===FEATURE_FILE_START===
(feature file content here)
===FEATURE_FILE_END===

===SERVICE_CLASS_START===
(Java service class content here)
===SERVICE_CLASS_END===

===PROPERTY_ENTRY_START===
(property entry line here)
===PROPERTY_ENTRY_END===

After generating the content within markers, use the `write_file` tool to create:
1. `src/test/resources/features/{spec.service_name}.feature`
2. `src/test/java/com/enterprise/test/services/{spec.service_name}.java`
"""
    return prompt
