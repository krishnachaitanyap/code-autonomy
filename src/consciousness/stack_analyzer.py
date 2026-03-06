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

    return technologies, enriched


# ---------------------------------------------------------------------------
# Phase 2: Code Pattern Scanning
# ---------------------------------------------------------------------------

# Java/Kotlin patterns
_PATTERN_REST_CONTROLLER = re.compile(
    r"@(RestController|RequestMapping|GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping)"
    r"(?:\(([^)]*)\))?"
)
_PATTERN_SOAP = re.compile(r"@(WebService|WebMethod|SOAPBinding)")
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

# Python patterns
_PATTERN_PY_ROUTE = re.compile(r"@\w+\.(route|get|post|put|delete|patch)\s*\(\s*['\"]([^'\"]+)['\"]")
_PATTERN_PY_MODEL = re.compile(r"class\s+(\w+)\s*\(.*(?:Model|Base|db\.Model)\s*\)")
_PATTERN_PY_CELERY_TASK = re.compile(r"@(?:shared_task|app\.task|celery\.task)")

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


def _scan_java_patterns(content: str, rel_path: str, profile: StackProfile) -> None:
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
            })
        elif m.group(1) == "SendTo":
            topic = _extract_param(m.group(2))
            profile.messaging.append({
                "type": "Kafka", "topic": topic, "group": "",
                "direction": "producer",
            })
        else:
            # KafkaTemplate usage
            profile.messaging.append({
                "type": "Kafka", "topic": "", "group": "",
                "direction": "producer",
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
        })

    # Feign clients
    for m in _PATTERN_FEIGN.finditer(content):
        service_name = _extract_param(m.group(1))
        url_match = re.search(r"""url\s*=\s*["']([^"']+)["']""", m.group(1))
        url = url_match.group(1) if url_match else ""
        profile.downstream_services.append({
            "name": service_name or class_name, "client_type": "Feign",
            "url": url,
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


def _scan_python_patterns(content: str, rel_path: str, profile: StackProfile) -> None:
    """Scan a Python file for technology patterns."""
    # Flask/FastAPI routes
    for m in _PATTERN_PY_ROUTE.finditer(content):
        http_method = m.group(1).upper()
        if http_method == "ROUTE":
            http_method = "GET"
        path = m.group(2)
        module_name = Path(rel_path).stem
        profile.api_endpoints.append({
            "class": module_name, "method": "", "path": path,
            "http_method": http_method,
        })

    # SQLAlchemy/Django models
    for m in _PATTERN_PY_MODEL.finditer(content):
        model_name = m.group(1)
        profile.data_stores.append({
            "type": "model", "entities": [model_name], "url_pattern": "",
        })

    # Celery tasks
    for m in _PATTERN_PY_CELERY_TASK.finditer(content):
        profile.messaging.append({
            "type": "Celery", "topic": "", "group": "",
            "direction": "task",
        })


def _scan_code_patterns(repo: Path, code_files: list, profile: StackProfile) -> None:
    """Phase 2: Scan code files for technology patterns."""
    for rel_path, fpath in code_files:
        try:
            content = fpath.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        if rel_path.endswith((".java", ".kt")):
            _scan_java_patterns(content, rel_path, profile)
        elif rel_path.endswith(".py"):
            _scan_python_patterns(content, rel_path, profile)


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
    """Remove duplicate messaging entries."""
    seen = set()
    deduped = []
    for msg in messages:
        key = (msg.get("type", ""), msg.get("topic", ""), msg.get("direction", ""))
        if key not in seen:
            seen.add(key)
            deduped.append(msg)
    return deduped


def _dedup_data_stores(stores: list[dict]) -> list[dict]:
    """Merge data store entries by entity name."""
    seen_entities = set()
    deduped = []
    for store in stores:
        entities = tuple(store.get("entities", []))
        if entities and entities not in seen_entities:
            seen_entities.add(entities)
            deduped.append(store)
    return deduped


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def analyze_stack(repo_path: str, consciousness=None) -> StackProfile:
    """Run all three analysis phases and return a StackProfile.

    Args:
        repo_path: Absolute path to repository root.
        consciousness: Optional ProjectConsciousness for code file access.
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
    # Also scan src/ directories for more coverage
    for src_dir in ("src", "app", "lib"):
        src_path = repo / src_dir
        if src_path.is_dir():
            for dirpath, dirnames, filenames in os.walk(src_path):
                dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
                for fname in filenames:
                    if fname.endswith((".java", ".kt", ".py", ".js", ".ts")):
                        fpath = Path(dirpath) / fname
                        rel = os.path.relpath(str(fpath), str(repo)).replace("\\", "/")
                        if not any(r == rel for r, _ in code_files):
                            code_files.append((rel, fpath))

    _scan_code_patterns(repo, code_files, profile)

    # Phase 3: Config files
    _scan_config_files(repo, profile)

    # Deduplicate
    profile.api_endpoints = _dedup_endpoints(profile.api_endpoints)
    profile.messaging = _dedup_messaging(profile.messaging)
    profile.data_stores = _dedup_data_stores(profile.data_stores)

    # Classify app type
    profile.app_type = _classify_app_type(profile)

    return profile
