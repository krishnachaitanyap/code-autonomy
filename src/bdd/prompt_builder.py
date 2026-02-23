"""
Enterprise BDD prompt construction for JISI Cucumber test generation.

Builds the full prompt that instructs the AI to generate:
1. Cucumber .feature file with enterprise tags
2. Java service class extending ServiceBase
3. Property configuration entry

The prompt includes exact concrete code examples matching the
ServiceBase enterprise pattern (feature file + Java service class).
"""

from src.bdd.service_spec import ServiceSpec, FieldDefinition, Operation, _class_to_path

# Primitive types to keep; complex/nested types are filtered out
_PRIMITIVE_TYPES = frozenset({
    "String", "Integer", "Long", "Double", "Float", "Boolean",
    "BigDecimal", "BigInteger", "Date", "int", "long", "double",
    "float", "boolean", "short", "byte", "char",
})


def _filter_primitive_fields(fields: list[FieldDefinition]) -> list[FieldDefinition]:
    """Filter to only primitive/simple types, excluding complex nested objects."""
    return [f for f in fields if f.type in _PRIMITIVE_TYPES]


def _effective_feature_name(spec: ServiceSpec) -> str:
    """Return the feature name — falls back to service_name."""
    return spec.feature_name or spec.service_name


def _effective_test_types(op: Operation, spec: ServiceSpec) -> list[str]:
    """Return the effective test types for an operation (op override or spec default)."""
    return op.test_types if op.test_types else spec.test_types


def _build_examples_table(spec: ServiceSpec, op: Operation) -> str:
    """Build the Examples: table for a Scenario Outline."""
    lines = [
        "    Examples:",
        "      | channelType | userType | accountType |",
    ]
    for ct in spec.channel_types:
        for ut in spec.user_types:
            for at in op.account_types:
                lines.append(f"      | {ct:<11} | {ut:<8} | {at:<11} |")
    return "\n".join(lines)


def _build_heartbeat_scenario(spec: ServiceSpec) -> str:
    """Build the heartbeat scenario (always first)."""
    first_op = spec.operations[0].name if spec.operations else "healthCheck"
    return f"""\
  @Test-heartbeat
  @Team-{spec.team}
  Scenario: HealthCheck_{spec.domain}
    Given A C30 user
    When I request for {first_op}
    Then it should not contain Errors"""


def _build_scenario_outline(spec: ServiceSpec, op: Operation, test_type: str) -> str:
    """Build a Scenario Outline block for one operation + test type."""
    response_type = spec.response_type_name or op.name
    lines = [
        f"  @Test-{test_type}",
        f"  @Operation-{op.name}",
        f"  @Team-{spec.team}",
        f"  Scenario Outline: As a user with valid accountId, verify {op.name} for {test_type}",
        "    Given A <channelType> user",
        "    And with <userType> user",
        "    And with <accountType> account",
        f"    When I request for {op.name}",
        "    Then it should not contain Errors",
    ]
    # Add response field validation steps
    for display_name in op.response_fields_map:
        lines.append(
            f"    And it should return {display_name} information in {response_type} response"
        )
    lines.append(_build_examples_table(spec, op))
    return "\n".join(lines)


def _build_feature_file_example(spec: ServiceSpec) -> str:
    """Build the complete feature file example."""
    feature_name = _effective_feature_name(spec)
    parts = [
        f"@Application-{spec.application_tag}",
        f"@Service-{spec.service_name}",
        f"@Team-{spec.team}",
        f"Feature: {feature_name}",
        "",
        _build_heartbeat_scenario(spec),
    ]
    for op in spec.operations:
        for tt in _effective_test_types(op, spec):
            if tt == "heartbeat":
                continue  # heartbeat is handled separately above
            parts.append("")
            parts.append(_build_scenario_outline(spec, op, tt))
    return "\n".join(parts)


def _build_field_set_declaration(set_name: str, fields_map: dict[str, str]) -> str:
    """Build a static final Set<String> declaration."""
    adds = "\n".join(f'        add("{key}");' for key in fields_map)
    return f"""\
    protected static final Set<String> {set_name} = new HashSet<String>() {{{{
{adds}
    }}}};"""


def _build_create_request_method(op: Operation, suffix: str = "") -> str:
    """Build a createRequest_{operation} method."""
    method_name = f"createRequest_{op.name}{suffix}"
    payload_puts = []
    for field_key, field_expr in op.request_payload_fields:
        payload_puts.append(f'        payload.put("{field_key}", {field_expr});')
    if not payload_puts:
        # Default payload pattern using ServiceBase helpers
        payload_puts = [
            '        jsonArray.add(this.getDefaultUser().getAccount().getAccountId());',
            '        payload.put("context", this.getDefaultRestRequestContext());',
            '        payload.put("profileId", this.getDefaultUser().getProfileId());',
            '        payload.put("accountIds", jsonArray);',
        ]
        array_init = "        JSONArray jsonArray = new JSONArray();\n"
    else:
        array_init = ""

    return f"""\
    public void {method_name}() throws Throwable {{
        HashMap<String, Object> createRequest = new HashMap<>();
        JSONObject payload = new JSONObject();
{array_init}{chr(10).join(payload_puts)}
        createRequest.put("entity", payload);
        createRequest.put("endPointUrl", this.getEndPoint());
        requestResponse.setRequest(createRequest);
    }}"""


def _build_validation_methods(op: Operation, response_type: str, set_name: str) -> str:
    """Build @Then/@And validation methods for an operation."""
    methods = []

    # Per-field @Then validation
    for display_name, json_key in op.response_fields_map.items():
        safe_method = json_key.replace(".", "_")
        methods.append(f"""\
    @Then("^it should contain {json_key} in the response$")
    public void it_should_have_{safe_method}() throws Throwable {{
        String validResponse = requestResponse.getResponse().toString();
        Assert.assertTrue("Response should contain {json_key}", validResponse.contains("{json_key}"));
    }}""")

    # @And return types validation
    methods.append(f"""\
    @And("^it should return (.*) information in {response_type} response$")
    public void contains_return_types(String types) throws Throwable {{
        JSONArray response = (JSONArray) (((JSONObject) requestResponse.getResponse()).get("response"));
        Assert.assertNotNull(response);
        Assert.assertTrue("Invalid ReturnType: " + types, {set_name}.contains(types));
        checkDataElementInResponse(response, types);
    }}""")

    return "\n\n".join(methods)


def _build_check_data_element_method() -> str:
    """Build the checkDataElementInResponse helper."""
    return """\
    private static void checkDataElementInResponse(JSONArray response, String element) {
        JSONObject obj = (JSONObject) response.get(0);
        Assert.assertNotNull(obj.get(element).toString());
    }"""


def _build_service_class_example(spec: ServiceSpec) -> str:
    """Build the complete Java service class example."""
    parts = [
        f"package {spec.package_name};",
        "",
        "import com.cig.gws.ServiceBase;",
        "import cucumber.api.java.en.And;",
        "import cucumber.api.java.en.Then;",
        "import org.json.simple.JSONArray;",
        "import org.json.simple.JSONObject;",
        "import org.junit.Assert;",
        "",
        "import java.util.HashMap;",
        "import java.util.Set;",
        "import java.util.HashSet;",
        "",
        f"public class {spec.service_name} extends {spec.base_class} {{",
    ]

    response_type = spec.response_type_name or (
        spec.operations[0].name if spec.operations else "response"
    )

    # Build per-operation sections
    for op in spec.operations:
        set_name = f"{op.name}ReturnTypes"
        if op.response_fields_map:
            parts.append("")
            parts.append(_build_field_set_declaration(set_name, op.response_fields_map))

        # createRequest method for the base operation
        parts.append("")
        parts.append(_build_create_request_method(op))

        # Per-test-type variant createRequest methods (e.g. _pvt, _compare)
        for tt in _effective_test_types(op, spec):
            if tt in ("heartbeat", "regression"):
                continue
            parts.append("")
            parts.append(_build_create_request_method(op, suffix=f"_{tt}"))

        # Validation methods
        if op.response_fields_map:
            parts.append("")
            parts.append(_build_validation_methods(op, response_type, set_name))

    # checkDataElementInResponse helper
    parts.append("")
    parts.append(_build_check_data_element_method())
    parts.append("}")

    return "\n".join(parts)


def _build_property_entry(spec: ServiceSpec) -> str:
    """Build the property configuration line."""
    return f"{spec.service_name}.endpoint=${{${{env}}.{spec.domain}.ws.url}}{spec.endpoint}"


def _build_invoker_handler_block(invoker_path: str, handler_path: str, label: str = "") -> str:
    """Build the instruction block for a single invoker/handler pair."""
    parts = []
    prefix = f"**{label}** — " if label else ""
    if invoker_path:
        parts.append(f"""\
{prefix}**Invoker (Request DTO)**: `{invoker_path}`
- Read this file to extract all request fields (field names, types, required/optional)
- Look for: class fields, setter methods, @JsonProperty annotations, or constructor parameters
- Use the extracted fields to build the `payload.put(...)` calls in `createRequest_{{operation}}()`
- Map each field to the appropriate ServiceBase helper or literal value""")
    if handler_path:
        parts.append(f"""\
{prefix}**Handler (Response DTO)**: `{handler_path}`
- Read this file to extract all response fields (field names, types)
- Look for: class fields, getter methods, @JsonProperty annotations
- Use the extracted fields to populate the static `Set<String>` for return type validation
- Use the extracted fields to generate `@Then`/`@And` validation step methods
- Each response field should map to a `checkDataElementInResponse()` call""")
    return "\n\n".join(parts)


def _build_source_review_section(spec: ServiceSpec) -> str:
    """Build the Pre-Generation Step section that instructs the AI to read Invoker/Handler files.

    Returns an empty string when no invoker/handler classes are specified (backward compatible).
    """
    # Collect service-level references
    svc_invoker = _class_to_path(spec.invoker_class) if spec.invoker_class else ""
    svc_handler = _class_to_path(spec.handler_class) if spec.handler_class else ""

    # Collect per-operation overrides
    op_overrides = []
    for op in spec.operations:
        if op.invoker_class or op.handler_class:
            inv = _class_to_path(op.invoker_class) if op.invoker_class else ""
            hdl = _class_to_path(op.handler_class) if op.handler_class else ""
            op_overrides.append((op.name, inv, hdl))

    # Nothing to emit
    if not svc_invoker and not svc_handler and not op_overrides:
        return ""

    parts = [
        "### Pre-Generation Step: Read Invoker/Handler Source Files",
        "",
        "Before generating artifacts, you MUST use the `read_file` tool to read the following",
        "source files and extract request/response field definitions:",
        "",
    ]

    # Service-level block
    if svc_invoker or svc_handler:
        parts.append(_build_invoker_handler_block(svc_invoker, svc_handler))
        parts.append("")

    # Per-operation overrides
    for op_name, inv_path, hdl_path in op_overrides:
        parts.append(_build_invoker_handler_block(inv_path, hdl_path, label=f"Operation `{op_name}`"))
        parts.append("")

    # How to use the extracted data
    parts.append("""\
**How to use the extracted data**:
- Request fields from Invoker → `payload.put("fieldName", value)` in createRequest methods
- Response fields from Handler → entries in the static Set<String>, @Then/@And validation methods
- Field types determine how to construct values (String literals, getDefaultUser() helpers, etc.)""")

    parts.append("")
    parts.append("---")
    parts.append("")

    return "\n".join(parts)


def build_jisi_bdd_prompt(spec: ServiceSpec) -> str:
    """
    Build the full enterprise BDD prompt for the given service specification.

    Returns a multi-line string to inject into the agent context that instructs
    the AI to generate the three JISI BDD artifacts, using exact ServiceBase
    enterprise patterns with concrete code examples.
    """
    feature_example = _build_feature_file_example(spec)
    service_class_example = _build_service_class_example(spec)
    property_entry = _build_property_entry(spec)
    source_review_section = _build_source_review_section(spec)

    create_methods = ", ".join(
        f"createRequest_{op.name}()" for op in spec.operations
    )

    prompt = f"""\
## JISI BDD Testing — Enterprise Cucumber Test Generation

Generate **three** artifacts for the **{spec.service_name}** REST service.
Follow the exact patterns shown in the examples below.

### Service Details
- Service name: {spec.service_name}
- Endpoint: {spec.endpoint}
- Team: {spec.team}
- Application tag: {spec.application_tag}
- Base class: {spec.base_class}
- Package: {spec.package_name}
- Domain: {spec.domain}
- Operations: {', '.join(f'{op.name} ({op.method})' for op in spec.operations)}

---

{source_review_section}### Artifact 1: Cucumber Feature File

**Path**: `src/test/resources/features/{spec.service_name}.feature`

Generate the feature file following this **exact** pattern:

```gherkin
{feature_example}
```

Requirements:
- Feature-level tags: @Application-{spec.application_tag}, @Service-{spec.service_name}, @Team-{spec.team}
- Heartbeat scenario MUST come first
- Each test type (regression, end_to_end, pvt, compare) gets its own tagged Scenario Outline
- Per-scenario tags: @Test-{{type}}, @Operation-{{operationName}}, @Team-{spec.team}
- Steps MUST use ONLY CommonSteps and GenericSteps — do NOT create custom step definitions
- CommonSteps verbs: `Given A <channelType> user`, `And with <userType> user`, `And with <accountType> account`
- `When I request for {{operation}}`
- `Then it should not contain Errors`
- Custom And steps for response field validation
- Examples table with channelType, userType, accountType columns

### Artifact 2: Java Service Class

**Path**: `src/test/java/{spec.package_name.replace('.', '/')}/{spec.service_name}.java`

Generate the Java class following this **exact** pattern:

```java
{service_class_example}
```

Requirements:
- Class extends `{spec.base_class}`
- Import: com.cig.gws.ServiceBase, cucumber.api.java.en.And/Then, org.json.simple.JSONArray/JSONObject, org.junit.Assert, java.util.HashMap/Set/HashSet
- Static response field sets: `protected static final Set<String>` with HashSet initialization
- Create methods: {create_methods}
- `createRequest_{{operation}}()` methods build request with HashMap + JSONObject + JSONArray
- ServiceBase methods: `this.getDefaultUser().getAccount().getAccountId()`, `this.getDefaultRestRequestContext()`, `this.getDefaultUser().getProfileId()`, `this.getEndPoint()`
- `requestResponse.setRequest(createRequest)` to send, `requestResponse.getResponse()` to receive
- @Then/@And annotated validation methods with regex patterns
- `checkDataElementInResponse(JSONArray, String)` helper for field-level assertions
- Per-operation variants with suffixes (e.g., `_pvt`) get their own createRequest methods

### Artifact 3: Property Configuration Entry

**Format**:
```
{property_entry}
```

Pattern: `{{ServiceName}}.endpoint=${{${{env}}.{spec.domain}.ws.url}}{{endpoint}}`

---

### CRITICAL RULES (Enterprise Constraints)
1. Feature file MUST include heartbeat scenario first
2. Each test type (regression, end_to_end, pvt, compare) gets its own tagged Scenario Outline
3. `createRequest_{{operation}}()` methods use HashMap + JSONObject + JSONArray + ServiceBase helpers
4. Validation methods use `@Then`/`@And` with regex patterns
5. Response field checks use a static Set + `checkDataElementInResponse()` helper
6. `requestResponse.setRequest(createRequest)` and `requestResponse.getResponse()` are the bridge
7. Per-operation variants with suffixes (e.g., `_pvt`) get their own createRequest methods
8. Property format: `{{ServiceName}}.endpoint=${{${{env}}.{spec.domain}.ws.url}}{{endpoint}}`

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
2. `src/test/java/{spec.package_name.replace('.', '/')}/{spec.service_name}.java`
"""
    return prompt
