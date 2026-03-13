"""
Migration Recipes Registry — composable building blocks for repo migration.

Each recipe defines a discrete migration step that can be combined into a
full migration roadmap. Recipes are selected based on gap analysis between
source and reference repository StackProfiles.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class MigrationRecipe:
    id: str
    name: str
    category: str  # java | dependencies | docker | k8s | cicd | config | observability | security | testing | quality
    description: str
    priority: int  # higher = more important (0-100)
    tags: list[str] = field(default_factory=list)
    prerequisites: list[str] = field(default_factory=list)  # recipe IDs that must run first
    agent_instructions: str = ""  # instructions for the AI agent executing this recipe

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "priority": self.priority,
            "tags": self.tags,
            "prerequisites": self.prerequisites,
            "agent_instructions": self.agent_instructions,
        }


# ---------------------------------------------------------------------------
# Built-in recipes (32 total)
# ---------------------------------------------------------------------------

RECIPES: list[MigrationRecipe] = [
    MigrationRecipe(
        id="java_upgrade",
        name="Java Version Upgrade (8->11->17->21)",
        category="java",
        description="Upgrade Java version to match the reference repository. Updates pom.xml/build.gradle "
                    "compiler settings, fixes deprecated API usage, and updates language features.",
        priority=90,
        tags=["java", "compiler", "language-level"],
        prerequisites=[],
        agent_instructions=(
            "1. Identify current Java version from pom.xml (<maven.compiler.source>) or build.gradle (sourceCompatibility).\n"
            "2. Identify target Java version from reference repo.\n"
            "3. Update compiler settings to target version.\n"
            "4. Replace deprecated APIs (e.g. javax -> jakarta for Java 17+).\n"
            "5. Update Dockerfile base image to match new Java version.\n"
            "6. Fix any compilation issues from language changes."
        ),
    ),
    MigrationRecipe(
        id="spring_boot_upgrade",
        name="Spring Boot Version Upgrade (2.x->3.x)",
        category="java",
        description="Upgrade Spring Boot version to match reference. Handles namespace migration "
                    "(javax->jakarta), property key changes, and auto-configuration updates.",
        priority=85,
        tags=["spring", "springboot", "framework"],
        prerequisites=["java_upgrade"],
        agent_instructions=(
            "1. Update spring-boot-starter-parent version in pom.xml.\n"
            "2. Migrate javax.* imports to jakarta.* (Spring Boot 3.x).\n"
            "3. Update deprecated configuration properties.\n"
            "4. Fix removed auto-configuration classes.\n"
            "5. Update Spring Security configuration if present.\n"
            "6. Verify application context loads correctly."
        ),
    ),
    MigrationRecipe(
        id="dependency_update",
        name="Dependency Version Alignment",
        category="dependencies",
        description="Align dependency versions with the reference repository. Adds missing dependencies, "
                    "updates outdated versions, and removes unused ones.",
        priority=70,
        tags=["maven", "gradle", "dependencies", "versions"],
        prerequisites=["java_upgrade", "spring_boot_upgrade"],
        agent_instructions=(
            "1. Compare dependency lists between source and reference pom.xml/build.gradle.\n"
            "2. Update versions for existing dependencies to match reference.\n"
            "3. Add missing dependencies from reference.\n"
            "4. Flag potentially unused dependencies for review.\n"
            "5. Ensure dependency management section is aligned."
        ),
    ),
    MigrationRecipe(
        id="dockerfile_modernize",
        name="Dockerfile Modernization",
        category="docker",
        description="Modernize Dockerfile to match reference patterns. Implements multi-stage builds, "
                    "optimizes layers, updates base images, and adds health checks.",
        priority=75,
        tags=["docker", "container", "image"],
        prerequisites=[],
        agent_instructions=(
            "1. Compare source and reference Dockerfiles.\n"
            "2. Implement multi-stage build if reference uses it.\n"
            "3. Update base image to match reference (e.g. eclipse-temurin, distroless).\n"
            "4. Optimize layer ordering for better caching.\n"
            "5. Add HEALTHCHECK if present in reference.\n"
            "6. Copy security and resource configurations from reference."
        ),
    ),
    MigrationRecipe(
        id="docker_compose_update",
        name="Docker Compose Update",
        category="docker",
        description="Update docker-compose.yml to match reference patterns. Aligns service definitions, "
                    "networks, volumes, and environment configurations.",
        priority=60,
        tags=["docker-compose", "local-dev"],
        prerequisites=["dockerfile_modernize"],
        agent_instructions=(
            "1. Compare docker-compose files between source and reference.\n"
            "2. Update service definitions to match reference patterns.\n"
            "3. Add missing services (e.g. observability, databases).\n"
            "4. Align network and volume configurations.\n"
            "5. Update environment variable patterns."
        ),
    ),
    MigrationRecipe(
        id="k8s_manifests",
        name="Kubernetes Manifest Alignment",
        category="k8s",
        description="Align Kubernetes manifests with reference. Updates deployments, services, "
                    "configmaps, resource limits, probes, and security contexts.",
        priority=80,
        tags=["kubernetes", "k8s", "deployment", "manifests"],
        prerequisites=[],
        agent_instructions=(
            "1. Compare K8s manifests between source and reference.\n"
            "2. Update Deployment spec (replicas, strategy, resources, probes).\n"
            "3. Add missing resources (HPA, PDB, NetworkPolicy, ServiceMonitor).\n"
            "4. Align resource requests/limits with reference.\n"
            "5. Update security contexts and pod security standards.\n"
            "6. Align ConfigMap and Secret references."
        ),
    ),
    MigrationRecipe(
        id="helm_chart_update",
        name="Helm Chart Update",
        category="k8s",
        description="Update Helm chart to match reference patterns. Aligns values.yaml, "
                    "templates, and chart metadata.",
        priority=65,
        tags=["helm", "kubernetes", "charts"],
        prerequisites=["k8s_manifests"],
        agent_instructions=(
            "1. Compare Helm charts between source and reference.\n"
            "2. Update Chart.yaml metadata and dependencies.\n"
            "3. Align values.yaml structure and defaults.\n"
            "4. Update templates to match reference patterns.\n"
            "5. Add missing template files from reference."
        ),
    ),
    MigrationRecipe(
        id="cicd_pipeline",
        name="CI/CD Pipeline Migration",
        category="cicd",
        description="Migrate CI/CD pipeline to match reference. Updates build, test, scan, "
                    "and deploy stages to align with golden template.",
        priority=70,
        tags=["cicd", "jenkins", "github-actions", "pipeline"],
        prerequisites=[],
        agent_instructions=(
            "1. Identify CI/CD system (Jenkinsfile, .github/workflows, .gitlab-ci.yml).\n"
            "2. Compare pipeline stages with reference.\n"
            "3. Add missing stages (security scan, quality gate, artifact publish).\n"
            "4. Update build and test commands for new versions.\n"
            "5. Align deployment stages with reference patterns.\n"
            "6. Update environment variables and secrets references."
        ),
    ),
    MigrationRecipe(
        id="config_externalization",
        name="Configuration Externalization",
        category="config",
        description="Externalize configuration to match reference patterns. Moves hardcoded "
                    "values to config files, environment variables, or config servers.",
        priority=55,
        tags=["config", "properties", "externalization"],
        prerequisites=[],
        agent_instructions=(
            "1. Compare application config files (application.yml/properties).\n"
            "2. Identify hardcoded values that should be externalized.\n"
            "3. Add missing configuration properties from reference.\n"
            "4. Set up Spring Cloud Config or Consul integration if in reference.\n"
            "5. Create profile-specific configs (dev, staging, prod) if in reference."
        ),
    ),
    MigrationRecipe(
        id="observability_alignment",
        name="Observability Stack Alignment",
        category="observability",
        description="Align observability setup with reference. Adds metrics, tracing, "
                    "health endpoints, and logging configuration.",
        priority=60,
        tags=["metrics", "tracing", "logging", "actuator", "prometheus"],
        prerequisites=["dependency_update"],
        agent_instructions=(
            "1. Compare observability dependencies and config.\n"
            "2. Add Micrometer/Prometheus metrics if in reference.\n"
            "3. Configure distributed tracing (OpenTelemetry/Sleuth).\n"
            "4. Align actuator endpoints and health checks.\n"
            "5. Update logging configuration (logback/log4j).\n"
            "6. Add custom metrics or spans from reference."
        ),
    ),
    MigrationRecipe(
        id="security_hardening",
        name="Security Hardening",
        category="security",
        description="Apply security hardening from reference. Updates Spring Security config, "
                    "adds security headers, CORS policy, and vulnerability fixes.",
        priority=75,
        tags=["security", "spring-security", "hardening", "cors"],
        prerequisites=["spring_boot_upgrade"],
        agent_instructions=(
            "1. Compare security configuration between source and reference.\n"
            "2. Update Spring Security filter chain configuration.\n"
            "3. Add security headers (CSP, HSTS, X-Frame-Options).\n"
            "4. Align CORS policy with reference.\n"
            "5. Update authentication/authorization patterns.\n"
            "6. Add dependency vulnerability scanning configuration."
        ),
    ),

    # -----------------------------------------------------------------------
    # Database-mode recipes — schema, data, type mapping, constraints, etc.
    # -----------------------------------------------------------------------

    MigrationRecipe(
        id="db_schema_migration",
        name="Database Schema Migration (DDL)",
        category="database",
        description="Generate DDL migration scripts to align source database schema with destination. "
                    "Creates/alters tables, columns, and data types to match target schema.",
        priority=90,
        tags=["database", "ddl", "schema", "tables", "columns"],
        prerequisites=[],
        agent_instructions=(
            "1. Compare source and destination database schemas (tables, columns, data types).\n"
            "2. Generate CREATE TABLE statements for missing tables.\n"
            "3. Generate ALTER TABLE statements for column differences.\n"
            "4. Handle data type conversions between database engines.\n"
            "5. Order DDL statements to respect foreign key dependencies.\n"
            "6. Generate rollback scripts for each migration step."
        ),
    ),
    MigrationRecipe(
        id="db_data_migration",
        name="Data Migration (DML)",
        category="database",
        description="Generate DML scripts to migrate data between source and destination databases. "
                    "Handles INSERT/UPDATE/UPSERT operations with data transformation.",
        priority=85,
        tags=["database", "dml", "data", "etl", "insert"],
        prerequisites=["db_schema_migration"],
        agent_instructions=(
            "1. Identify tables requiring data migration.\n"
            "2. Generate INSERT/SELECT statements for bulk data transfer.\n"
            "3. Handle data type conversions during transfer.\n"
            "4. Create upsert logic for incremental migrations.\n"
            "5. Add batch processing for large tables.\n"
            "6. Generate data validation queries post-migration."
        ),
    ),
    MigrationRecipe(
        id="db_type_mapping",
        name="Data Type Mapping & Conversion",
        category="database",
        description="Map and convert data types between source and destination database engines. "
                    "Handles vendor-specific types, precision differences, and encoding.",
        priority=80,
        tags=["database", "types", "mapping", "conversion"],
        prerequisites=[],
        agent_instructions=(
            "1. Catalog all source database column types.\n"
            "2. Map each type to the equivalent destination engine type.\n"
            "3. Handle precision/scale differences (e.g. NUMBER vs DECIMAL).\n"
            "4. Address vendor-specific types (e.g. Oracle CLOB -> PostgreSQL TEXT).\n"
            "5. Flag potential data loss from type narrowing.\n"
            "6. Generate CAST/CONVERT expressions for runtime conversion."
        ),
    ),
    MigrationRecipe(
        id="db_constraint_validation",
        name="Constraint Validation & Integrity",
        category="database",
        description="Validate and migrate database constraints. Ensures primary keys, foreign keys, "
                    "unique constraints, check constraints, and not-null rules are preserved.",
        priority=75,
        tags=["database", "constraints", "integrity", "foreign-key", "primary-key"],
        prerequisites=["db_schema_migration"],
        agent_instructions=(
            "1. Extract all constraints from source schema.\n"
            "2. Compare constraints with destination schema.\n"
            "3. Generate ALTER TABLE ADD CONSTRAINT statements for missing constraints.\n"
            "4. Validate foreign key references resolve correctly.\n"
            "5. Check for orphaned records that would violate new constraints.\n"
            "6. Order constraint creation after data migration to avoid violations."
        ),
    ),
    MigrationRecipe(
        id="db_index_optimization",
        name="Index Optimization",
        category="database",
        description="Analyze and migrate database indexes. Identifies missing indexes, redundant indexes, "
                    "and suggests optimal indexing strategies for the destination database.",
        priority=70,
        tags=["database", "indexes", "performance", "optimization"],
        prerequisites=["db_schema_migration"],
        agent_instructions=(
            "1. Extract all indexes from source database.\n"
            "2. Compare indexes with destination schema.\n"
            "3. Generate CREATE INDEX statements for missing indexes.\n"
            "4. Identify redundant or duplicate indexes.\n"
            "5. Suggest covering indexes for frequent query patterns.\n"
            "6. Consider destination engine-specific index types (GIN, BRIN, etc.)."
        ),
    ),
    MigrationRecipe(
        id="db_backup_rollback",
        name="Backup & Rollback Strategy",
        category="database",
        description="Create backup and rollback procedures for the database migration. Includes "
                    "pre-migration snapshots, incremental backups, and verified restore procedures.",
        priority=65,
        tags=["database", "backup", "rollback", "recovery", "safety"],
        prerequisites=[],
        agent_instructions=(
            "1. Design pre-migration backup strategy (full + incremental).\n"
            "2. Generate backup scripts for source database.\n"
            "3. Create rollback scripts for each migration phase.\n"
            "4. Define verification queries to validate backup integrity.\n"
            "5. Document restore procedures with estimated timelines.\n"
            "6. Create migration checkpoint markers for partial rollback."
        ),
    ),
    MigrationRecipe(
        id="db_stored_procedure_migration",
        name="Stored Procedure & Function Migration",
        category="database",
        description="Migrate stored procedures, functions, and triggers between database engines. "
                    "Handles syntax translation, parameter differences, and procedural logic.",
        priority=60,
        tags=["database", "stored-procedures", "functions", "triggers", "plsql"],
        prerequisites=["db_schema_migration"],
        agent_instructions=(
            "1. Extract all stored procedures and functions from source.\n"
            "2. Translate procedural syntax to destination engine (e.g. PL/SQL -> PL/pgSQL).\n"
            "3. Convert vendor-specific built-in functions.\n"
            "4. Migrate triggers with equivalent logic.\n"
            "5. Handle cursor and exception handling differences.\n"
            "6. Test migrated procedures with sample inputs."
        ),
    ),
    MigrationRecipe(
        id="db_view_migration",
        name="View Migration",
        category="database",
        description="Migrate database views between source and destination. Handles view definitions, "
                    "materialized views, and view dependencies.",
        priority=55,
        tags=["database", "views", "materialized-views"],
        prerequisites=["db_schema_migration"],
        agent_instructions=(
            "1. Extract all view definitions from source database.\n"
            "2. Translate view SQL to destination engine syntax.\n"
            "3. Resolve view dependencies (views referencing other views).\n"
            "4. Convert materialized views with refresh strategies.\n"
            "5. Order view creation to respect dependency chain.\n"
            "6. Validate view outputs match between source and destination."
        ),
    ),

    # -----------------------------------------------------------------------
    # NoSQL / cross-paradigm database recipes
    # -----------------------------------------------------------------------

    MigrationRecipe(
        id="db_nosql_schema_design",
        name="NoSQL Schema Design & Mapping",
        category="database",
        description="Design and map document/collection schemas for NoSQL databases. Handles "
                    "SQL-to-NoSQL denormalization, embedding vs referencing decisions, "
                    "and data modeling for MongoDB, Cassandra, DynamoDB, or Couchbase.",
        priority=88,
        tags=["database", "nosql", "mongodb", "cassandra", "dynamodb", "couchbase", "schema-design"],
        prerequisites=[],
        agent_instructions=(
            "1. Analyze source relational schema (tables, relationships, join patterns).\n"
            "2. Identify access patterns and query requirements for target NoSQL engine.\n"
            "3. Design document/collection schemas with embedding vs referencing trade-offs.\n"
            "4. Map relational joins to denormalized document structures.\n"
            "5. Handle one-to-many and many-to-many relationships.\n"
            "6. Create partition key / sort key design (DynamoDB) or shard key (MongoDB)."
        ),
    ),
    MigrationRecipe(
        id="db_nosql_data_migration",
        name="NoSQL Data Migration & ETL",
        category="database",
        description="Migrate data between SQL and NoSQL or between NoSQL engines. Handles "
                    "document transformation, denormalization, batch imports, and data validation.",
        priority=83,
        tags=["database", "nosql", "etl", "data-migration", "transformation"],
        prerequisites=["db_nosql_schema_design"],
        agent_instructions=(
            "1. Map source records to target document structures.\n"
            "2. Generate ETL scripts for bulk data transformation and loading.\n"
            "3. Handle nested document creation from relational joins.\n"
            "4. Implement batch processing with configurable chunk sizes.\n"
            "5. Add data validation and reconciliation queries.\n"
            "6. Handle binary/LOB data migration between paradigms."
        ),
    ),
    MigrationRecipe(
        id="db_nosql_index_strategy",
        name="NoSQL Index & Query Optimization",
        category="database",
        description="Design indexes and optimize queries for NoSQL databases. Covers secondary "
                    "indexes, compound indexes, TTL indexes, and query pattern optimization.",
        priority=68,
        tags=["database", "nosql", "indexes", "query-optimization", "performance"],
        prerequisites=["db_nosql_schema_design"],
        agent_instructions=(
            "1. Analyze query patterns and access frequencies.\n"
            "2. Design secondary indexes for common query patterns.\n"
            "3. Add compound indexes for multi-field queries.\n"
            "4. Configure TTL indexes for expiring data.\n"
            "5. Optimize read/write throughput with partition strategies.\n"
            "6. Add text/geospatial indexes where applicable."
        ),
    ),

    # -----------------------------------------------------------------------
    # Improvement-mode recipes — quality, testing, performance, structure
    # -----------------------------------------------------------------------

    MigrationRecipe(
        id="unit_testing",
        name="Unit Test Coverage Improvement",
        category="testing",
        description="Add or improve unit test coverage. Identifies untested classes and methods, "
                    "generates JUnit/TestNG/pytest tests, adds mock configurations, and targets "
                    "a minimum coverage threshold.",
        priority=80,
        tags=["testing", "unit-tests", "coverage", "junit", "pytest", "mockito"],
        prerequisites=[],
        agent_instructions=(
            "1. Scan src/main for all service, controller, repository, and utility classes.\n"
            "2. Scan src/test to identify which classes already have tests.\n"
            "3. For each untested or under-tested class, generate unit tests.\n"
            "4. Use appropriate mocking (Mockito, @MockBean, unittest.mock) for dependencies.\n"
            "5. Cover happy paths, edge cases, null inputs, and error conditions.\n"
            "6. Add test configuration (test application.yml, test fixtures) if missing.\n"
            "7. Target at least 80% line coverage for new tests."
        ),
    ),
    MigrationRecipe(
        id="integration_testing",
        name="Integration Test Infrastructure",
        category="testing",
        description="Set up integration test infrastructure. Adds Testcontainers for databases/messaging, "
                    "Spring Boot test slices, API integration tests, and test data builders.",
        priority=70,
        tags=["testing", "integration", "testcontainers", "spring-test"],
        prerequisites=["unit_testing"],
        agent_instructions=(
            "1. Identify external dependencies (databases, message brokers, caches, downstream APIs).\n"
            "2. Add Testcontainers dependencies and base test configuration.\n"
            "3. Create integration test base class with @SpringBootTest or test slices.\n"
            "4. Add @DataJpaTest, @WebMvcTest, @WebFluxTest slices for targeted testing.\n"
            "5. Create test data builders and fixtures for domain entities.\n"
            "6. Write integration tests for critical flows (API -> service -> DB).\n"
            "7. Configure separate test profiles (application-test.yml)."
        ),
    ),
    MigrationRecipe(
        id="performance_testing",
        name="Performance Test Setup",
        category="testing",
        description="Add performance and load testing infrastructure. Sets up JMeter, Gatling, or k6 "
                    "load test scripts, benchmark configurations, and performance baselines.",
        priority=55,
        tags=["testing", "performance", "load-testing", "jmeter", "gatling", "k6"],
        prerequisites=[],
        agent_instructions=(
            "1. Identify critical API endpoints and high-throughput operations.\n"
            "2. Create load test scripts (JMeter .jmx, Gatling simulations, or k6 scripts).\n"
            "3. Define performance baselines (response time P95, throughput, error rate).\n"
            "4. Add docker-compose services for running load tests locally.\n"
            "5. Create CI pipeline stage for automated performance regression testing.\n"
            "6. Add JMH benchmark configs for hot-path microbenchmarks if applicable."
        ),
    ),
    MigrationRecipe(
        id="security_testing",
        name="Security Testing & Scanning",
        category="testing",
        description="Add security testing infrastructure. Integrates SAST (SonarQube, SpotBugs), "
                    "dependency vulnerability scanning (OWASP, Snyk), and security-focused test cases.",
        priority=65,
        tags=["testing", "security", "sast", "owasp", "dependency-check"],
        prerequisites=[],
        agent_instructions=(
            "1. Add OWASP dependency-check plugin to build configuration.\n"
            "2. Add SpotBugs / FindSecBugs for static security analysis.\n"
            "3. Configure SonarQube quality gate rules if SonarQube is in use.\n"
            "4. Write security test cases (SQL injection, XSS, CSRF, auth bypass).\n"
            "5. Add input validation tests for all API endpoints.\n"
            "6. Add CI pipeline stage for security scanning before deployment."
        ),
    ),
    MigrationRecipe(
        id="contract_testing",
        name="API Contract Testing",
        category="testing",
        description="Add consumer-driven contract tests. Sets up Spring Cloud Contract or Pact "
                    "for API provider/consumer verification.",
        priority=50,
        tags=["testing", "contract", "pact", "spring-cloud-contract"],
        prerequisites=["integration_testing"],
        agent_instructions=(
            "1. Identify API contracts (REST endpoints, message producers/consumers).\n"
            "2. Choose contract testing framework (Spring Cloud Contract or Pact).\n"
            "3. Define contracts for each API endpoint (request/response pairs).\n"
            "4. Generate provider verification tests from contracts.\n"
            "5. Set up consumer contract stubs for downstream service testing.\n"
            "6. Integrate contract verification into CI pipeline."
        ),
    ),
    MigrationRecipe(
        id="code_quality",
        name="Code Quality & Refactoring",
        category="quality",
        description="Improve code quality by fixing code smells, removing dead code, reducing "
                    "complexity, enforcing coding standards, and improving readability.",
        priority=60,
        tags=["quality", "refactoring", "code-smells", "complexity", "standards"],
        prerequisites=[],
        agent_instructions=(
            "1. Identify code smells: long methods, god classes, deep nesting, duplicated code.\n"
            "2. Reduce cyclomatic complexity in methods exceeding threshold (>10).\n"
            "3. Extract helper methods, services, and value objects for better cohesion.\n"
            "4. Remove dead code, unused imports, and commented-out blocks.\n"
            "5. Apply consistent naming conventions and coding standards.\n"
            "6. Add Checkstyle/PMD/Spotless configuration for automated enforcement.\n"
            "7. Replace magic numbers and strings with named constants."
        ),
    ),
    MigrationRecipe(
        id="performance_optimization",
        name="Performance Optimization",
        category="quality",
        description="Optimize application performance. Identifies N+1 queries, missing indexes, "
                    "inefficient algorithms, missing caching, and blocking I/O patterns.",
        priority=65,
        tags=["performance", "optimization", "n+1", "caching", "async", "indexing"],
        prerequisites=[],
        agent_instructions=(
            "1. Identify N+1 query patterns in JPA/Hibernate entities (add @EntityGraph, fetch joins).\n"
            "2. Add missing database indexes for frequently queried columns.\n"
            "3. Add caching annotations (@Cacheable) for repeated lookups.\n"
            "4. Replace blocking I/O with async patterns where beneficial.\n"
            "5. Optimize collection processing (use streams, batch operations).\n"
            "6. Add connection pool tuning (HikariCP settings).\n"
            "7. Profile and optimize hot-path serialization/deserialization."
        ),
    ),
    MigrationRecipe(
        id="project_structure",
        name="Project Structure Optimization",
        category="quality",
        description="Reorganize project structure for better maintainability. Enforces clean "
                    "architecture layers, module boundaries, and package conventions.",
        priority=50,
        tags=["structure", "architecture", "packages", "modules", "layers"],
        prerequisites=[],
        agent_instructions=(
            "1. Analyze current package structure for layer violations.\n"
            "2. Enforce clean layering: controller -> service -> repository -> domain.\n"
            "3. Move misplaced classes to correct packages.\n"
            "4. Extract shared utilities into a common/util package.\n"
            "5. Separate DTOs from domain entities if mixed.\n"
            "6. Add package-info.java with module documentation.\n"
            "7. Create multi-module structure if project is large enough to benefit."
        ),
    ),
    MigrationRecipe(
        id="api_documentation",
        name="API Documentation & OpenAPI",
        category="quality",
        description="Add or improve API documentation. Generates OpenAPI/Swagger specs, adds "
                    "endpoint descriptions, request/response examples, and error schemas.",
        priority=45,
        tags=["documentation", "openapi", "swagger", "api-docs"],
        prerequisites=[],
        agent_instructions=(
            "1. Add springdoc-openapi dependency if not present.\n"
            "2. Add @Operation, @ApiResponse, @Schema annotations to controllers.\n"
            "3. Document request/response models with @Schema descriptions.\n"
            "4. Add example values for common request payloads.\n"
            "5. Document error responses (400, 401, 403, 404, 500) with schemas.\n"
            "6. Configure Swagger UI path and info metadata.\n"
            "7. Add README documentation for API usage."
        ),
    ),
    MigrationRecipe(
        id="error_handling",
        name="Error Handling & Resilience",
        category="quality",
        description="Implement consistent error handling patterns. Adds global exception handlers, "
                    "structured error responses, retry policies, and circuit breakers.",
        priority=60,
        tags=["error-handling", "exceptions", "resilience", "retry", "circuit-breaker"],
        prerequisites=[],
        agent_instructions=(
            "1. Add @ControllerAdvice global exception handler if missing.\n"
            "2. Define standard error response DTO (code, message, details, timestamp).\n"
            "3. Map domain exceptions to appropriate HTTP status codes.\n"
            "4. Add input validation with @Valid and ConstraintViolation handling.\n"
            "5. Add retry policies for transient failures (database, HTTP).\n"
            "6. Add circuit breaker for downstream service calls (Resilience4j).\n"
            "7. Add structured logging for exceptions with correlation IDs."
        ),
    ),
]

# Index for O(1) lookup
_RECIPE_MAP: dict[str, MigrationRecipe] = {r.id: r for r in RECIPES}


def get_recipe(recipe_id: str) -> Optional[MigrationRecipe]:
    """Get a single recipe by ID."""
    return _RECIPE_MAP.get(recipe_id)


def get_all_recipes() -> list[MigrationRecipe]:
    """Return all available recipes."""
    return list(RECIPES)


def get_recipes_by_category() -> dict[str, list[MigrationRecipe]]:
    """Group recipes by category for UI display."""
    groups: dict[str, list[MigrationRecipe]] = {}
    for recipe in RECIPES:
        groups.setdefault(recipe.category, []).append(recipe)
    return groups


def get_applicable_recipes(
    source_profile: dict,
    reference_profile: dict,
    gap_analysis: dict,
    improvement_analysis: dict | None = None,
) -> list[MigrationRecipe]:
    """Filter recipes to those relevant based on detected gaps and improvement analysis.

    Returns recipes where the gap analysis or improvement analysis indicates work is needed.
    """
    if not gap_analysis and not improvement_analysis:
        return list(RECIPES)  # no analysis yet — return all

    categories_with_gaps = set(gap_analysis.get("categories_with_gaps", []))
    applicable = []

    # Category → recipe category mapping
    _gap_to_recipe = {
        "technology": ["java", "dependencies"],
        "dependencies": ["dependencies", "java"],
        "k8s": ["k8s"],
        "docker": ["docker"],
        "config": ["config"],
        "cicd": ["cicd"],
        "observability": ["observability"],
        "security": ["security"],
        # Improvement-mode gap categories
        "testing": ["testing"],
        "test_coverage": ["testing"],
        "code_quality": ["quality"],
        "performance": ["quality"],
        "structure": ["quality"],
        "error_handling": ["quality"],
        "api_documentation": ["quality"],
        # Database-mode gap categories
        "database_tables": ["database"],
        "database_columns": ["database"],
        "database_indexes": ["database"],
        "database_types": ["database"],
        "database_views": ["database"],
        "database_constraints": ["database"],
        "database_collections": ["database"],
        "database_nosql": ["database"],
    }

    # Collect recipe categories that have gaps
    recipe_categories: set[str] = set()
    for gap_cat in categories_with_gaps:
        for rc in _gap_to_recipe.get(gap_cat, []):
            recipe_categories.add(rc)

    # Add categories from improvement analysis
    if improvement_analysis:
        for area in improvement_analysis.get("areas_needing_improvement", []):
            for rc in _gap_to_recipe.get(area, []):
                recipe_categories.add(rc)

    if not recipe_categories:
        return list(RECIPES)  # can't determine — return all

    for recipe in RECIPES:
        if recipe.category in recipe_categories:
            applicable.append(recipe)

    return applicable
