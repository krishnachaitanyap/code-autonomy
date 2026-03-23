"""
Artifact repository settings file generators.

Generates Maven settings.xml, .npmrc, and Gradle init.gradle from the
artifact_repository config section, so dependency resolution commands
can reach enterprise artifact repositories (Artifactory, Nexus, etc.).
"""

import os
import re
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional


def generate_maven_settings(artifact_config: dict, output_dir: str) -> str:
    """Generate a Maven settings.xml with mirror + server auth blocks.

    Returns the path to the generated file.
    """
    mirror_url = artifact_config.get("maven_mirror_url", "")
    mirror_id = artifact_config.get("maven_mirror_id", "enterprise")
    release_url = artifact_config.get("maven_release_url", "")
    snapshot_url = artifact_config.get("maven_snapshot_url", "")
    username = artifact_config.get("maven_username", "")
    password = artifact_config.get("maven_password", "")

    mirrors = ""
    if mirror_url:
        mirrors = f"""
  <mirrors>
    <mirror>
      <id>{mirror_id}</id>
      <mirrorOf>*</mirrorOf>
      <url>{mirror_url}</url>
    </mirror>
  </mirrors>"""

    servers = ""
    server_ids = set()
    if username and mirror_id:
        server_ids.add(mirror_id)
    if release_url:
        server_ids.add(f"{mirror_id}-releases")
    if snapshot_url:
        server_ids.add(f"{mirror_id}-snapshots")

    if username and server_ids:
        server_blocks = []
        for sid in sorted(server_ids):
            server_blocks.append(f"""    <server>
      <id>{sid}</id>
      <username>{username}</username>
      <password>{password}</password>
    </server>""")
        servers = "\n  <servers>\n" + "\n".join(server_blocks) + "\n  </servers>"

    profiles = ""
    if release_url or snapshot_url:
        repos = []
        if release_url:
            repos.append(f"""        <repository>
          <id>{mirror_id}-releases</id>
          <url>{release_url}</url>
          <releases><enabled>true</enabled></releases>
          <snapshots><enabled>false</enabled></snapshots>
        </repository>""")
        if snapshot_url:
            repos.append(f"""        <repository>
          <id>{mirror_id}-snapshots</id>
          <url>{snapshot_url}</url>
          <releases><enabled>false</enabled></releases>
          <snapshots><enabled>true</enabled></snapshots>
        </repository>""")
        profiles = f"""
  <profiles>
    <profile>
      <id>enterprise</id>
      <repositories>
{chr(10).join(repos)}
      </repositories>
    </profile>
  </profiles>
  <activeProfiles>
    <activeProfile>enterprise</activeProfile>
  </activeProfiles>"""

    content = f"""<?xml version="1.0" encoding="UTF-8"?>
<settings xmlns="http://maven.apache.org/SETTINGS/1.0.0"
          xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
          xsi:schemaLocation="http://maven.apache.org/SETTINGS/1.0.0
                              http://maven.apache.org/xsd/settings-1.0.0.xsd">{mirrors}{servers}{profiles}
</settings>
"""
    path = os.path.join(output_dir, "settings.xml")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def generate_npmrc(artifact_config: dict, output_dir: str) -> str:
    """Generate an .npmrc file with registry + auth token.

    Returns the path to the generated file.
    """
    registry_url = artifact_config.get("npm_registry_url", "")
    auth_token = artifact_config.get("npm_auth_token", "")
    verify_ssl = artifact_config.get("verify_ssl", True)

    lines = []
    if registry_url:
        lines.append(f"registry={registry_url}")
        # Extract host portion for auth scope
        # e.g. https://artifactory.corp.example.com/api/npm/npm-virtual
        # becomes //artifactory.corp.example.com/api/npm/npm-virtual
        if auth_token:
            scope = registry_url.replace("https:", "").replace("http:", "")
            lines.append(f"{scope}:_authToken={auth_token}")
    if not verify_ssl:
        lines.append("strict-ssl=false")

    ca_cert = artifact_config.get("ca_cert_path", "")
    if ca_cert:
        lines.append(f"cafile={ca_cert}")

    content = "\n".join(lines) + "\n"
    path = os.path.join(output_dir, ".npmrc")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def generate_gradle_init(artifact_config: dict, output_dir: str) -> str:
    """Generate an init.gradle with custom repository declarations.

    Returns the path to the generated file.
    """
    mirror_url = artifact_config.get("maven_mirror_url", "")
    mirror_id = artifact_config.get("maven_mirror_id", "enterprise")
    plugin_url = artifact_config.get("gradle_plugin_url", "")
    username = artifact_config.get("maven_username", "")
    password = artifact_config.get("maven_password", "")
    verify_ssl = artifact_config.get("verify_ssl", True)

    repo_url = mirror_url or artifact_config.get("maven_release_url", "")

    cred_block = ""
    if username:
        cred_block = f"""
                credentials {{
                    username = '{username}'
                    password = '{password}'
                }}"""

    repo_block = ""
    if repo_url:
        repo_block = f"""
    allprojects {{
        repositories {{
            maven {{
                name = '{mirror_id}'
                url = '{repo_url}'{cred_block}
                allowInsecureProtocol = {str(not verify_ssl).lower()}
            }}
        }}
    }}"""

    plugin_block = ""
    if plugin_url:
        plugin_block = f"""
    settingsEvaluated {{ settings ->
        settings.pluginManagement {{
            repositories {{
                maven {{
                    name = '{mirror_id}-plugins'
                    url = '{plugin_url}'{cred_block}
                    allowInsecureProtocol = {str(not verify_ssl).lower()}
                }}
            }}
        }}
    }}"""

    content = f"""// Auto-generated init.gradle for enterprise artifact repository
allprojects {{
    buildscript {{
        repositories {{
            maven {{
                name = '{mirror_id}'
                url = '{repo_url}'{cred_block}
            }}
        }}
    }}
}}{repo_block}{plugin_block}
"""
    path = os.path.join(output_dir, "init.gradle")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def _detect_build_tool(repo_path: str) -> str:
    """Detect the build tool used by the repository.

    Returns 'maven', 'gradle', or 'npm'.
    """
    repo = Path(repo_path)
    if (repo / "pom.xml").exists() or (repo / "mvnw").exists():
        return "maven"
    if (repo / "build.gradle").exists() or (repo / "build.gradle.kts").exists() or (repo / "gradlew").exists():
        return "gradle"
    if (repo / "package.json").exists():
        return "npm"
    # Default to maven for Java repos
    if any(repo.rglob("*.java")):
        return "maven"
    return "npm"


def prepare_dependency_env(artifact_config: dict, repo_path: str) -> dict:
    """Detect build tool and generate appropriate settings files.

    Returns a dict with:
        build_tool: str - detected build tool name
        settings_path: str - path to generated settings file
        download_cmd: str - command to run for dependency resolution
        source_cache_dir: str - where downloaded sources end up
    """
    if not artifact_config.get("enabled", False):
        return {
            "build_tool": _detect_build_tool(repo_path),
            "settings_path": "",
            "download_cmd": "",
            "source_cache_dir": "",
            "error": "Artifact repository is not enabled. Configure it in Settings > Artifact Repository.",
        }

    build_tool = _detect_build_tool(repo_path)
    tmp_dir = tempfile.mkdtemp(prefix="artifact_repo_")

    if build_tool == "maven":
        settings_path = generate_maven_settings(artifact_config, tmp_dir)
        ca_cert = artifact_config.get("ca_cert_path", "")
        ssl_opts = ""
        if ca_cert:
            ssl_opts = f" -Djavax.net.ssl.trustStore={ca_cert}"
        if not artifact_config.get("verify_ssl", True):
            ssl_opts += " -Dmaven.wagon.http.ssl.insecure=true -Dmaven.wagon.http.ssl.allowall=true"
        download_cmd = f"mvn -s {settings_path} dependency:resolve -Dclassifier=sources -B{ssl_opts}"
        source_cache_dir = os.path.expanduser("~/.m2/repository")
        return {
            "build_tool": "maven",
            "settings_path": settings_path,
            "download_cmd": download_cmd,
            "source_cache_dir": source_cache_dir,
        }

    elif build_tool == "gradle":
        init_path = generate_gradle_init(artifact_config, tmp_dir)
        download_cmd = f"./gradlew dependencies --init-script {init_path}"
        source_cache_dir = os.path.expanduser("~/.gradle/caches/modules-2/files-2.1")
        return {
            "build_tool": "gradle",
            "settings_path": init_path,
            "download_cmd": download_cmd,
            "source_cache_dir": source_cache_dir,
        }

    elif build_tool == "npm":
        npmrc_path = generate_npmrc(artifact_config, tmp_dir)
        registry_url = artifact_config.get("npm_registry_url", "")
        registry_flag = f" --registry {registry_url}" if registry_url else ""
        download_cmd = f"npm install --userconfig {npmrc_path}{registry_flag}"
        source_cache_dir = os.path.join(repo_path, "node_modules")
        return {
            "build_tool": "npm",
            "settings_path": npmrc_path,
            "download_cmd": download_cmd,
            "source_cache_dir": source_cache_dir,
        }

    return {
        "build_tool": build_tool,
        "settings_path": "",
        "download_cmd": "",
        "source_cache_dir": "",
        "error": f"Unsupported build tool: {build_tool}",
    }


# ===================================================================
# Dependency listing (parse build files without downloading)
# ===================================================================

def list_dependencies(repo_path: str) -> dict:
    """Parse build files and return structured dependency information.

    Returns a dict with:
        build_tool: str
        dependencies: list[dict] with groupId, artifactId, version, scope
        build_file: str - path to the build file parsed
        framework_hints: list[str] - detected framework names
    """
    build_tool = _detect_build_tool(repo_path)
    repo = Path(repo_path)

    if build_tool == "maven":
        return _parse_maven_deps(repo)
    elif build_tool == "gradle":
        return _parse_gradle_deps(repo)
    elif build_tool == "npm":
        return _parse_npm_deps(repo)

    return {
        "build_tool": build_tool,
        "dependencies": [],
        "build_file": "",
        "framework_hints": [],
    }


def _parse_maven_deps(repo: Path) -> dict:
    """Parse pom.xml for dependencies."""
    pom_path = repo / "pom.xml"
    if not pom_path.exists():
        return {"build_tool": "maven", "dependencies": [], "build_file": "", "framework_hints": []}

    deps = []
    framework_hints = set()
    ns = {"m": "http://maven.apache.org/POM/4.0.0"}

    try:
        tree = ET.parse(str(pom_path))
        root = tree.getroot()

        # Handle both namespaced and non-namespaced pom.xml
        dep_elements = root.findall(".//m:dependencies/m:dependency", ns)
        if not dep_elements:
            dep_elements = root.findall(".//dependencies/dependency")

        for dep in dep_elements:
            gid = dep.findtext("m:groupId", "", ns) or dep.findtext("groupId", "") or ""
            aid = dep.findtext("m:artifactId", "", ns) or dep.findtext("artifactId", "") or ""
            ver = dep.findtext("m:version", "", ns) or dep.findtext("version", "") or ""
            scope = dep.findtext("m:scope", "compile", ns) or dep.findtext("scope", "compile") or "compile"

            if gid and aid:
                deps.append({
                    "groupId": gid,
                    "artifactId": aid,
                    "version": ver,
                    "scope": scope,
                    "coordinate": f"{gid}:{aid}:{ver}" if ver else f"{gid}:{aid}",
                })
                # Detect known frameworks
                _detect_framework(gid, aid, framework_hints)

        # Also parse parent POM
        parent = root.find("m:parent", ns) or root.find("parent")
        if parent is not None:
            pgid = parent.findtext("m:groupId", "", ns) or parent.findtext("groupId", "") or ""
            paid = parent.findtext("m:artifactId", "", ns) or parent.findtext("artifactId", "") or ""
            pver = parent.findtext("m:version", "", ns) or parent.findtext("version", "") or ""
            if pgid and paid:
                deps.insert(0, {
                    "groupId": pgid, "artifactId": paid, "version": pver,
                    "scope": "parent", "coordinate": f"{pgid}:{paid}:{pver}",
                })
                _detect_framework(pgid, paid, framework_hints)

    except ET.ParseError:
        pass

    return {
        "build_tool": "maven",
        "dependencies": deps,
        "build_file": "pom.xml",
        "framework_hints": sorted(framework_hints),
    }


def _parse_gradle_deps(repo: Path) -> dict:
    """Parse build.gradle for dependencies (best-effort regex)."""
    for name in ("build.gradle", "build.gradle.kts"):
        gf = repo / name
        if gf.exists():
            break
    else:
        return {"build_tool": "gradle", "dependencies": [], "build_file": "", "framework_hints": []}

    deps = []
    framework_hints = set()

    try:
        content = gf.read_text(encoding="utf-8", errors="replace")
        # Match: implementation 'group:artifact:version'
        # Match: implementation("group:artifact:version")
        pattern = re.compile(
            r"(?:implementation|api|compile|testImplementation|runtimeOnly|compileOnly)"
            r"""\s*[\('"]\s*['"]?([^:'"]+):([^:'"]+):?([^'")\s]*)['"]?\s*[\)']""",
        )
        for m in pattern.finditer(content):
            gid, aid, ver = m.group(1), m.group(2), m.group(3) or ""
            deps.append({
                "groupId": gid, "artifactId": aid, "version": ver,
                "scope": "compile",
                "coordinate": f"{gid}:{aid}:{ver}" if ver else f"{gid}:{aid}",
            })
            _detect_framework(gid, aid, framework_hints)
    except Exception:
        pass

    return {
        "build_tool": "gradle",
        "dependencies": deps,
        "build_file": gf.name,
        "framework_hints": sorted(framework_hints),
    }


def _parse_npm_deps(repo: Path) -> dict:
    """Parse package.json for dependencies."""
    import json as _json

    pkg_path = repo / "package.json"
    if not pkg_path.exists():
        return {"build_tool": "npm", "dependencies": [], "build_file": "", "framework_hints": []}

    deps = []
    framework_hints = set()

    try:
        pkg = _json.loads(pkg_path.read_text(encoding="utf-8"))
        for section, scope in [("dependencies", "runtime"), ("devDependencies", "dev"),
                               ("peerDependencies", "peer")]:
            for name, ver in (pkg.get(section) or {}).items():
                deps.append({
                    "groupId": "", "artifactId": name, "version": ver,
                    "scope": scope, "coordinate": f"{name}@{ver}",
                })
                _detect_npm_framework(name, framework_hints)
    except Exception:
        pass

    return {
        "build_tool": "npm",
        "dependencies": deps,
        "build_file": "package.json",
        "framework_hints": sorted(framework_hints),
    }


# Well-known framework patterns for auto-detection
_FRAMEWORK_PATTERNS = {
    "spring": ["org.springframework", "spring-boot", "spring-cloud"],
    "quarkus": ["io.quarkus"],
    "micronaut": ["io.micronaut"],
    "jakarta-ee": ["jakarta."],
    "junit5": ["org.junit.jupiter", "junit-jupiter"],
    "junit4": ["junit:junit"],
    "testng": ["org.testng"],
    "mockito": ["org.mockito"],
    "hibernate": ["org.hibernate"],
    "mybatis": ["org.mybatis"],
    "apache-camel": ["org.apache.camel"],
    "apache-kafka": ["org.apache.kafka"],
    "grpc": ["io.grpc"],
    "guice": ["com.google.inject"],
    "lombok": ["org.projectlombok"],
    "jackson": ["com.fasterxml.jackson"],
    "slf4j": ["org.slf4j"],
    "log4j": ["org.apache.logging.log4j"],
}


def _detect_framework(group_id: str, artifact_id: str, hints: set) -> None:
    """Add framework name to hints if dependency matches a known pattern."""
    coord = f"{group_id}:{artifact_id}".lower()
    for fw_name, patterns in _FRAMEWORK_PATTERNS.items():
        for pat in patterns:
            if pat.lower() in coord:
                hints.add(fw_name)
                return


_NPM_FRAMEWORK_PATTERNS = {
    "react": ["react", "react-dom", "next"],
    "angular": ["@angular/core"],
    "vue": ["vue", "nuxt"],
    "express": ["express"],
    "nestjs": ["@nestjs/core"],
    "jest": ["jest", "@jest/core"],
    "mocha": ["mocha"],
    "typescript": ["typescript"],
    "webpack": ["webpack"],
    "vite": ["vite"],
}


def _detect_npm_framework(name: str, hints: set) -> None:
    """Add framework name to hints if npm package matches a known pattern."""
    name_lower = name.lower()
    for fw_name, patterns in _NPM_FRAMEWORK_PATTERNS.items():
        for pat in patterns:
            if name_lower == pat or name_lower.startswith(pat + "/"):
                hints.add(fw_name)
                return


# ===================================================================
# Well-known groupId prefixes — LLM already trained on these
# ===================================================================

_WELL_KNOWN_GROUP_PREFIXES = [
    # Apache
    "org.apache.", "commons-",
    # Spring
    "org.springframework", "io.spring",
    # Jakarta / Java EE
    "jakarta.", "javax.", "java.",
    # Testing
    "org.junit", "junit", "org.testng", "org.mockito", "org.assertj",
    "org.hamcrest", "org.awaitility", "io.cucumber", "io.rest-assured",
    # Logging
    "org.slf4j", "org.apache.logging", "ch.qos.logback", "log4j",
    # Serialization
    "com.fasterxml.jackson", "com.google.gson", "org.json",
    # Google
    "com.google.", "io.grpc", "com.google.guava", "com.google.protobuf",
    # Cloud / AWS / Azure
    "software.amazon.awssdk", "com.amazonaws", "com.azure", "com.microsoft",
    "io.awspring",
    # Data
    "org.hibernate", "org.mybatis", "org.flywaydb", "org.liquibase",
    "org.postgresql", "mysql", "com.oracle", "com.h2database",
    "org.mongodb", "redis.clients", "io.lettuce",
    # Reactive
    "io.projectreactor", "io.reactivex",
    # Build tools / plugins
    "org.codehaus", "org.projectlombok", "org.mapstruct",
    # Quarkus / Micronaut
    "io.quarkus", "io.micronaut",
    # Swagger / OpenAPI
    "io.swagger", "org.springdoc", "org.openapitools",
    # Metrics / Observability
    "io.micrometer", "io.opentelemetry", "io.prometheus",
    # Security
    "org.bouncycastle", "com.auth0", "io.jsonwebtoken",
    # Networking
    "io.netty", "com.squareup.okhttp3", "org.asynchttpclient",
    # Misc well-known
    "org.yaml", "org.aspectj", "cglib", "org.ow2.asm",
    "com.github.", "io.github.",
]

_WELL_KNOWN_NPM_PREFIXES = [
    "react", "@react", "next", "vue", "nuxt", "@vue", "angular", "@angular",
    "express", "koa", "fastify", "@nestjs", "hapi",
    "jest", "mocha", "chai", "cypress", "@testing-library", "vitest",
    "typescript", "ts-", "@types/",
    "webpack", "vite", "esbuild", "rollup", "parcel", "turbopack",
    "eslint", "prettier", "stylelint",
    "axios", "node-fetch", "got", "superagent",
    "lodash", "underscore", "ramda", "date-fns", "moment", "dayjs",
    "tailwindcss", "bootstrap", "@mui/", "antd", "chakra",
    "prisma", "typeorm", "sequelize", "mongoose", "knex",
    "aws-sdk", "@aws-sdk/", "@azure/", "@google-cloud/",
    "graphql", "apollo", "@apollo/",
    "redis", "ioredis", "bull", "amqplib",
    "winston", "pino", "bunyan",
    "zod", "joi", "yup", "ajv",
    "uuid", "dotenv", "cors", "helmet", "jsonwebtoken",
]


def is_known_to_llm(group_id: str, artifact_id: str = "") -> bool:
    """Check if a Java/Maven dependency is well-known (LLM already trained on it).

    Returns True for open-source frameworks the LLM has seen in training data.
    Returns False for enterprise-internal dependencies that need source inspection.
    """
    gid_lower = group_id.lower()
    for prefix in _WELL_KNOWN_GROUP_PREFIXES:
        if gid_lower.startswith(prefix.lower()):
            return True
    return False


def is_npm_known_to_llm(package_name: str) -> bool:
    """Check if an npm package is well-known."""
    name_lower = package_name.lower()
    for prefix in _WELL_KNOWN_NPM_PREFIXES:
        if name_lower == prefix or name_lower.startswith(prefix):
            return True
    # Scoped packages from well-known orgs
    if name_lower.startswith("@") and "/" in name_lower:
        org = name_lower.split("/")[0]
        if org in ("@types", "@babel", "@eslint", "@jest", "@testing-library",
                    "@mui", "@emotion", "@apollo", "@graphql-tools", "@aws-sdk",
                    "@azure", "@google-cloud", "@nestjs", "@angular", "@vue",
                    "@react", "@next", "@vercel", "@prisma"):
            return True
    return False
