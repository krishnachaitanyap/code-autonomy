"""
Static-analysis technology stack analyzer.

Deeply inspects a project's dependencies, code patterns, and config files
to build a rich StackProfile — used to generate org-specific SKILLS.md content
that LLMs cannot infer from training data alone.

No LLM calls — pure static analysis using stdlib XML, regex, JSON, and YAML.
"""

import json
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from src.constants import SKIP_DIRS

# ---------------------------------------------------------------------------
# StackProfile dataclass
# ---------------------------------------------------------------------------

@dataclass
class StackProfile:
    app_type: str = "service"                           # middleware, web-frontend, batch, library, microservice, service
    technologies: dict = field(default_factory=dict)     # category → [techs]
    api_endpoints: list = field(default_factory=list)    # [{"class", "method", "path", "http_method"}]
    messaging: list = field(default_factory=list)        # [{"type", "topic", "group", "direction"}]
    data_stores: list = field(default_factory=list)      # [{"type", "entities", "url_pattern"}]
    downstream_services: list = field(default_factory=list)  # [{"name", "client_type", "url"}]
    config_sources: list = field(default_factory=list)   # [{"type", "key_prefix", "source"}]
    k8s_resources: list = field(default_factory=list)    # [{"kind", "name", "replicas", "image"}]
    observability: list = field(default_factory=list)    # [{"type", "detail"}]
    config_properties: dict = field(default_factory=dict)  # key → value for important properties
    dependencies: list = field(default_factory=list)      # [{"group", "artifact", "version", "category"}]


# ---------------------------------------------------------------------------
# Dependency → Technology mapping tables
# ---------------------------------------------------------------------------

_MAVEN_TECH_MAP = {
    # --- API Layer ---
    "spring-boot-starter-web":        ("api", "REST (Spring MVC)"),
    "spring-boot-starter-webflux":    ("api", "Reactive REST (WebFlux)"),
    "spring-boot-starter-jersey":     ("api", "REST (JAX-RS / Jersey)"),
    "spring-ws-core":                 ("api", "SOAP (Spring WS)"),
    "cxf-spring-boot-starter-jaxws":  ("api", "SOAP (Apache CXF)"),
    "springdoc-openapi":              ("api", "OpenAPI/Swagger"),
    "spring-boot-starter-graphql":    ("api", "GraphQL"),
    "grpc-spring-boot-starter":       ("api", "gRPC"),
    # --- Messaging ---
    "spring-kafka":                   ("messaging", "Kafka (Spring Kafka)"),
    "spring-boot-starter-activemq":   ("messaging", "ActiveMQ (JMS)"),
    "spring-boot-starter-amqp":       ("messaging", "RabbitMQ (AMQP)"),
    "spring-cloud-stream":            ("messaging", "Spring Cloud Stream"),
    # --- Cache ---
    "spring-boot-starter-cache":      ("cache", "Spring Cache Abstraction"),
    "spring-boot-starter-data-redis": ("cache", "Redis"),
    "redisson":                       ("cache", "Redis (Redisson)"),
    "hazelcast":                      ("cache", "Hazelcast"),
    "caffeine":                       ("cache", "Caffeine (local cache)"),
    "ehcache":                        ("cache", "Ehcache"),
    # --- Database ---
    "spring-boot-starter-data-jpa":   ("database", "JPA / Hibernate"),
    "spring-boot-starter-jdbc":       ("database", "JDBC (Spring JdbcTemplate)"),
    "mybatis-spring-boot-starter":    ("database", "MyBatis"),
    "spring-boot-starter-data-mongodb": ("database", "MongoDB"),
    "spring-boot-starter-data-cassandra": ("database", "Cassandra"),
    "spring-boot-starter-data-r2dbc": ("database", "R2DBC (reactive DB)"),
    "ojdbc":                          ("database", "Oracle JDBC"),
    "postgresql":                     ("database", "PostgreSQL"),
    "mysql-connector":                ("database", "MySQL"),
    "mssql-jdbc":                     ("database", "SQL Server"),
    "HikariCP":                       ("database", "HikariCP connection pool"),
    "flyway":                         ("database", "Flyway migrations"),
    "liquibase":                      ("database", "Liquibase migrations"),
    # --- HTTP Clients ---
    "spring-cloud-starter-openfeign": ("http_client", "Feign (declarative HTTP)"),
    "resilience4j":                   ("http_client", "Resilience4j (circuit breaker)"),
    "spring-cloud-starter-circuitbreaker": ("http_client", "Spring Circuit Breaker"),
    "spring-retry":                   ("http_client", "Spring Retry"),
    # --- Observability ---
    "micrometer-core":                ("observability", "Micrometer metrics"),
    "micrometer-registry-prometheus": ("observability", "Prometheus metrics"),
    "spring-boot-starter-actuator":   ("observability", "Spring Actuator"),
    "opentelemetry":                  ("observability", "OpenTelemetry"),
    "spring-cloud-starter-sleuth":    ("observability", "Distributed tracing (Sleuth)"),
    "zipkin":                         ("observability", "Zipkin tracing"),
    "logback":                        ("observability", "Logback logging"),
    "log4j":                          ("observability", "Log4j logging"),
    # --- Config Management ---
    "spring-cloud-config-client":     ("config", "Spring Cloud Config"),
    "spring-cloud-starter-consul":    ("config", "Consul config"),
    "spring-cloud-starter-vault":     ("config", "HashiCorp Vault"),
    "archaius":                       ("config", "Netflix Archaius"),
    # --- Security ---
    "spring-boot-starter-security":   ("security", "Spring Security"),
    "spring-boot-starter-oauth2":     ("security", "OAuth2"),
    "spring-security-saml2":          ("security", "SAML2"),
    "nimbus-jose-jwt":                ("security", "JWT"),
    # --- Service Discovery ---
    "spring-cloud-starter-eureka":    ("discovery", "Eureka"),
    "spring-cloud-kubernetes":        ("discovery", "K8s service discovery"),
    # --- Batch ---
    "spring-boot-starter-batch":      ("batch", "Spring Batch"),
    "quartz":                         ("batch", "Quartz scheduler"),
}

_NPM_TECH_MAP = {
    # --- API Layer ---
    "express":                        ("api", "Express.js"),
    "fastify":                        ("api", "Fastify"),
    "koa":                            ("api", "Koa"),
    "hapi":                           ("api", "Hapi"),
    "@nestjs/core":                   ("api", "NestJS"),
    "graphql":                        ("api", "GraphQL"),
    "apollo-server":                  ("api", "Apollo GraphQL"),
    "@grpc/grpc-js":                  ("api", "gRPC"),
    "swagger-ui-express":             ("api", "OpenAPI/Swagger"),
    # --- Messaging ---
    "kafkajs":                        ("messaging", "Kafka (KafkaJS)"),
    "amqplib":                        ("messaging", "RabbitMQ (AMQP)"),
    "bull":                           ("messaging", "Bull (Redis queue)"),
    "bullmq":                         ("messaging", "BullMQ (Redis queue)"),
    # --- Cache ---
    "ioredis":                        ("cache", "Redis (ioredis)"),
    "redis":                          ("cache", "Redis"),
    "node-cache":                     ("cache", "Node-Cache (local)"),
    # --- Database ---
    "sequelize":                      ("database", "Sequelize ORM"),
    "typeorm":                        ("database", "TypeORM"),
    "prisma":                         ("database", "Prisma ORM"),
    "@prisma/client":                 ("database", "Prisma ORM"),
    "mongoose":                       ("database", "MongoDB (Mongoose)"),
    "knex":                           ("database", "Knex.js (SQL builder)"),
    "pg":                             ("database", "PostgreSQL"),
    "mysql2":                         ("database", "MySQL"),
    "mongodb":                        ("database", "MongoDB"),
    # --- HTTP Clients ---
    "axios":                          ("http_client", "Axios"),
    "node-fetch":                     ("http_client", "node-fetch"),
    "got":                            ("http_client", "Got"),
    # --- Observability ---
    "prom-client":                    ("observability", "Prometheus metrics"),
    "winston":                        ("observability", "Winston logging"),
    "pino":                           ("observability", "Pino logging"),
    "@opentelemetry/sdk-node":        ("observability", "OpenTelemetry"),
    # --- Security ---
    "passport":                       ("security", "Passport.js"),
    "jsonwebtoken":                   ("security", "JWT"),
    "helmet":                         ("security", "Helmet (HTTP headers)"),
    # --- Frontend ---
    "react":                          ("frontend", "React"),
    "next":                           ("frontend", "Next.js"),
    "vue":                            ("frontend", "Vue.js"),
    "nuxt":                           ("frontend", "Nuxt.js"),
    "@angular/core":                  ("frontend", "Angular"),
    "svelte":                         ("frontend", "Svelte"),
}

_PYTHON_TECH_MAP = {
    # --- API Layer ---
    "flask":                          ("api", "Flask"),
    "django":                         ("api", "Django"),
    "fastapi":                        ("api", "FastAPI"),
    "djangorestframework":            ("api", "Django REST Framework"),
    "django-rest-framework":          ("api", "Django REST Framework"),
    "sanic":                          ("api", "Sanic"),
    "tornado":                        ("api", "Tornado"),
    "grpcio":                         ("api", "gRPC"),
    "graphene":                       ("api", "GraphQL (Graphene)"),
    # --- Messaging ---
    "celery":                         ("messaging", "Celery"),
    "kafka-python":                   ("messaging", "Kafka"),
    "confluent-kafka":                ("messaging", "Kafka (Confluent)"),
    "pika":                           ("messaging", "RabbitMQ (pika)"),
    "kombu":                          ("messaging", "Kombu (messaging)"),
    # --- Cache ---
    "redis":                          ("cache", "Redis"),
    "django-redis":                   ("cache", "Redis (Django)"),
    "cachetools":                     ("cache", "cachetools (local)"),
    # --- Database ---
    "sqlalchemy":                     ("database", "SQLAlchemy"),
    "django":                         ("database", "Django ORM"),
    "tortoise-orm":                   ("database", "Tortoise ORM"),
    "pymongo":                        ("database", "MongoDB (PyMongo)"),
    "psycopg2":                       ("database", "PostgreSQL"),
    "psycopg2-binary":                ("database", "PostgreSQL"),
    "mysqlclient":                    ("database", "MySQL"),
    "alembic":                        ("database", "Alembic migrations"),
    "motor":                          ("database", "MongoDB (async Motor)"),
    # --- HTTP Clients ---
    "requests":                       ("http_client", "Requests"),
    "httpx":                          ("http_client", "HTTPX"),
    "aiohttp":                        ("http_client", "aiohttp"),
    # --- Observability ---
    "prometheus-client":              ("observability", "Prometheus metrics"),
    "opentelemetry-sdk":              ("observability", "OpenTelemetry"),
    "sentry-sdk":                     ("observability", "Sentry"),
    "structlog":                      ("observability", "structlog"),
    # --- Security ---
    "pyjwt":                          ("security", "JWT (PyJWT)"),
    "authlib":                        ("security", "AuthLib (OAuth)"),
    "django-allauth":                 ("security", "Django AllAuth"),
    "python-jose":                    ("security", "JOSE/JWT"),
    # --- Batch ---
    "apscheduler":                    ("batch", "APScheduler"),
    "dramatiq":                       ("batch", "Dramatiq (task queue)"),
}


# ---------------------------------------------------------------------------
# Phase 1: Dependency Analysis
# ---------------------------------------------------------------------------

def _parse_maven_dependencies(repo: Path) -> list[dict]:
    """Parse pom.xml for dependencies. Reuses ET pattern from testing_service."""
    deps = []
    for pom in repo.rglob("pom.xml"):
        if any(skip in pom.parts for skip in SKIP_DIRS):
            continue
        try:
            tree = ET.parse(str(pom))
            root = tree.getroot()
            ns_match = re.match(r'\{(.+?)\}', root.tag)
            ns = {"m": ns_match.group(1)} if ns_match else {}
            prefix = "m:" if ns else ""

            for dep in root.findall(f".//{prefix}dependency", ns):
                group = dep.findtext(f"{prefix}groupId", "", ns)
                artifact = dep.findtext(f"{prefix}artifactId", "", ns)
                version = dep.findtext(f"{prefix}version", "", ns)
                deps.append({
                    "group": group,
                    "artifact": artifact,
                    "version": version or "",
                })
        except Exception:
            continue
    return deps


def _parse_gradle_dependencies(repo: Path) -> list[dict]:
    """Parse build.gradle / build.gradle.kts for dependencies."""
    deps = []
    dep_re = re.compile(
        r"""(?:implementation|compile|api|runtimeOnly|testImplementation)\s*"""
        r"""[\s(]+['"]([^'"]+:[^'"]+(?::[^'"]+)?)['"]""",
    )
    for name in ("build.gradle", "build.gradle.kts"):
        gradle_file = repo / name
        if not gradle_file.is_file():
            continue
        try:
            content = gradle_file.read_text(encoding="utf-8", errors="replace")
            for m in dep_re.finditer(content):
                parts = m.group(1).split(":")
                group = parts[0] if len(parts) > 0 else ""
                artifact = parts[1] if len(parts) > 1 else ""
                version = parts[2] if len(parts) > 2 else ""
                deps.append({"group": group, "artifact": artifact, "version": version})
        except Exception:
            continue
    return deps


def _parse_npm_dependencies(repo: Path) -> list[dict]:
    """Parse package.json for dependencies."""
    deps = []
    pkg_file = repo / "package.json"
    if not pkg_file.is_file():
        return deps
    try:
        data = json.loads(pkg_file.read_text(encoding="utf-8", errors="replace"))
        for section in ("dependencies", "devDependencies"):
            for name, version in (data.get(section) or {}).items():
                deps.append({"group": "", "artifact": name, "version": version})
    except Exception:
        pass
    return deps


def _parse_python_dependencies(repo: Path) -> list[dict]:
    """Parse requirements.txt, setup.py, pyproject.toml for Python deps."""
    deps = []
    # requirements.txt
    for req_file in ("requirements.txt", "requirements-dev.txt", "requirements_dev.txt"):
        rpath = repo / req_file
        if rpath.is_file():
            try:
                for line in rpath.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or line.startswith("-"):
                        continue
                    # Extract package name (before any version specifier)
                    pkg = re.split(r"[>=<!~\[]", line)[0].strip()
                    version_match = re.search(r"[>=<!~]+\s*([\d][^\s,;]*)", line)
                    version = version_match.group(1) if version_match else ""
                    if pkg:
                        deps.append({"group": "", "artifact": pkg.lower(), "version": version})
            except Exception:
                continue

    # pyproject.toml — simple regex extraction
    pyproject = repo / "pyproject.toml"
    if pyproject.is_file():
        try:
            content = pyproject.read_text(encoding="utf-8", errors="replace")
            # Match dependencies = ["pkg>=1.0", ...]
            in_deps = False
            for line in content.splitlines():
                if re.match(r"^dependencies\s*=\s*\[", line):
                    in_deps = True
                if in_deps:
                    for m in re.finditer(r'"([^"]+)"', line):
                        pkg = re.split(r"[>=<!~\[]", m.group(1))[0].strip()
                        if pkg:
                            deps.append({"group": "", "artifact": pkg.lower(), "version": ""})
                    if "]" in line:
                        in_deps = False
        except Exception:
            pass

    return deps


def _map_dependencies(deps: list[dict], lang: str) -> tuple[dict, list[dict]]:
    """Map raw dependencies to technology categories.

    Returns (technologies dict, enriched deps list with category).
    """
    if lang == "java":
        tech_map = _MAVEN_TECH_MAP
    elif lang in ("javascript", "typescript"):
        tech_map = _NPM_TECH_MAP
    elif lang == "python":
        tech_map = _PYTHON_TECH_MAP
    else:
        tech_map = {}

    technologies: dict[str, list[str]] = {}
    enriched = []

    for dep in deps:
        artifact = dep.get("artifact", "")
        category = ""
        # Try exact match first, then substring match
        for key, (cat, tech_name) in tech_map.items():
            if key == artifact or key in artifact:
                technologies.setdefault(cat, [])
                if tech_name not in technologies[cat]:
                    technologies[cat].append(tech_name)
                category = cat
                break
        enriched.append({**dep, "category": category})

    # GroupId-based detection: JISI framework
    for dep in deps:
        if dep.get("group") == "com.chase.wasgwsframework":
            technologies.setdefault("framework", [])
            if "JISI (WAS GWS)" not in technologies["framework"]:
                technologies["framework"].append("JISI (WAS GWS)")
            break

    return technologies, enriched


# ---------------------------------------------------------------------------
# Phase 2: Code Pattern Scanning
# ---------------------------------------------------------------------------

# Java/Kotlin patterns
_PATTERN_REST_CONTROLLER = re.compile(
    r"@(RestController|RequestMapping|GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping)"
    r"(?:\(([^)]*)\))?"
)
_PATTERN_SOAP = re.compile(r"@(WebService|WebMethod|SOAPBinding)\s*(?:\(([^)]*)\))?")
_PATTERN_KAFKA = re.compile(
    r"@(KafkaListener|SendTo)\s*\(([^)]*)\)|KafkaTemplate"
)
_PATTERN_CACHE = re.compile(
    r"@(Cacheable|CacheEvict|CachePut)\s*\(([^)]*)\)|CacheManager"
)
_PATTERN_ENTITY = re.compile(r"@(Entity|Table)\s*(?:\(([^)]*)\))?")
_PATTERN_REPOSITORY = re.compile(r"(?:extends|implements)\s+(?:\w+)?Repository\b")
_PATTERN_FEIGN = re.compile(r"@FeignClient\s*\(([^)]*)\)")
_PATTERN_CONFIG = re.compile(r"@(RefreshScope|ConfigurationProperties)\s*(?:\(([^)]*)\))?")
_PATTERN_OBSERVABILITY = re.compile(r"@(Timed|Counted|Traced)\s*(?:\(([^)]*)\))?|MeterRegistry")
_PATTERN_CIRCUIT_BREAKER = re.compile(r"@(CircuitBreaker|Retry|RateLimiter)\s*(?:\(([^)]*)\))?")

# Enterprise REST proxy patterns (RESTProxy.getInstance / ChannelUtil.getChannelProperty)
_PATTERN_REST_PROXY = re.compile(
    r"RESTProxy\s*\.\s*getInstance\s*\(\s*(\w+)\s*\)",
)
_PATTERN_CHANNEL_PROPERTY = re.compile(
    r"ChannelUtil\s*\.\s*getChannelProperty\s*\(\s*(\w+)\s*\)",
)
# Constant definitions that hold property key prefixes (e.g. static final String FOO = "gws.mms.qp.token.delete.svc.rest.url")
_PATTERN_CONSTANT_DEF = re.compile(
    r"""(?:static\s+final|final\s+static)\s+String\s+(\w+)\s*=\s*["']([^"']+)["']""",
)

# Python patterns
_PATTERN_PY_ROUTE = re.compile(r"@\w+\.(route|get|post|put|delete|patch)\s*\(\s*['\"]([^'\"]+)['\"]")
_PATTERN_PY_MODEL = re.compile(r"class\s+(\w+)\s*\(.*(?:Model|Base|db\.Model)\s*\)")
_PATTERN_PY_CELERY_TASK = re.compile(r"@(?:shared_task|app\.task|celery\.task)")

# JS/TS patterns for frontend API calls
_PATTERN_JS_FETCH = re.compile(r"""fetch\s*\(\s*[`'"](/[^`'"]+)[`'"]""")
_PATTERN_JS_AXIOS = re.compile(r"""axios\s*\.\s*(get|post|put|delete|patch)\s*\(\s*[`'"](/[^`'"]+)[`'"]""", re.IGNORECASE)
_PATTERN_JS_HTTP_CLIENT = re.compile(r"""(?:this\s*\.\s*)?http\s*\.\s*(get|post|put|delete|patch)\s*(?:<[^>]+>)?\s*\(\s*[`'"](/[^`'"]+)[`'"]""", re.IGNORECASE)
_PATTERN_JS_COMPONENT = re.compile(r"(?:export\s+(?:default\s+)?)?(?:function|class)\s+(\w+)")

# Extract annotation parameter value
_PARAM_VALUE_RE = re.compile(r"""(?:value|topics?|name)\s*=\s*["']([^"']+)["']""")
_SIMPLE_VALUE_RE = re.compile(r"""["']([^"']+)["']""")

# Class name detection
_CLASS_NAME_RE = re.compile(r"(?:public\s+)?(?:class|interface)\s+(\w+)")
_METHOD_NAME_RE = re.compile(r"(?:public|private|protected)\s+\S+\s+(\w+)\s*\(")


def _extract_param(annotation_args: str) -> str:
    """Extract the primary parameter value from annotation arguments."""
    if not annotation_args:
        return ""
    m = _PARAM_VALUE_RE.search(annotation_args)
    if m:
        return m.group(1)
    m = _SIMPLE_VALUE_RE.search(annotation_args)
    if m:
        return m.group(1)
    return ""


def _property_key_to_service_name(prop_key: str) -> str:
    """Convert a property key like 'gws.mms.qp.token.delete.svc.rest.url' to a
    readable service name like 'mms-qp-token-delete'.

    Strips common prefixes (gws.) and suffixes (.svc.rest.url, .host, .baseurl, .protocol).
    """
    name = prop_key
    # Strip common prefixes
    for prefix in ("gws.", "app.", "service.", "com.", "org."):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    # Strip common suffixes
    for suffix in (".svc.rest.url", ".rest.url", ".svc.url", ".url",
                   ".host", ".baseurl", ".protocol", ".port", ".endpoint"):
        if name.endswith(suffix):
            name = name[:-len(suffix)]
            break
    # Convert dots to hyphens for readability
    name = name.replace(".", "-")
    return name or prop_key


def _scan_java_patterns(content: str, rel_path: str, profile: StackProfile,
                        global_constants: dict[str, str] | None = None) -> None:
    """Scan a Java/Kotlin file for technology patterns."""
    # Detect class name for context
    class_match = _CLASS_NAME_RE.search(content)
    class_name = class_match.group(1) if class_match else Path(rel_path).stem

    # REST endpoints
    for m in _PATTERN_REST_CONTROLLER.finditer(content):
        annotation = m.group(1)
        path = _extract_param(m.group(2)) if m.group(2) else ""
        http_method_map = {
            "GetMapping": "GET", "PostMapping": "POST",
            "PutMapping": "PUT", "DeleteMapping": "DELETE",
            "PatchMapping": "PATCH", "RequestMapping": "REQUEST",
        }
        http_method = http_method_map.get(annotation, "")
        if http_method and path:
            profile.api_endpoints.append({
                "class": class_name, "method": "", "path": path,
                "http_method": http_method,
            })
        elif annotation == "RestController":
            profile.api_endpoints.append({
                "class": class_name, "method": "", "path": "",
                "http_method": "CONTROLLER",
            })

    # Kafka
    for m in _PATTERN_KAFKA.finditer(content):
        if m.group(1) == "KafkaListener":
            topic = _extract_param(m.group(2))
            group_match = re.search(r"""groupId\s*=\s*["']([^"']+)["']""", m.group(2) or "")
            group = group_match.group(1) if group_match else ""
            profile.messaging.append({
                "type": "Kafka", "topic": topic, "group": group,
                "direction": "consumer",
                "source_file": rel_path, "source_class": class_name,
            })
        elif m.group(1) == "SendTo":
            topic = _extract_param(m.group(2))
            profile.messaging.append({
                "type": "Kafka", "topic": topic, "group": "",
                "direction": "producer",
                "source_file": rel_path, "source_class": class_name,
            })
        else:
            # KafkaTemplate usage
            profile.messaging.append({
                "type": "Kafka", "topic": "", "group": "",
                "direction": "producer",
                "source_file": rel_path, "source_class": class_name,
            })

    # Cache
    for m in _PATTERN_CACHE.finditer(content):
        if m.group(1):
            cache_name = _extract_param(m.group(2)) if m.group(2) else ""
            profile.observability.append({"type": "cache", "detail": f"@{m.group(1)}({cache_name})"})

    # Entities
    for m in _PATTERN_ENTITY.finditer(content):
        table_name = _extract_param(m.group(2)) if m.group(2) else ""
        profile.data_stores.append({
            "type": "entity", "entities": [class_name],
            "url_pattern": table_name,
            "source_file": rel_path, "source_class": class_name,
        })

    # Repository interfaces (extends *Repository<Entity, ...>)
    if _PATTERN_REPOSITORY.search(content):
        # Extract the entity type from generic parameter: Repository<EntityName, ...>
        repo_generic = re.search(r"Repository\s*<\s*(\w+)", content)
        if repo_generic:
            entity_name = repo_generic.group(1)
            profile.data_stores.append({
                "type": "repository", "entities": [entity_name],
                "url_pattern": "",
                "source_file": rel_path, "source_class": class_name,
            })

    # Repository usage in controllers/services (field injection of FooRepository)
    if not _PATTERN_REPOSITORY.search(content):
        for repo_usage in re.finditer(r"(\w+)Repository\b", content):
            entity_name = repo_usage.group(1)
            if entity_name[0].isupper():
                profile.data_stores.append({
                    "type": "usage", "entities": [entity_name],
                    "url_pattern": "",
                    "source_file": rel_path, "source_class": class_name,
                })
                break  # one per file

    # Feign clients
    for m in _PATTERN_FEIGN.finditer(content):
        service_name = _extract_param(m.group(1))
        url_match = re.search(r"""url\s*=\s*["']([^"']+)["']""", m.group(1))
        url = url_match.group(1) if url_match else ""
        profile.downstream_services.append({
            "name": service_name or class_name, "client_type": "Feign",
            "url": url, "source_file": rel_path, "source_class": class_name,
        })

    # Config
    for m in _PATTERN_CONFIG.finditer(content):
        if m.group(1) == "RefreshScope":
            profile.config_sources.append({
                "type": "RefreshScope", "key_prefix": "",
                "source": class_name,
            })
        elif m.group(1) == "ConfigurationProperties":
            prefix = _extract_param(m.group(2)) if m.group(2) else ""
            profile.config_sources.append({
                "type": "ConfigurationProperties", "key_prefix": prefix,
                "source": class_name,
            })

    # Observability annotations
    for m in _PATTERN_OBSERVABILITY.finditer(content):
        if m.group(1):
            detail = _extract_param(m.group(2)) if m.group(2) else ""
            profile.observability.append({"type": m.group(1), "detail": detail})

    # Circuit breaker
    for m in _PATTERN_CIRCUIT_BREAKER.finditer(content):
        if m.group(1):
            name = _extract_param(m.group(2)) if m.group(2) else ""
            profile.observability.append({"type": m.group(1), "detail": name})

    # SOAP web services
    for m in _PATTERN_SOAP.finditer(content):
        annotation = m.group(1)
        args = m.group(2) or ""
        if annotation == "WebService":
            service_name = _extract_param(args) or class_name
            # Look for WSDL location in annotation args
            wsdl_match = re.search(r"""(?:wsdlLocation|targetNamespace)\s*=\s*["']([^"']+)["']""", args)
            wsdl_url = wsdl_match.group(1) if wsdl_match else ""
            profile.downstream_services.append({
                "name": service_name,
                "client_type": "SOAP",
                "url": wsdl_url,
                "source_file": rel_path, "source_class": class_name,
            })
        elif annotation == "WebMethod":
            method_name = _extract_param(args) or ""
            # Find the Java method name if annotation param is empty
            if not method_name:
                # Look for the method following @WebMethod
                method_after = re.search(
                    r"@WebMethod[^}]*?(?:public|protected)\s+\S+\s+(\w+)\s*\(",
                    content[m.start():],
                )
                method_name = method_after.group(1) if method_after else "unknown"
            profile.api_endpoints.append({
                "class": class_name, "method": method_name,
                "path": f"SOAP:{method_name}",
                "http_method": "SOAP",
            })

    # Enterprise REST proxy pattern: RESTProxy.getInstance(service).invoke(...)
    # Build constant → value map: local file constants + global constants from all files
    constants = dict(global_constants or {})  # start with global
    for m in _PATTERN_CONSTANT_DEF.finditer(content):
        constants[m.group(1)] = m.group(2)  # local overrides global

    # Build local variable → constant map for ChannelUtil.getChannelProperty(CONST) assignments
    # e.g. "String service = ChannelUtil.getChannelProperty(MMS_QP_DELETE_TOKEN_REST_SERVICE_URL);"
    # maps local var "service" → constant name "MMS_QP_DELETE_TOKEN_REST_SERVICE_URL"
    channel_prop_locals: dict[str, str] = {}
    for m in re.finditer(
        r"(?:String|var)\s+(\w+)\s*=\s*ChannelUtil\s*\.\s*getChannelProperty\s*\(\s*(\w+)\s*\)",
        content,
    ):
        local_var = m.group(1)
        const_name = m.group(2)
        channel_prop_locals[local_var] = const_name

    for m in _PATTERN_REST_PROXY.finditer(content):
        service_var = m.group(1)
        # Resolution chain: local var → ChannelProperty constant → string value
        # 1. Check if it's a local var assigned from ChannelUtil.getChannelProperty()
        if service_var in channel_prop_locals:
            const_name = channel_prop_locals[service_var]
            service_name = constants.get(const_name, const_name)
        else:
            # 2. Direct constant reference
            service_name = constants.get(service_var, service_var)
        # Clean up: extract a readable service name from property key
        # e.g. "gws.mms.qp.token.delete.svc.rest.url" → "mms-qp-token-delete"
        readable = _property_key_to_service_name(service_name)
        profile.downstream_services.append({
            "name": readable,
            "client_type": "RESTProxy",
            "url": service_name if service_name != service_var else "",
            "source_file": rel_path, "source_class": class_name,
        })

    # ChannelUtil.getChannelProperty(CONSTANT) — additional downstream signal
    # Capture both direct constant usage and local-var-assigned patterns
    channel_prop_constants = set()
    for m in _PATTERN_CHANNEL_PROPERTY.finditer(content):
        prop_var = m.group(1)
        prop_key = constants.get(prop_var, prop_var)
        channel_prop_constants.add(prop_key)

    # Also include constants resolved via local var assignments
    for const_name in channel_prop_locals.values():
        prop_key = constants.get(const_name, const_name)
        channel_prop_constants.add(prop_key)

    existing = {s["name"] for s in profile.downstream_services}
    for prop_key in channel_prop_constants:
        if prop_key != prop_key.upper() or "." in prop_key:  # resolved to actual property key (not just a raw constant name)
            readable = _property_key_to_service_name(prop_key)
            if readable not in existing:
                existing.add(readable)
                profile.downstream_services.append({
                    "name": readable,
                    "client_type": "ChannelProperty",
                    "url": prop_key,
                    "source_file": rel_path, "source_class": class_name,
                })


def _scan_python_patterns(content: str, rel_path: str, profile: StackProfile) -> None:
    """Scan a Python file for technology patterns."""
    module_name = Path(rel_path).stem

    # Flask/FastAPI routes
    for m in _PATTERN_PY_ROUTE.finditer(content):
        http_method = m.group(1).upper()
        if http_method == "ROUTE":
            http_method = "GET"
        path = m.group(2)
        profile.api_endpoints.append({
            "class": module_name, "method": "", "path": path,
            "http_method": http_method,
        })

    # SQLAlchemy/Django models
    for m in _PATTERN_PY_MODEL.finditer(content):
        model_name = m.group(1)
        profile.data_stores.append({
            "type": "model", "entities": [model_name], "url_pattern": "",
            "source_file": rel_path, "source_class": module_name,
        })

    # Celery tasks
    for m in _PATTERN_PY_CELERY_TASK.finditer(content):
        profile.messaging.append({
            "type": "Celery", "topic": "", "group": "",
            "direction": "task",
            "source_file": rel_path, "source_class": module_name,
        })


def _scan_js_ts_patterns(content: str, rel_path: str, profile: StackProfile) -> None:
    """Scan a JS/TS file for frontend API call patterns (fetch, axios, HttpClient)."""
    # Detect component/class name
    comp_match = _PATTERN_JS_COMPONENT.search(content)
    component_name = comp_match.group(1) if comp_match else Path(rel_path).stem

    # Collect (method, path) tuples from all patterns
    api_calls: set[tuple[str, str]] = set()
    for m in _PATTERN_JS_FETCH.finditer(content):
        api_calls.add(("FETCH", m.group(1)))
    for m in _PATTERN_JS_AXIOS.finditer(content):
        api_calls.add((m.group(1).upper(), m.group(2)))
    for m in _PATTERN_JS_HTTP_CLIENT.finditer(content):
        api_calls.add((m.group(1).upper(), m.group(2)))

    for method, path in api_calls:
        profile.downstream_services.append({
            "name": f"API:{path}",
            "client_type": "Frontend",
            "url": path,
            "source_file": rel_path, "source_class": component_name,
        })


def _build_global_constants(code_files: list) -> dict[str, str]:
    """First pass: collect all static final String constants across Java files.

    Returns a map of constant_name → string_value, e.g.
    {"MMS_QP_DELETE_TOKEN_REST_SERVICE_URL": "gws.mms.qp.token.delete.svc.rest.url"}
    """
    global_constants: dict[str, str] = {}
    for rel_path, fpath in code_files:
        if not rel_path.endswith((".java", ".kt")):
            continue
        try:
            content = fpath.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for m in _PATTERN_CONSTANT_DEF.finditer(content):
            global_constants[m.group(1)] = m.group(2)
    return global_constants


def _scan_with_code_index(
    repo_path: str, config: dict, profile: StackProfile
) -> bool:
    """Use CodeIndex call graph to detect downstream dependencies.

    Leverages the cached dependency graph, symbol table, property index,
    and class hierarchy to resolve cross-file call chains that regex cannot
    follow (e.g. RESTProxy.getInstance(localVar) where localVar comes from
    ChannelUtil.getChannelProperty(CONSTANT) defined in another file).

    Returns True if successful, False to fall back to regex.
    """
    try:
        from src.code_index.storage import build_or_load_code_index
        code_index = build_or_load_code_index(repo_path, config)
    except Exception:
        return False

    graph = code_index.dependency_graph
    symbols = code_index.symbol_table
    props = code_index.property_index
    hierarchy = code_index.class_hierarchy

    found_any = False

    # --- 1. Downstream services via HTTP client patterns ---
    # Search for methods on known HTTP client classes
    http_client_classes = (
        "RESTProxy", "RestTemplate", "WebClient", "FeignClient",
        "HttpClient", "ChannelUtil",
    )
    http_method_names = (
        "getInstance", "getForObject", "getForEntity", "postForObject",
        "postForEntity", "exchange", "execute", "invoke", "send",
        "getChannelProperty", "get", "post", "put", "delete",
    )

    for class_name in http_client_classes:
        class_symbols = symbols.get_by_name(class_name)
        for sym in class_symbols:
            # Find all callers of this class's methods via reverse graph
            callers = graph.get_callers(sym.fqn)
            for caller_fqn in callers:
                caller_sym = symbols.get_by_fqn(caller_fqn)
                caller_file = caller_fqn.split("::")[0] if "::" in caller_fqn else ""
                caller_class = ""
                if caller_sym and caller_sym.parent_class:
                    parent = symbols.get_by_fqn(caller_sym.parent_class)
                    caller_class = parent.name if parent else ""
                elif caller_sym:
                    caller_class = caller_sym.name

                profile.downstream_services.append({
                    "name": f"{class_name} (via {caller_class or caller_file})",
                    "client_type": class_name,
                    "url": "",
                    "source_file": caller_file,
                    "source_class": caller_class,
                })
                found_any = True

        # Also search for methods that might be on these classes
        for method_name in http_method_names:
            method_symbols = symbols.get_by_name(method_name)
            for msym in method_symbols:
                # Check if this method belongs to one of our HTTP client classes
                if msym.parent_class:
                    parent = symbols.get_by_fqn(msym.parent_class)
                    if parent and parent.name == class_name:
                        callers = graph.get_callers(msym.fqn)
                        for caller_fqn in callers:
                            caller_sym = symbols.get_by_fqn(caller_fqn)
                            caller_file = caller_fqn.split("::")[0] if "::" in caller_fqn else ""
                            caller_class = ""
                            if caller_sym and caller_sym.parent_class:
                                p = symbols.get_by_fqn(caller_sym.parent_class)
                                caller_class = p.name if p else ""
                            elif caller_sym:
                                caller_class = caller_sym.name

                            profile.downstream_services.append({
                                "name": f"{class_name}.{method_name} (via {caller_class or caller_file})",
                                "client_type": class_name,
                                "url": "",
                                "source_file": caller_file,
                                "source_class": caller_class,
                            })
                            found_any = True

    # Resolve RESTProxy chains via property index:
    # RESTProxy.getInstance(var) → var = ChannelUtil.getChannelProperty(CONST) → props.lookup(CONST)
    rest_proxy_props = props.lookup_fuzzy(r"\.svc\.rest\.url$|\.rest\.url$|\.svc\.url$")
    for prop_key, entries in rest_proxy_props.items():
        readable = _property_key_to_service_name(prop_key)
        existing = {s["name"] for s in profile.downstream_services}
        if readable not in existing:
            source_file = entries[0][0] if entries else ""
            profile.downstream_services.append({
                "name": readable,
                "client_type": "RESTProxy (code-index)",
                "url": prop_key,
                "source_file": source_file,
                "source_class": "",
            })
            found_any = True

    # --- 2. Data stores via Repository interfaces and @Entity ---
    # Find classes extending *Repository via class hierarchy
    class_entries = symbols.get_by_type("class")
    for entry in class_entries:
        if not entry.bases:
            continue

        # Check if any base class contains "Repository"
        for base in entry.bases:
            if "Repository" in base:
                # This is a Repository interface — find the entity type from its name
                entity_name = entry.name.replace("Repository", "")
                if entity_name:
                    # Find who uses this repository via reverse graph
                    callers = graph.get_callers(entry.fqn)
                    source_classes = []
                    source_files = []
                    for caller_fqn in callers:
                        caller_file = caller_fqn.split("::")[0] if "::" in caller_fqn else ""
                        caller_sym = symbols.get_by_fqn(caller_fqn)
                        if caller_file and caller_file not in source_files:
                            source_files.append(caller_file)
                        if caller_sym:
                            cname = caller_sym.name
                            if caller_sym.parent_class:
                                p = symbols.get_by_fqn(caller_sym.parent_class)
                                cname = p.name if p else cname
                            if cname not in source_classes:
                                source_classes.append(cname)

                    profile.data_stores.append({
                        "type": "repository",
                        "entities": [entity_name],
                        "url_pattern": "",
                        "source_file": entry.file_path,
                        "source_class": entry.name,
                    })
                    found_any = True
                break

        # Check for @Entity / @Table annotations
        if any(d in ("Entity", "Table") for d in entry.decorators):
            profile.data_stores.append({
                "type": "entity",
                "entities": [entry.name],
                "url_pattern": "",
                "source_file": entry.file_path,
                "source_class": entry.name,
            })
            found_any = True

    # --- 3. Messaging via Kafka/JMS annotations ---
    # Search property index for Kafka-related annotations
    for annotation_name in ("KafkaListener", "SendTo", "JmsListener"):
        annotation_entries = props.lookup(annotation_name)
        for file_path, line, snippet in annotation_entries:
            # Extract topic from snippet if possible
            topic_match = re.search(r"""(?:topics?|value|destination)\s*=\s*["']([^"']+)["']""", snippet)
            topic = topic_match.group(1) if topic_match else ""

            direction = "consumer" if annotation_name in ("KafkaListener", "JmsListener") else "producer"
            msg_type = "Kafka" if "Kafka" in annotation_name else "JMS"

            # Find the class containing this annotation
            file_symbols = symbols.get_by_file(file_path)
            source_class = ""
            for sym in file_symbols:
                if annotation_name in sym.decorators:
                    source_class = sym.name
                    if sym.parent_class:
                        p = symbols.get_by_fqn(sym.parent_class)
                        source_class = p.name if p else source_class
                    break

            profile.messaging.append({
                "type": msg_type,
                "topic": topic,
                "group": "",
                "direction": direction,
                "source_file": file_path,
                "source_class": source_class,
            })
            found_any = True

    # Search for KafkaTemplate usage in symbol table
    kafka_template_symbols = symbols.get_by_name("KafkaTemplate")
    for kt_sym in kafka_template_symbols:
        callers = graph.get_callers(kt_sym.fqn)
        for caller_fqn in callers:
            caller_file = caller_fqn.split("::")[0] if "::" in caller_fqn else ""
            caller_sym = symbols.get_by_fqn(caller_fqn)
            caller_class = ""
            if caller_sym and caller_sym.parent_class:
                p = symbols.get_by_fqn(caller_sym.parent_class)
                caller_class = p.name if p else ""
            elif caller_sym:
                caller_class = caller_sym.name

            profile.messaging.append({
                "type": "Kafka",
                "topic": "",
                "group": "",
                "direction": "producer",
                "source_file": caller_file,
                "source_class": caller_class,
            })
            found_any = True

    # --- 4. API endpoints via annotations ---
    # Search for Spring mapping annotations in the symbol table
    mapping_annotations = {
        "GetMapping": "GET", "PostMapping": "POST",
        "PutMapping": "PUT", "DeleteMapping": "DELETE",
        "PatchMapping": "PATCH", "RequestMapping": "REQUEST",
        "RestController": "CONTROLLER",
    }

    for entry in symbols.all_entries:
        if not entry.decorators:
            continue
        for decorator in entry.decorators:
            if decorator in mapping_annotations:
                http_method = mapping_annotations[decorator]
                # Extract path from the signature/snippet
                path = ""
                # Try property index for the annotation value
                for prop_entry in props.lookup(decorator):
                    if prop_entry[0] == entry.file_path:
                        path_match = re.search(r"""["']([^"']+)["']""", prop_entry[2])
                        if path_match:
                            path = path_match.group(1)
                        break

                parent_class = ""
                if entry.parent_class:
                    p = symbols.get_by_fqn(entry.parent_class)
                    parent_class = p.name if p else ""
                else:
                    parent_class = entry.name

                profile.api_endpoints.append({
                    "class": parent_class or entry.name,
                    "method": entry.name if entry.symbol_type == "method" else "",
                    "path": path,
                    "http_method": http_method,
                })
                found_any = True

    return found_any


def _scan_code_patterns(repo: Path, code_files: list, profile: StackProfile,
                        config: dict | None = None) -> None:
    """Phase 2: Scan code files for technology patterns.

    Tries CodeIndex-based analysis first (uses cached call graph for
    cross-file resolution), then falls back to regex scanning.
    """
    # Try CodeIndex-based analysis first (uses cached call graph)
    if config:
        success = _scan_with_code_index(str(repo), config, profile)
        if success:
            return

    # Fallback: existing regex scanning
    # First pass: build global constant map across all Java files
    global_constants = _build_global_constants(code_files)

    for rel_path, fpath in code_files:
        try:
            content = fpath.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        if rel_path.endswith((".java", ".kt")):
            _scan_java_patterns(content, rel_path, profile, global_constants)
        elif rel_path.endswith(".py"):
            _scan_python_patterns(content, rel_path, profile)
        elif rel_path.endswith((".js", ".ts", ".jsx", ".tsx")):
            _scan_js_ts_patterns(content, rel_path, profile)


# ---------------------------------------------------------------------------
# Phase 3: Config File Analysis
# ---------------------------------------------------------------------------

_CONFIG_KEY_TECH = {
    "spring.datasource":       ("database", "Database connection"),
    "spring.jpa":              ("database", "JPA config"),
    "spring.kafka":            ("messaging", "Kafka"),
    "spring.redis":            ("cache", "Redis"),
    "spring.cache":            ("cache", "Cache config"),
    "spring.cloud.config":     ("config", "Spring Cloud Config"),
    "management.endpoints":    ("observability", "Actuator endpoints"),
    "server.port":             ("config", "Service port"),
    "eureka.client":           ("discovery", "Eureka"),
    "resilience4j":            ("http_client", "Resilience4j"),
    "spring.rabbitmq":         ("messaging", "RabbitMQ"),
    "spring.data.mongodb":     ("database", "MongoDB"),
}


def _parse_properties_file(filepath: Path) -> dict:
    """Parse a .properties file into key-value pairs."""
    props = {}
    try:
        for line in filepath.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                props[key.strip()] = value.strip()
    except Exception:
        pass
    return props


def _parse_yaml_file(filepath: Path) -> dict:
    """Parse a YAML file into flat key-value pairs.

    Uses a simple parser to avoid requiring PyYAML as a dependency.
    """
    flat = {}
    try:
        content = filepath.read_text(encoding="utf-8", errors="replace")
        # Try PyYAML if available
        try:
            import yaml
            data = yaml.safe_load(content)
            if isinstance(data, dict):
                _flatten_dict(data, "", flat)
                return flat
        except ImportError:
            pass

        # Simple line-by-line parser for basic YAML
        key_stack: list[tuple[int, str]] = []
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            indent = len(line) - len(line.lstrip())
            # Pop stack entries with >= indent
            while key_stack and key_stack[-1][0] >= indent:
                key_stack.pop()
            if ":" in stripped:
                key_part, _, value_part = stripped.partition(":")
                key_part = key_part.strip()
                value_part = value_part.strip()
                if value_part:
                    prefix = ".".join(k for _, k in key_stack)
                    full_key = f"{prefix}.{key_part}" if prefix else key_part
                    flat[full_key] = value_part
                else:
                    key_stack.append((indent, key_part))
    except Exception:
        pass
    return flat


def _flatten_dict(d: dict, prefix: str, result: dict) -> None:
    """Flatten a nested dict into dot-separated keys."""
    for key, value in d.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            _flatten_dict(value, full_key, result)
        elif isinstance(value, list):
            result[full_key] = str(value)
        else:
            result[full_key] = str(value) if value is not None else ""


def _scan_config_files(repo: Path, profile: StackProfile) -> None:
    """Phase 3: Parse config files for technology signals."""
    # Spring config files
    config_files = [
        "application.yml", "application.yaml",
        "application.properties",
        "bootstrap.yml", "bootstrap.yaml",
        "bootstrap.properties",
    ]
    # Also check src/main/resources/
    resources_dir = repo / "src" / "main" / "resources"

    for cfg_name in config_files:
        for search_dir in (repo, resources_dir):
            cfg_path = search_dir / cfg_name
            if not cfg_path.is_file():
                continue

            if cfg_name.endswith((".yml", ".yaml")):
                props = _parse_yaml_file(cfg_path)
            else:
                props = _parse_properties_file(cfg_path)

            for key, value in props.items():
                for prefix, (cat, desc) in _CONFIG_KEY_TECH.items():
                    if key.startswith(prefix):
                        profile.config_properties[key] = value
                        break

    # K8s manifests
    k8s_patterns = ["**/deployment.yaml", "**/deployment.yml",
                     "**/k8s/**/*.yaml", "**/k8s/**/*.yml",
                     "**/helm/**/*.yaml", "**/helm/**/*.yml"]
    for pattern in k8s_patterns:
        for yml_path in repo.glob(pattern):
            if any(skip in yml_path.parts for skip in SKIP_DIRS):
                continue
            try:
                content = yml_path.read_text(encoding="utf-8", errors="replace")
                kind_match = re.search(r"kind:\s*(\w+)", content)
                name_match = re.search(r"name:\s*(\S+)", content)
                replicas_match = re.search(r"replicas:\s*(\d+)", content)
                image_match = re.search(r"image:\s*(\S+)", content)
                kind = kind_match.group(1) if kind_match else ""
                if kind in ("Deployment", "StatefulSet", "Service", "ConfigMap", "Ingress"):
                    profile.k8s_resources.append({
                        "kind": kind,
                        "name": name_match.group(1) if name_match else "",
                        "replicas": replicas_match.group(1) if replicas_match else "",
                        "image": image_match.group(1) if image_match else "",
                    })
            except Exception:
                continue

    # Dockerfile
    dockerfile = repo / "Dockerfile"
    if dockerfile.is_file():
        try:
            content = dockerfile.read_text(encoding="utf-8", errors="replace")
            from_match = re.search(r"FROM\s+(\S+)", content)
            expose_match = re.search(r"EXPOSE\s+(\d+)", content)
            base_image = from_match.group(1) if from_match else ""
            port = expose_match.group(1) if expose_match else ""
            if base_image:
                profile.k8s_resources.append({
                    "kind": "Docker",
                    "name": "Dockerfile",
                    "replicas": "",
                    "image": base_image,
                })
            if port:
                profile.config_properties["docker.expose.port"] = port
        except Exception:
            pass

    # docker-compose.yml
    compose = repo / "docker-compose.yml"
    if not compose.is_file():
        compose = repo / "docker-compose.yaml"
    if compose.is_file():
        try:
            content = compose.read_text(encoding="utf-8", errors="replace")
            for m in re.finditer(r"(\w[\w-]*):\s*\n\s+image:\s*(\S+)", content):
                profile.k8s_resources.append({
                    "kind": "Docker Compose",
                    "name": m.group(1),
                    "replicas": "",
                    "image": m.group(2),
                })
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Phase 4: Enterprise Properties File Scanning
# ---------------------------------------------------------------------------

# Patterns for service URLs in .properties files
_PROP_SVC_URL_RE = re.compile(r"^([\w.]+\.(?:svc\.rest\.url|rest\.url|svc\.url|endpoint\.url))\s*=\s*(.+)$", re.MULTILINE)
_PROP_SOAP_URL_RE = re.compile(
    r"^([\w.]+\.(?:wsdl\.url|soap\.url|ws\.url|webservice\.url|wsdl\.location))\s*=\s*(.+)$",
    re.MULTILINE,
)
_PROP_HOST_RE = re.compile(r"^([\w.]+\.host(?:_\w+)?)\s*=\s*(.+)$", re.MULTILINE)
_PROP_HOST_VAR_RE = re.compile(r"\$\{([\w.]+\.host(?:_\w+)?)\}")

# Environment priority for property files (higher = preferred; production wins)
_ENV_KEYWORDS: dict[str, int] = {
    "prod": 10, "production": 10, "prd": 10, "preprod": 8, "pre-prod": 8,
    "staging": 7, "stg": 7, "stage": 7, "uat": 7, "perf": 7,
    "sit": 4, "int": 4,
    "dev": 2, "development": 2,
    "local": 1, "test": 1, "sandbox": 1,
}

# Region-specific host patterns (e.g. gws.mms.host.east=..., gws.mms.host_us-east-1=...)
_REGION_HOST_RE = re.compile(
    r"^([\w.]+\.host)[._-](us-east-?\d?|us-west-?\d?|eu-west-?\d?|eu-central-?\d?|"
    r"ap-southeast-?\d?|ap-northeast-?\d?|ap-south-?\d?|"
    r"east|west|central|na|emea|apac)\s*=\s*(.+)$",
    re.MULTILINE | re.IGNORECASE,
)


def _env_priority(filepath: Path) -> int:
    """Return environment priority for a config file (higher = preferred, prod = 10)."""
    name = filepath.stem.lower()
    parent = filepath.parent.name.lower()
    for part in (name, parent):
        for env, pri in sorted(_ENV_KEYWORDS.items(), key=lambda x: -x[1]):
            if env in part:
                return pri
    return 5  # default/unspecified


def _scan_enterprise_properties(repo: Path, profile: StackProfile) -> None:
    """Phase 4: Scan .properties files for enterprise service URL patterns.

    Prefers production environment values when the same property key appears
    in multiple env-specific files.  Detects region-specific hosts.

    Detects:
    - *.svc.rest.url = ... patterns → downstream services
    - *.host = ... patterns → downstream hosts
    - ${...host} variable references in URL values → host dependencies
    - Region-specific host variants (e.g. *.host.east, *.host_us-west-2)
    """
    existing_names = {s["name"] for s in profile.downstream_services}
    prop_files: list[Path] = []

    # Find .properties files in standard locations
    for pattern in ("*.properties", "**/*.properties"):
        for pf in repo.glob(pattern):
            if any(skip in pf.parts for skip in SKIP_DIRS):
                continue
            prop_files.append(pf)
            if len(prop_files) > 50:  # cap to avoid huge repos
                break

    # Sort ascending by env priority so production files are processed last (override)
    prop_files.sort(key=_env_priority)

    # Collect best (production-preferred) URL per property key
    # key → (priority, value, rel_path)
    svc_best: dict[str, tuple[int, str, str]] = {}
    soap_best: dict[str, tuple[int, str, str]] = {}
    hosts_seen: set[str] = set()
    region_hosts: dict[str, set[str]] = {}  # base_host_name → {region names}

    for pf in prop_files:
        try:
            content = pf.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        priority = _env_priority(pf)
        prop_rel_path = str(pf.relative_to(repo)).replace("\\", "/")

        # REST service URL entries
        for m in _PROP_SVC_URL_RE.finditer(content):
            prop_key = m.group(1)
            prop_value = m.group(2).strip()
            if prop_key not in svc_best or priority >= svc_best[prop_key][0]:
                svc_best[prop_key] = (priority, prop_value, prop_rel_path)

            # Extract host variable references from the URL value
            for hm in _PROP_HOST_VAR_RE.finditer(prop_value):
                host_key = hm.group(1)
                host_name = _property_key_to_service_name(host_key)
                hosts_seen.add(host_name)

        # SOAP/WSDL URL entries
        for m in _PROP_SOAP_URL_RE.finditer(content):
            prop_key = m.group(1)
            prop_value = m.group(2).strip()
            if prop_key not in soap_best or priority >= soap_best[prop_key][0]:
                soap_best[prop_key] = (priority, prop_value, prop_rel_path)

        # Plain host definitions
        for m in _PROP_HOST_RE.finditer(content):
            host_key = m.group(1)
            host_name = _property_key_to_service_name(host_key)
            hosts_seen.add(host_name)

        # Region-specific host entries (e.g. gws.mms.host.east=...)
        for m in _REGION_HOST_RE.finditer(content):
            base_key = m.group(1)
            region = m.group(2).lower()
            base_name = _property_key_to_service_name(base_key)
            region_hosts.setdefault(base_name, set()).add(region)

    # Store production-preferred property values for URL resolution
    for prop_key, (_, value, _) in svc_best.items():
        profile.config_properties[prop_key] = value
    for prop_key, (_, value, _) in soap_best.items():
        profile.config_properties[prop_key] = value

    # Add REST service URLs (production-preferred values)
    for prop_key, (_, value, source_file) in svc_best.items():
        service_name = _property_key_to_service_name(prop_key)
        if service_name not in existing_names:
            existing_names.add(service_name)
            svc: dict = {
                "name": service_name,
                "client_type": "REST (properties)",
                "url": value,
                "source_file": source_file,
            }
            if service_name in region_hosts:
                svc["regions"] = sorted(region_hosts[service_name])
            profile.downstream_services.append(svc)

    # Add SOAP URLs (production-preferred values)
    for prop_key, (_, value, source_file) in soap_best.items():
        service_name = _property_key_to_service_name(prop_key)
        if service_name not in existing_names:
            existing_names.add(service_name)
            profile.downstream_services.append({
                "name": service_name,
                "client_type": "SOAP (properties)",
                "url": value,
                "source_file": source_file,
            })

    # Add unique hosts as downstream services (if not already captured)
    for host_name in sorted(hosts_seen):
        if host_name not in existing_names:
            existing_names.add(host_name)
            svc = {
                "name": host_name,
                "client_type": "host (properties)",
                "url": "",
                "source_file": "",
            }
            if host_name in region_hosts:
                svc["regions"] = sorted(region_hosts[host_name])
            profile.downstream_services.append(svc)


# ---------------------------------------------------------------------------
# App Type Classification
# ---------------------------------------------------------------------------

def _classify_app_type(profile: StackProfile) -> str:
    """Classify the application type based on detected technologies."""
    techs = profile.technologies
    has_api = bool(techs.get("api"))
    has_messaging = bool(techs.get("messaging"))
    has_batch = bool(techs.get("batch"))
    has_frontend = bool(techs.get("frontend"))

    if has_api and has_messaging:
        return "middleware"
    if has_batch:
        return "batch"
    if has_frontend and not has_api:
        return "web-frontend"
    if has_api and not has_messaging:
        return "microservice"

    # Check dependencies for Spring Boot without web
    has_spring = any(
        "spring" in d.get("artifact", "").lower()
        for d in profile.dependencies
    )
    if has_spring and not has_api:
        return "library"

    return "service"


# ---------------------------------------------------------------------------
# Deduplication helpers
# ---------------------------------------------------------------------------

def _dedup_endpoints(endpoints: list[dict]) -> list[dict]:
    """Remove duplicate API endpoints."""
    seen = set()
    deduped = []
    for ep in endpoints:
        key = (ep.get("class", ""), ep.get("path", ""), ep.get("http_method", ""))
        if key not in seen:
            seen.add(key)
            deduped.append(ep)
    return deduped


def _dedup_messaging(messages: list[dict]) -> list[dict]:
    """Merge duplicate messaging entries, aggregating source locations."""
    merged: dict[tuple, dict] = {}
    for msg in messages:
        key = (msg.get("type", ""), msg.get("topic", ""), msg.get("direction", ""))
        if key not in merged:
            merged[key] = {
                "type": msg.get("type", ""),
                "topic": msg.get("topic", ""),
                "group": msg.get("group", ""),
                "direction": msg.get("direction", ""),
                "source_files": [],
                "source_classes": [],
            }
        entry = merged[key]
        sf = msg.get("source_file", "")
        sc = msg.get("source_class", "")
        if sf and sf not in entry["source_files"]:
            entry["source_files"].append(sf)
        if sc and sc not in entry["source_classes"]:
            entry["source_classes"].append(sc)
        # Keep first non-empty group
        if not entry["group"] and msg.get("group"):
            entry["group"] = msg["group"]
    return list(merged.values())


def _dedup_data_stores(stores: list[dict]) -> list[dict]:
    """Merge data store entries by entity name, aggregating source locations."""
    merged: dict[tuple, dict] = {}
    # Priority: entity > repository > usage > model
    type_priority = {"entity": 0, "repository": 1, "model": 2, "usage": 3}
    for store in stores:
        entities = tuple(store.get("entities", []))
        if not entities:
            continue
        if entities not in merged:
            merged[entities] = {
                "type": store.get("type", ""),
                "entities": list(entities),
                "url_pattern": store.get("url_pattern", ""),
                "source_files": [],
                "source_classes": [],
            }
        entry = merged[entities]
        sf = store.get("source_file", "")
        sc = store.get("source_class", "")
        if sf and sf not in entry["source_files"]:
            entry["source_files"].append(sf)
        if sc and sc not in entry["source_classes"]:
            entry["source_classes"].append(sc)
        # Prefer higher-priority type
        cur_pri = type_priority.get(entry["type"], 99)
        new_pri = type_priority.get(store.get("type", ""), 99)
        if new_pri < cur_pri:
            entry["type"] = store["type"]
        # Keep first non-empty url_pattern
        if not entry["url_pattern"] and store.get("url_pattern"):
            entry["url_pattern"] = store["url_pattern"]
    return list(merged.values())


def _dedup_downstream_services(services: list[dict]) -> list[dict]:
    """Merge duplicate downstream service entries, aggregating source locations."""
    merged: dict[str, dict] = {}
    for svc in services:
        key = svc.get("name", "")
        if not key:
            continue
        if key not in merged:
            merged[key] = {
                "name": key,
                "client_type": svc.get("client_type", ""),
                "url": svc.get("url", ""),
                "source_files": [],
                "source_classes": [],
            }
        entry = merged[key]
        sf = svc.get("source_file", "")
        sc = svc.get("source_class", "")
        if sf and sf not in entry["source_files"]:
            entry["source_files"].append(sf)
        if sc and sc not in entry["source_classes"]:
            entry["source_classes"].append(sc)
        # Keep the first non-empty url/client_type
        if not entry["url"] and svc.get("url"):
            entry["url"] = svc["url"]
        if not entry["client_type"] and svc.get("client_type"):
            entry["client_type"] = svc["client_type"]
        # Preserve regions
        if svc.get("regions"):
            existing_regions = entry.get("regions", [])
            for r in svc["regions"]:
                if r not in existing_regions:
                    existing_regions.append(r)
            if existing_regions:
                entry["regions"] = existing_regions
    return list(merged.values())


# ---------------------------------------------------------------------------
# Phase 2.5: JISI Servlet XML Scanning
# ---------------------------------------------------------------------------

def _scan_jisi_servlets(repo: Path, profile: StackProfile) -> None:
    """Scan JISI servlet XML files for REST and SOAP endpoints.

    Reuses the existing parsers from src.bdd.servlet_discovery to discover
    endpoints declared in rest-servlet.xml (Spring beans) and cxf-servlet.xml
    (CXF JAX-WS), then adds them to the profile as API endpoints and
    downstream services.
    """
    from src.bdd.servlet_discovery import (
        _find_servlet_xml_files,
        _parse_rest_servlet_xml,
        _parse_cxf_servlet_xml,
        _derive_service_name,
    )

    rest_files, cxf_files = _find_servlet_xml_files(str(repo))
    if not rest_files and not cxf_files:
        return

    existing_endpoints = {
        (ep.get("class", ""), ep.get("path", ""), ep.get("http_method", ""))
        for ep in profile.api_endpoints
    }
    existing_services = {s.get("name", "") for s in profile.downstream_services}

    # REST servlet beans
    for xml_path in rest_files:
        try:
            endpoints = _parse_rest_servlet_xml(xml_path)
        except Exception:
            continue
        rel_xml = str(xml_path.relative_to(repo)).replace("\\", "/")
        for ep in endpoints:
            name = _derive_service_name(ep.bean_id, ep.fqcn, ep.protocol)
            ep_key = (name, ep.fqcn, "JISI REST")
            if ep_key not in existing_endpoints:
                existing_endpoints.add(ep_key)
                profile.api_endpoints.append({
                    "class": name,
                    "method": "",
                    "path": ep.fqcn,
                    "http_method": "JISI REST",
                })
            if name not in existing_services:
                existing_services.add(name)
                profile.downstream_services.append({
                    "name": name,
                    "client_type": "JISI REST",
                    "url": ep.fqcn,
                    "source_file": rel_xml,
                    "source_class": ep.fqcn,
                })

    # CXF / SOAP endpoints
    for xml_path in cxf_files:
        try:
            endpoints = _parse_cxf_servlet_xml(xml_path)
        except Exception:
            continue
        rel_xml = str(xml_path.relative_to(repo)).replace("\\", "/")
        for ep in endpoints:
            name = _derive_service_name(ep.bean_id, ep.fqcn, ep.protocol)
            ep_key = (name, ep.address or ep.fqcn, "JISI SOAP")
            if ep_key not in existing_endpoints:
                existing_endpoints.add(ep_key)
                profile.api_endpoints.append({
                    "class": name,
                    "method": "",
                    "path": ep.address or ep.fqcn,
                    "http_method": "JISI SOAP",
                })
            if name not in existing_services:
                existing_services.add(name)
                profile.downstream_services.append({
                    "name": name,
                    "client_type": "JISI SOAP",
                    "url": ep.address or ep.fqcn,
                    "source_file": rel_xml,
                    "source_class": ep.fqcn,
                })


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def analyze_stack(repo_path: str, consciousness=None, config: dict | None = None) -> StackProfile:
    """Run all analysis phases and return a StackProfile.

    Args:
        repo_path: Absolute path to repository root.
        consciousness: Optional ProjectConsciousness for code file access.
        config: Optional config dict. When provided, enables CodeIndex-based
            analysis (cached call graph) for cross-file dependency resolution.
            Falls back to regex scanning if not provided or if CodeIndex fails.
    """
    repo = Path(repo_path)
    if not repo.is_dir():
        return StackProfile()

    profile = StackProfile()

    # Detect language from common markers
    lang = ""
    if (repo / "pom.xml").exists() or (repo / "build.gradle").exists() or (repo / "build.gradle.kts").exists():
        lang = "java"
    elif (repo / "package.json").exists():
        lang = "javascript"
    elif (repo / "requirements.txt").exists() or (repo / "pyproject.toml").exists() or (repo / "setup.py").exists():
        lang = "python"

    if consciousness and hasattr(consciousness, "conventions"):
        conv_lang = consciousness.conventions.get("language", "")
        if conv_lang and conv_lang != "unknown":
            lang = conv_lang

    # Phase 1: Dependencies
    deps = []
    if lang == "java":
        if (repo / "pom.xml").exists():
            deps = _parse_maven_dependencies(repo)
        else:
            deps = _parse_gradle_dependencies(repo)
    elif lang in ("javascript", "typescript"):
        deps = _parse_npm_dependencies(repo)
    elif lang == "python":
        deps = _parse_python_dependencies(repo)

    technologies, enriched_deps = _map_dependencies(deps, lang)
    profile.technologies = technologies
    profile.dependencies = enriched_deps

    # Phase 2: Code patterns
    # Get code files either from consciousness or by walking
    code_files = []
    if consciousness and consciousness.implementation_samples:
        for sample in consciousness.implementation_samples:
            path = sample.get("path", "")
            if path:
                fpath = repo / path
                if fpath.is_file():
                    code_files.append((path, fpath))
    # Scan src/ directories for more coverage
    for src_dir in ("src", "app", "lib"):
        src_path = repo / src_dir
        if src_path.is_dir():
            for dirpath, dirnames, filenames in os.walk(src_path):
                dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
                for fname in filenames:
                    if fname.endswith((".java", ".kt", ".py", ".js", ".ts", ".jsx", ".tsx")):
                        fpath = Path(dirpath) / fname
                        rel = os.path.relpath(str(fpath), str(repo)).replace("\\", "/")
                        if not any(r == rel for r, _ in code_files):
                            code_files.append((rel, fpath))

    # Multi-module project support: also scan any nested src/main/java directories
    # (e.g. core/module/src/main/java/ in Maven multi-module projects)
    for smj in repo.rglob("src/main/java"):
        if not smj.is_dir():
            continue
        if any(skip in smj.parts for skip in SKIP_DIRS):
            continue
        # Skip if already covered by the scan above (direct src/ at root)
        if str(smj).startswith(str(repo / "src")):
            continue
        for dirpath, dirnames, filenames in os.walk(smj):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fname in filenames:
                if fname.endswith((".java", ".kt")):
                    fpath = Path(dirpath) / fname
                    rel = os.path.relpath(str(fpath), str(repo)).replace("\\", "/")
                    if not any(r == rel for r, _ in code_files):
                        code_files.append((rel, fpath))
                    if len(code_files) > 2000:  # cap to avoid huge repos
                        break
            if len(code_files) > 2000:
                break

    _scan_code_patterns(repo, code_files, profile, config=config)

    # Phase 2.5: JISI servlet XML scanning (if JISI framework detected)
    is_jisi = "JISI (WAS GWS)" in (profile.technologies.get("framework") or [])
    if is_jisi:
        _scan_jisi_servlets(repo, profile)

    # Phase 3: Config files
    _scan_config_files(repo, profile)

    # Phase 4: Enterprise properties (RESTProxy service URLs, host definitions)
    _scan_enterprise_properties(repo, profile)

    # Deduplicate
    profile.api_endpoints = _dedup_endpoints(profile.api_endpoints)
    profile.messaging = _dedup_messaging(profile.messaging)
    profile.data_stores = _dedup_data_stores(profile.data_stores)
    profile.downstream_services = _dedup_downstream_services(profile.downstream_services)

    # Resolve property-key URLs to production values
    # RESTProxy detection stores the property key as url (e.g. "gws.mms.qp.token.delete.svc.rest.url");
    # Phase 4 stores the actual production value in config_properties — resolve here.
    for svc in profile.downstream_services:
        url = svc.get("url", "")
        if url and "." in url and "://" not in url and "/" not in url:
            resolved = profile.config_properties.get(url)
            if resolved:
                svc["url"] = resolved

    # Classify app type
    profile.app_type = _classify_app_type(profile)

    return profile
