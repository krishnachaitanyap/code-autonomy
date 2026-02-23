# Java Middleware Capabilities for code-autonomy

## Context

This plan adds **9 AI-assisted development capabilities** for Java middleware applications (Spring Boot microservices, enterprise integration, data access, security, monitoring) to the code-autonomy platform. The system already has a strong Java foundation — javalang AST parsing, 8 testing strategies, Maven/Gradle support, JIRA-to-PR pipeline, and 8 code intelligence tools. This plan closes the remaining gaps to deliver a complete Java middleware development platform.

**Design principle**: All capabilities are delivered through the existing agent loop via three channels: (a) system prompt enrichment, (b) new testing strategy entries, and (c) new code intelligence tools. No new loop mechanisms. Configuration-driven so non-Java projects are unaffected.

---

## What Already Works (reuse as-is)

| Area | Existing Implementation |
|------|------------------------|
| Agentic loop (50 turns) | `src/agent/analyzer.py` — explore/edit/test/fix/complete |
| Java AST parsing | `src/code_index/symbol_table.py` — classes, interfaces, enums, methods, annotations, generics, Javadoc |
| 8 testing strategies | `src/code/testing_strategies.py` — unit, integration, bdd, contract, e2e, soap, jisi_bdd, auto |
| Maven/Gradle execution | `src/code/executor.py` — detect_build_tool(), run_java_tests() |
| 8 code intelligence tools | `src/code_index/tools.py` — find_callers, find_dependents, impact_analysis, describe_entity, find_similar, context_for_edit, predict_breakage, find_all_usages |
| JIRA integration | `src/jira/client.py`, `session.py` — OAuth, multi-story, session persistence |
| Bitbucket Server PRs | `src/platform/bitbucket_server.py`, `src/jira/bitbucket_bridge.py` |
| Enterprise BDD (JISI) | `src/bdd/service_spec.py`, `prompt_builder.py`, `output_parser.py` |
| Working memory + checkpointing | `src/agent/knowledge.py` — cross-turn + cross-run persistence |
| Plan mode + ask mode | `src/agent/analyzer.py` — human approval gates, read-only Q&A |

---

## New Directory: `src/java/`

All new Java middleware capabilities live in a new `src/java/` package:

```
src/java/
  __init__.py
  refactoring.py          # Capability 2: Refactoring patterns
  modernization.py        # Capability 3: Migration patterns
  stack_trace.py          # Capability 4: Stack trace parser
  quality.py              # Capability 5: Checkstyle/PMD/SpotBugs
  templates.py            # Capability 6: Code generation templates
  ci_templates.py         # Capability 7: CI/CD pipeline templates
  spring_intelligence.py  # Capability 8: Spring-specific code intelligence
  agentic_prompts.py      # Capability 9: Pre-built multi-step prompts
```

---

## Capability 1: Unit Testing for Java Middleware

**Status**: Partially exists (generic JUnit5/Mockito). Needs Spring-specific and messaging strategies.

**Changes**:

- **`src/code/testing_strategies.py`** (MODIFY) — Add 4 new entries to `STRATEGY_GUIDANCE`:
  - `spring_unit`: Spring Boot-specific unit testing — `@WebMvcTest` for controllers (MockMvc), `@ExtendWith(MockitoExtension)` + `@InjectMocks` for services, `@DataJpaTest` for repositories (H2), `@TestPropertySource` for config
  - `kafka`: Spring Kafka testing — `@EmbeddedKafka`, `KafkaTemplate`, `@KafkaListener` test patterns, `ConsumerRecord` assertions
  - `rabbitmq`: Spring AMQP testing — `RabbitListenerTestHarness`, `TestRabbitTemplate`, `@RabbitListener` verification
  - `security`: Spring Security testing — `@WithMockUser`, `@WithCustomAuth`, `SecurityMockMvcConfigurers`, OAuth2/JWT token testing
  - Extend auto-detection keywords in `get_testing_strategy_context()` for each new strategy
  - Add new strategy names to `STRATEGIES` list

---

## Capability 2: Code Refactoring

**Status**: Agent can edit code, but no refactoring-specific guidance.

**Changes**:

- **`src/java/refactoring.py`** (NEW) — Refactoring pattern library:
  - `REFACTORING_PROMPT`: Guidance for Extract Method, Extract Interface, Rename, Move Class
  - Spring-specific: `@Autowired` injection implications, `@Qualifier` string updates, `@Transactional` proxy boundaries, `@Value("${prop}")` coordinated renames
  - `detect_refactoring_intent(requirements: str) -> bool`: Keyword detection (refactor, extract, rename, clean up, consolidate, simplify)

- **`src/agent/analyzer.py`** (MODIFY) — In `_build_agent_context()` (~line 367), add conditional injection:
  ```python
  if detect_refactoring_intent(requirements):
      refactoring_section = REFACTORING_PROMPT
  ```
  Insert `refactoring_section` into `user_msg` assembly at line 388.

---

## Capability 3: Modernization & Migrations

**Status**: Not implemented.

**Changes**:

- **`src/java/modernization.py`** (NEW):
  - `JAVA_VERSION_MIGRATIONS`: Prompt templates for Java 8->11, 8->17, 11->17, 17->21 (records, sealed classes, text blocks, pattern matching, virtual threads)
  - `FRAMEWORK_MIGRATIONS`: Prompt templates for EJB->Spring, Struts->Spring MVC, XML config->Java config, javax->jakarta namespace, Spring Boot 2->3
  - `detect_java_version(repo_path: str) -> str`: Parse `<maven.compiler.source>` from pom.xml or `sourceCompatibility` from build.gradle
  - `detect_frameworks(symbol_table) -> list[str]`: Detect frameworks from import patterns (javax.ejb.*, org.springframework.*, javax.servlet.*)
  - `get_migration_prompt(source_version, target_version, source_framework, target_framework) -> str`

- **`src/agent/analyzer.py`** (MODIFY) — In `_build_agent_context()`, detect migration keywords ("migrate", "modernize", "upgrade", "java 17") and inject appropriate migration prompt.

---

## Capability 4: Debugging & Root Cause Analysis

**Status**: Generic error-driven regeneration exists. No Java-specific stack trace parsing.

**Changes**:

- **`src/java/stack_trace.py`** (NEW):
  - `StackFrame` dataclass: class_name, method, file, line, is_project
  - `JavaException` dataclass: type, message, frames, caused_by (nested)
  - `parse_java_stack_trace(text: str) -> list[JavaException]`: Regex-based parser for `at com.example.Class.method(File.java:42)` and `Caused by:` chains
  - `map_frames_to_source(exception, symbol_table, repo_path) -> str`: Map project frames to actual source code lines, producing focused debugging context
  - `SPRING_ERROR_HINTS`: Dict mapping common Spring exceptions to debugging guidance (BeanCreationException, NoSuchBeanDefinitionException, HttpMessageNotReadableException, DataIntegrityViolationException, etc.)
  - `enhance_error_output(error_text, symbol_table, repo_path) -> str`: Detect Java exceptions in test output, parse them, map to source, add Spring hints

- **`src/agent/analyzer.py`** (MODIFY) — In the agent loop where `run_command` tool results are processed, if output contains Java stack traces (detected by `"at "` frame pattern + `"Exception"` keyword), call `enhance_error_output()` and append enriched context to tool result before injecting into conversation.

---

## Capability 5: Code Quality Improvements

**Status**: Not implemented.

**Changes**:

- **`src/java/quality.py`** (NEW):
  - `detect_quality_tools(repo_path) -> list[str]`: Check pom.xml/build.gradle for checkstyle-maven-plugin, maven-pmd-plugin, spotbugs-maven-plugin
  - `run_quality_check(repo_path, tool="all") -> str`: Execute `mvn checkstyle:check` / `mvn pmd:check` / `mvn spotbugs:check`, parse XML output, return structured findings with file:line references
  - `CODE_QUALITY_PROMPT`: Guidance for common Java code smells — God Class, Long Method, Feature Envy, field injection vs constructor injection, missing `@Transactional`, raw types, missing validation annotations

- **`src/agent/tools.py`** (MODIFY) — Add new tool schema `run_quality_check`:
  ```python
  _RUN_QUALITY_CHECK_SCHEMA = _tool("run_quality_check",
      "Run Java code quality tools (Checkstyle, PMD, SpotBugs). Returns findings with file:line.",
      {"tool": {"type": "string", "description": "checkstyle, pmd, spotbugs, or all"}},
      required=[])
  ```
  Add to `AGENT_TOOLS` list (conditionally, when Java project detected). Add handler in `execute_tool()`.

- **`src/agent/analyzer.py`** (MODIFY) — Inject `CODE_QUALITY_PROMPT` into system prompt when quality-related keywords detected in requirements.

---

## Capability 6: Single-Command Code Generation (Templates)

**Status**: Agent can write files but no middleware-specific templates.

**Changes**:

- **`src/java/templates.py`** (NEW) — Middleware template library:
  - `TEMPLATES` dict with prompt templates for: `rest_controller`, `service`, `repository`, `entity`, `dto_record`, `kafka_consumer`, `kafka_producer`, `rabbitmq_listener`, `security_config`, `actuator_config`, `exception_handler` (`@ControllerAdvice`), `mapper` (MapStruct/manual)
  - Each template includes: Spring annotations, constructor injection, SLF4J logging, OpenAPI annotations, validation annotations
  - `get_template_prompt(template_name, entity_name, package_name) -> str`: Build parameterized generation prompt
  - `detect_template_from_requirements(requirements) -> str | None`: Keyword-based detection

- **`src/agent/analyzer.py`** (MODIFY) — In `_build_agent_context()`, detect template requirements and inject the appropriate template prompt as scaffolding guidance.

---

## Capability 7: Automation (CI/CD Enhancement)

**Status**: JIRA + Bitbucket pipeline is production-ready. Needs CI/CD template generation and PR description enhancement.

**Changes**:

- **`src/java/ci_templates.py`** (NEW):
  - `GITHUB_ACTIONS_SPRING_BOOT`: Maven build + test + Docker + deploy workflow
  - `JENKINS_PIPELINE_SPRING_BOOT`: Declarative Jenkinsfile with Maven stages
  - `GITLAB_CI_SPRING_BOOT`: .gitlab-ci.yml with build/test/deploy stages
  - `generate_ci_pipeline(ci_system, build_tool) -> str`: Select and parameterize template

- **`src/platform/pr_platform.py`** (MODIFY) — Enhance PR description builder to include:
  - Detected testing strategy
  - Files changed summary with middleware component classification (controller/service/repo/entity/test)
  - Dependency changes from pom.xml diff (if any)

---

## Capability 8: Developer Tool Enhancements (Spring Intelligence)

**Status**: 8 code intelligence tools exist. No Spring-specific intelligence.

**Changes**:

- **`src/java/spring_intelligence.py`** (NEW):
  - `extract_spring_endpoints(symbol_table) -> list[dict]`: Find all REST endpoints from `@GetMapping`, `@PostMapping`, `@RequestMapping`, etc. in symbol table decorators. Returns: HTTP method, path (from annotation value), handler FQN, file:line
  - `extract_spring_beans(symbol_table) -> list[dict]`: Find all Spring beans from `@Service`, `@Component`, `@Repository`, `@Controller`, `@RestController`, `@Configuration`, `@Bean` annotations
  - `extract_autowired_edges(symbol_table, repo_path) -> list[tuple]`: Parse `@Autowired` fields and constructor params to build injection dependency edges

- **`src/code_index/tools.py`** (MODIFY) — Add 2 new tool schemas:
  ```python
  _FIND_ENDPOINTS_SCHEMA = _tool("find_endpoints",
      "Find all REST/SOAP endpoints in the Java project. Returns HTTP method, path, handler, file:line.",
      {}, required=[])

  _FIND_BEANS_SCHEMA = _tool("find_beans",
      "Find all Spring bean definitions (@Service, @Component, @Repository, @Bean, etc.).",
      {}, required=[])
  ```
  Add to `CODE_INDEX_TOOLS` list and `execute_code_index_tool()` dispatcher.

- **`src/context/call_graph/java_extractor.py`** (MODIFY) — Enhance call graph node IDs to include parameter types for method overload disambiguation: `File.java::ClassName.methodName(ParamType1,ParamType2)` instead of `File.java::methodName`.

---

## Capability 9: Agentic Prompts & Analyses

**Status**: Agent loop is mature. Needs pre-built prompts for complex middleware tasks.

**Changes**:

- **`src/java/agentic_prompts.py`** (NEW):
  - `PROMPTS` dict with structured multi-step prompts:
    - `build_microservice`: EXPLORE -> SCAFFOLD (entity/repo/service/controller/DTO) -> CONFIGURE (application.yml) -> TEST -> DOCUMENT
    - `api_audit`: Enumerate endpoints -> Check auth -> Validate input -> Review error handling -> Report
    - `security_audit`: Scan for hardcoded secrets -> Check auth config -> Review CORS -> Check SQL injection -> Report
    - `performance_analysis`: Find N+1 queries -> Check caching -> Review thread pools -> Profile endpoints
    - `dependency_upgrade`: Analyze deps -> Check vulnerabilities -> Upgrade -> Test -> Fix breaking changes
  - `get_agentic_prompt(task_type, **kwargs) -> str`: Build prompt with variable substitution
  - `detect_task_type(requirements) -> str | None`: Keyword detection

- **`src/agent/analyzer.py`** (MODIFY) — In `_build_agent_context()`, detect agentic task types and prepend structured decomposition prompt.

---

## Configuration

- **`src/config_loader.py`** (MODIFY) — Add new section at ~line 206:
  ```python
  "java_middleware": {
      "enabled": get_bool("java_middleware", "enabled", True),
      "auto_detect": get_bool("java_middleware", "auto_detect", True),
      "quality_tools": get_bool("java_middleware", "quality_tools", True),
      "modernization": get_bool("java_middleware", "modernization", True),
      "enhanced_stack_traces": get_bool("java_middleware", "enhanced_stack_traces", True),
      "spring_intelligence": get_bool("java_middleware", "spring_intelligence", True),
  },
  ```

- **`config.example.ini`** (MODIFY) — Add `[java_middleware]` section with documentation.

---

## Files Summary

### New Files (9 source + 5 tests)

| File | Lines (est.) | Purpose |
|------|-------------|---------|
| `src/java/__init__.py` | 5 | Package init |
| `src/java/refactoring.py` | ~80 | Refactoring patterns + detection |
| `src/java/modernization.py` | ~200 | Java version + framework migration patterns |
| `src/java/stack_trace.py` | ~180 | Stack trace parser + Spring error hints |
| `src/java/quality.py` | ~150 | Checkstyle/PMD/SpotBugs integration |
| `src/java/templates.py` | ~250 | Middleware code generation templates |
| `src/java/ci_templates.py` | ~120 | CI/CD pipeline templates |
| `src/java/spring_intelligence.py` | ~150 | Spring endpoint/bean/injection extraction |
| `src/java/agentic_prompts.py` | ~180 | Pre-built multi-step task prompts |
| `tests/test_java_stack_trace.py` | ~100 | Stack trace parser tests |
| `tests/test_java_quality.py` | ~80 | Quality tool detection tests |
| `tests/test_java_modernization.py` | ~80 | Migration detection tests |
| `tests/test_java_templates.py` | ~60 | Template selection tests |
| `tests/test_java_spring_intelligence.py` | ~100 | Endpoint/bean extraction tests |

### Modified Files (7)

| File | Changes |
|------|---------|
| `src/code/testing_strategies.py` | Add 4 strategies (spring_unit, kafka, rabbitmq, security) + extend auto-detection |
| `src/agent/analyzer.py` | Inject middleware prompts in `_build_agent_context()` (~line 367-391) |
| `src/agent/tools.py` | Add `run_quality_check` tool schema + handler |
| `src/code_index/tools.py` | Add `find_endpoints` + `find_beans` tools |
| `src/context/call_graph/java_extractor.py` | Overload-aware method node IDs |
| `src/config_loader.py` | Add `[java_middleware]` config section |
| `config.example.ini` | Document `[java_middleware]` settings |

---

## Implementation Order

| Phase | Capabilities | Rationale |
|-------|-------------|-----------|
| **Phase 1** | 1 (Testing) + Config | Low risk, immediate value, enables other phases |
| **Phase 2** | 4 (Debugging) + 5 (Quality) | High-impact developer productivity |
| **Phase 3** | 8 (Spring Intelligence) + 2 (Refactoring) | Code intelligence enables better refactoring |
| **Phase 4** | 6 (Templates) + 3 (Modernization) | Code generation + migration |
| **Phase 5** | 9 (Agentic Prompts) + 7 (CI/CD) | Orchestration and automation |

Each phase is independently testable and deliverable.

---

## Verification

1. **Unit tests**: `pytest tests/test_java_*.py -v` — all new tests pass
2. **Existing tests**: `pytest tests/ -v` — all existing tests still pass (backward compat)
3. **Integration test**: Point at a real Spring Boot repo, run `--agent` with requirements like "add a REST endpoint for /api/orders" and verify:
   - Agent uses `find_endpoints` and `find_beans` to understand existing structure
   - Agent generates controller + service + repository + entity + tests
   - Agent runs `mvn test` and fixes failures
   - Stack trace parser enhances error output when tests fail
4. **Config test**: Verify `[java_middleware] enabled = false` disables all new features
5. **Non-Java test**: Run against a Python project and verify no Java middleware features are injected
