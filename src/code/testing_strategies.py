"""
Testing strategy definitions for Java projects.
Provides AI prompts and dependency guidance for BDD, Contract, Integration, Unit, and E2E testing.
"""

from typing import Optional

# Supported strategies
STRATEGIES = ["bdd", "contract", "integration", "unit", "e2e", "soap", "jisi_bdd", "auto"]

# Strategy metadata: prompt guidance + Maven/Gradle snippets
STRATEGY_GUIDANCE = {
    "bdd": {
        "name": "BDD (Behavior-Driven Development)",
        "description": "Cucumber/JGiven with Gherkin scenarios and step definitions",
        "prompt": """
## Testing Strategy: BDD (Behavior-Driven Development)

Use Cucumber with Gherkin syntax. For Java:

1. **Feature files** in `src/test/resources/` (e.g., `features/user_validation.feature`):
   - Use Gherkin: Feature, Scenario, Given, When, Then, And
   - Example:
     Feature: User validation
       Scenario: Valid email is accepted
         Given a user with email "test@example.com"
         When the email is validated
         Then the result should be valid

2. **Step definitions** in `src/test/java/.../steps/`:
   - Annotate with @Given, @When, @Then
   - Use cucumber-java (JUnit 5: cucumber-junit-platform-engine)

3. **Maven dependencies** (add to pom.xml if missing):
   - io.cucumber:cucumber-java (scope: test)
   - io.cucumber:cucumber-junit-platform-engine (scope: test)
   - org.junit.platform:junit-platform-suite (scope: test)

4. **Runner** (optional): Or use @Cucumber in a test class with @Suite, @IncludeEngines("cucumber")
""",
        "maven_deps": """
<!-- BDD: Cucumber -->
<dependency>
    <groupId>io.cucumber</groupId>
    <artifactId>cucumber-java</artifactId>
    <version>7.18.0</version>
    <scope>test</scope>
</dependency>
<dependency>
    <groupId>io.cucumber</groupId>
    <artifactId>cucumber-junit-platform-engine</artifactId>
    <version>7.18.0</version>
    <scope>test</scope>
</dependency>
<dependency>
    <groupId>org.junit.platform</groupId>
    <artifactId>junit-platform-suite</artifactId>
    <version>1.10.0</version>
    <scope>test</scope>
</dependency>
""",
        "gradle_deps": """
// BDD: Cucumber
testImplementation 'io.cucumber:cucumber-java:7.18.0'
testImplementation 'io.cucumber:cucumber-junit-platform-engine:7.18.0'
testImplementation 'org.junit.platform:junit-platform-suite:1.10.0'
""",
    },
    "contract": {
        "name": "Contract Testing",
        "description": "Pact or Spring Cloud Contract for API contracts",
        "prompt": """
## Testing Strategy: Contract Testing

Support both consumer-driven (Pact) and provider-driven (Spring Cloud Contract).

### Option A: Pact (consumer-driven)
1. **Consumer tests** (client): Define expected request/response, publish pact
2. **Provider tests** (server): Verify against pact
3. **Maven**: au.com.dius.pact.provider:junit5spring or spring6 (Spring Boot 3)
4. **Annotate** provider test with @PactFolder or @PactUrl, use @TestTemplate with PactVerificationSpringProvider

### Option B: Spring Cloud Contract
1. **Contract definitions** in `src/test/resources/contracts/` (Groovy or YAML)
2. **Provider generates** stubs; consumer uses WireMock stubs
3. **Provider base test**: Extends base class generated from contracts
4. **Maven**: spring-cloud-starter-contract-verifier (provider), spring-cloud-starter-contract-stub-runner (consumer)

Generate contracts that define:
- HTTP method and path
- Request headers/body
- Response status and body
- Use matchers for flexible matching (regex, type)
""",
        "maven_deps": """
<!-- Contract: Pact (consumer-driven) -->
<dependency>
    <groupId>au.com.dius.pact.provider</groupId>
    <artifactId>junit5spring</artifactId>
    <version>4.6.8</version>
    <scope>test</scope>
</dependency>
<!-- Or for Spring Boot 3: au.com.dius.pact.provider:spring6 -->

<!-- Contract: Spring Cloud Contract (alternative) -->
<!--
<dependency>
    <groupId>org.springframework.cloud</groupId>
    <artifactId>spring-cloud-starter-contract-verifier</artifactId>
    <scope>test</scope>
</dependency>
-->
""",
        "gradle_deps": """
// Contract: Pact
testImplementation 'au.com.dius.pact.provider:junit5spring:4.6.8'
""",
    },
    "integration": {
        "name": "Integration Testing",
        "description": "Spring Boot Test, TestContainers, REST Assured",
        "prompt": """
## Testing Strategy: Integration Testing

1. **Spring Boot Test**:
   - @SpringBootTest for full context
   - @WebMvcTest for Controller-only (mock services)
   - @DataJpaTest for JPA repositories
   - @MockBean for mocking dependencies

2. **TestContainers** (for DB, Redis, etc.):
   - @Container with PostgreSQLContainer, MySQLContainer, etc.
   - Provides real DB in Docker for integration tests
   - Maven: org.testcontainers:testcontainers, testcontainers:postgresql

3. **REST Assured** (API testing):
   - given().when().get(...).then().statusCode(200)
   - Maven: io.rest-assured:rest-assured (scope: test)

4. **Structure**:
   - Integration tests in `src/test/java/.../integration/` or `*IT.java`
   - Use @ActiveProfiles("test") for test config
   - @Transactional and @Rollback for DB tests if needed
""",
        "maven_deps": """
<!-- Integration: Spring Boot Test -->
<dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-test</artifactId>
    <scope>test</scope>
</dependency>
<!-- Integration: TestContainers -->
<dependency>
    <groupId>org.testcontainers</groupId>
    <artifactId>testcontainers</artifactId>
    <version>1.19.3</version>
    <scope>test</scope>
</dependency>
<dependency>
    <groupId>org.testcontainers</groupId>
    <artifactId>postgresql</artifactId>
    <version>1.19.3</version>
    <scope>test</scope>
</dependency>
<!-- Integration: REST Assured -->
<dependency>
    <groupId>io.rest-assured</groupId>
    <artifactId>rest-assured</artifactId>
    <scope>test</scope>
</dependency>
""",
        "gradle_deps": """
// Integration: Spring Boot Test, TestContainers, REST Assured
testImplementation 'org.springframework.boot:spring-boot-starter-test'
testImplementation 'org.testcontainers:testcontainers:1.19.3'
testImplementation 'org.testcontainers:postgresql:1.19.3'
testImplementation 'io.rest-assured:rest-assured'
""",
    },
    "unit": {
        "name": "Unit Testing",
        "description": "JUnit 5 + Mockito for isolated unit tests",
        "prompt": """
## Testing Strategy: Unit Testing

1. **JUnit 5** (Jupiter):
   - @Test, @BeforeEach, @AfterEach
   - @ParameterizedTest for data-driven tests
   - Assertions: assertEquals, assertTrue, assertThrows

2. **Mockito**:
   - @Mock, @InjectMocks
   - when(...).thenReturn(...), verify(...)
   - @ExtendWith(MockitoExtension.class)

3. **AssertJ** (fluent assertions):
   - assertThat(actual).isEqualTo(expected)
   - assertThat(list).hasSize(1).containsOnly(...)

4. **Structure**:
   - One test class per production class: XxxTest for Xxx
   - Place in src/test/java same package structure
   - Test one unit in isolation; mock dependencies
""",
        "maven_deps": """
<!-- Unit: JUnit 5 + Mockito -->
<dependency>
    <groupId>org.junit.jupiter</groupId>
    <artifactId>junit-jupiter</artifactId>
    <version>5.10.1</version>
    <scope>test</scope>
</dependency>
<dependency>
    <groupId>org.mockito</groupId>
    <artifactId>mockito-junit-jupiter</artifactId>
    <version>5.8.0</version>
    <scope>test</scope>
</dependency>
<dependency>
    <groupId>org.assertj</groupId>
    <artifactId>assertj-core</artifactId>
    <version>3.24.2</version>
    <scope>test</scope>
</dependency>
""",
        "gradle_deps": """
testImplementation 'org.junit.jupiter:junit-jupiter:5.10.1'
testImplementation 'org.mockito:mockito-junit-jupiter:5.8.0'
testImplementation 'org.assertj:assertj-core:3.24.2'
""",
    },
    "e2e": {
        "name": "End-to-End Testing",
        "description": "Selenium/Playwright for browser-based E2E",
        "prompt": """
## Testing Strategy: End-to-End (E2E) Testing

1. **Selenium WebDriver** (Java):
   - WebDriver driver = new ChromeDriver()
   - driver.get(url); driver.findElement(...).click()
   - Maven: org.seleniumhq.selenium:selenium-java

2. **Playwright (Java)** (modern alternative):
   - Page page = browser.newPage(); page.goto(url)
   - page.locator("button").click()
   - Maven: com.microsoft.playwright:playwright

3. **Structure**:
   - E2E tests in src/test/java/.../e2e/
   - Use @BeforeAll to start browser, @AfterAll to quit
   - Consider separate Maven/Gradle profile for E2E (slower, needs browser)
""",
        "maven_deps": """
<!-- E2E: Selenium -->
<dependency>
    <groupId>org.seleniumhq.selenium</groupId>
    <artifactId>selenium-java</artifactId>
    <version>4.15.0</version>
    <scope>test</scope>
</dependency>
<!-- Or E2E: Playwright -->
<!--
<dependency>
    <groupId>com.microsoft.playwright</groupId>
    <artifactId>playwright</artifactId>
    <version>1.40.0</version>
    <scope>test</scope>
</dependency>
-->
""",
        "gradle_deps": """
testImplementation 'org.seleniumhq.selenium:selenium-java:4.15.0'
""",
    },
    "soap": {
        "name": "SOAP / Legacy Web Services",
        "description": "SOAP web service testing for JAX-WS, Spring WS, CXF, Axis",
        "prompt": """
## Testing Strategy: SOAP / Legacy Web Service Testing

Support legacy SOAP projects (JAX-WS, Spring WS, Apache CXF, Axis).

### Option A: Spring Web Services (Spring WS)
1. **MockWebServiceServer** for client-side tests:
   - MockWebServiceServer.createServer(webServiceTemplate)
   - expect(payload(...)).andRespond(withPayload(...))
   - Use RequestMatchers, ResponseCreators from org.springframework.ws.test.client

2. **@WebServiceServerTest** or @SpringBootTest for full context
3. **Maven**: spring-ws-test (scope: test)

### Option B: JAX-WS / javax.xml.ws
1. **Dynamic client** or generated stub from WSDL
2. **JUnit 4 or 5** with @Before to create Service/Port
3. **Assert XML** response: use XMLUnit or string contains for envelope/body
4. **Mock server**: WireMock with SOAP or use in-memory endpoint

### Option C: Apache CXF
1. **CXF test utilities** or Jetty in-memory server
2. **JaxWsServerFactoryBean** for test server
3. **Client**: JaxWsProxyFactoryBean or dynamic client

### Legacy considerations
- Many SOAP projects use **JUnit 4** (@Test, @Before); support both JUnit 4 and 5
- **WSDL** location: src/main/resources/wsdl/ or similar
- **XML namespaces**: Preserve correct SOAP envelope and body namespaces
- **Endpoint URLs**: Use wiremock or test endpoint for isolation
""",
        "maven_deps": """
<!-- SOAP: Spring Web Services (if using Spring WS) -->
<dependency>
    <groupId>org.springframework.ws</groupId>
    <artifactId>spring-ws-test</artifactId>
    <version>4.0.10</version>
    <scope>test</scope>
</dependency>
<!-- SOAP: JUnit 4 (legacy SOAP projects often use JUnit 4) -->
<dependency>
    <groupId>junit</groupId>
    <artifactId>junit</artifactId>
    <version>4.13.2</version>
    <scope>test</scope>
</dependency>
<!-- SOAP: XMLUnit for XML assertions -->
<dependency>
    <groupId>org.xmlunit</groupId>
    <artifactId>xmlunit-assertj</artifactId>
    <version>2.9.1</version>
    <scope>test</scope>
</dependency>
<!-- WireMock for SOAP mocking (optional) -->
<dependency>
    <groupId>org.wiremock</groupId>
    <artifactId>wiremock</artifactId>
    <version>3.3.1</version>
    <scope>test</scope>
</dependency>
""",
        "gradle_deps": """
// SOAP: Spring Web Services
testImplementation 'org.springframework.ws:spring-ws-test:4.0.10'
// SOAP: JUnit 4 (legacy)
testImplementation 'junit:junit:4.13.2'
// SOAP: XMLUnit for XML assertions
testImplementation 'org.xmlunit:xmlunit-assertj:2.9.1'
// WireMock for SOAP mocking (optional)
testImplementation 'org.wiremock:wiremock:3.3.1'
""",
    },
    "jisi_bdd": {
        "name": "JISI BDD (Enterprise Cucumber)",
        "description": "Enterprise BDD testing with CommonSteps/GenericSteps and ServiceBase pattern",
        "prompt": """
## Testing Strategy: JISI BDD (Enterprise Cucumber)

Generate enterprise Cucumber BDD tests following the JISI framework conventions.

### Key conventions
1. **Feature files** in `src/test/resources/features/` with enterprise tags:
   - @Application-{tag}, @Service-{name}, @Team-{team}, @Test-{type}
   - Test types: regression, compare, pvt, heartbeat

2. **Steps** — use ONLY CommonSteps and GenericSteps from the framework:
   - Do NOT create custom step definitions
   - All step glue is provided by the enterprise test framework

3. **Service class** in `src/test/java/.../services/`:
   - Extends ServiceBase
   - Provides createRequest_{operationName}() methods per operation
   - Call ServiceBase methods DIRECTLY — do NOT assign return values to variables
   - Only primitive field types (String, Integer, Boolean, BigDecimal, etc.)
   - Method names MUST be unique across the entire test suite

4. **Property entry** for endpoint resolution:
   - Format: `{service}.endpoint=${${env}.profilecore.ws.url}{path}`

5. **Reference pattern**: AccountLookupRESTSvc

Use the `--bdd-spec` flag or config `bdd_spec_path` to provide a JSON service
specification for fully structured prompt generation.
""",
        "maven_deps": """
<!-- JISI BDD: Cucumber (from enterprise framework-utils) -->
<dependency>
    <groupId>io.cucumber</groupId>
    <artifactId>cucumber-java</artifactId>
    <scope>test</scope>
</dependency>
""",
        "gradle_deps": """
// JISI BDD: Cucumber (from enterprise framework-utils)
testImplementation 'io.cucumber:cucumber-java'
""",
    },
    "auto": {
        "name": "Auto-detect",
        "description": "Infer strategy from requirements and project structure",
        "prompt": "",
        "maven_deps": "",
        "gradle_deps": "",
    },
}


def get_testing_strategy_context(
    strategy: str,
    build_tool: Optional[str] = None,
    requirements: str = "",
) -> str:
    """
    Get prompt context for the specified testing strategy.
    Use when generating Java tests so the AI follows the right conventions.

    Args:
        strategy: One of bdd, contract, integration, unit, e2e, auto
        build_tool: "maven" or "gradle" - includes dependency snippets if provided
        requirements: Raw requirements text - used when strategy is "auto" to infer

    Returns:
        Multiline string to append to the AI prompt
    """
    s = (strategy or "auto").lower().strip()
    if s not in STRATEGIES:
        s = "auto"

    if s == "auto":
        # Infer from keywords in requirements
        req_lower = requirements.lower()
        if any(k in req_lower for k in ["jisi", "jisi_bdd", "commonsteps", "genericsteps", "servicebase"]):
            s = "jisi_bdd"
        elif any(k in req_lower for k in ["bdd", "cucumber", "gherkin", "given", "when", "then", "feature", "scenario"]):
            s = "bdd"
        elif any(k in req_lower for k in ["contract", "pact", "consumer", "provider", "api contract"]):
            s = "contract"
        elif any(k in req_lower for k in ["integration", "testcontainers", "rest assured", "@springboottest"]):
            s = "integration"
        elif any(k in req_lower for k in ["e2e", "selenium", "playwright", "browser", "end-to-end"]):
            s = "e2e"
        elif any(k in req_lower for k in ["soap", "wsdl", "web service", "jax-ws", "cxf", "axis", "spring ws"]):
            s = "soap"
        else:
            # Default to unit for Java when no specific strategy signaled
            s = "unit"

    meta = STRATEGY_GUIDANCE.get(s, STRATEGY_GUIDANCE["unit"])
    parts = [meta["prompt"].strip()]

    if build_tool and meta.get("maven_deps") or meta.get("gradle_deps"):
        if build_tool == "maven" and meta.get("maven_deps"):
            parts.append("\n### Maven dependencies (add to pom.xml if not present)\n")
            parts.append(meta["maven_deps"].strip())
        elif build_tool == "gradle" and meta.get("gradle_deps"):
            parts.append("\n### Gradle dependencies (add to build.gradle if not present)\n")
            parts.append(meta["gradle_deps"].strip())

    return "\n".join(parts) if parts else ""
