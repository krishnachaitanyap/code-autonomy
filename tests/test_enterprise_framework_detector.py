"""
Tests for enterprise framework detection and reference-aware migration context.
"""

import os
import tempfile
import textwrap
from pathlib import Path

import pytest

from src.services.enterprise_framework_detector import (
    EnterpriseFrameworkResult,
    detect_enterprise_frameworks,
    _parse_pom,
    _scan_annotations,
    _scan_config_files,
    ENTERPRISE_FRAMEWORK_RULES,
)


# ---------------------------------------------------------------------------
# Fixtures: create fake repos for testing
# ---------------------------------------------------------------------------

@pytest.fixture
def nucleus_repo(tmp_path):
    """Create a minimal Nucleus framework repo."""
    # pom.xml with Nucleus parent
    pom = tmp_path / "pom.xml"
    pom.write_text(textwrap.dedent("""\
        <?xml version="1.0" encoding="UTF-8"?>
        <project xmlns="http://maven.apache.org/POM/4.0.0">
            <modelVersion>4.0.0</modelVersion>
            <parent>
                <groupId>com.enterprise.nucleus</groupId>
                <artifactId>nucleus-parent</artifactId>
                <version>3.2.1</version>
            </parent>
            <groupId>com.myorg</groupId>
            <artifactId>my-nucleus-app</artifactId>
            <version>1.0.0</version>
            <dependencies>
                <dependency>
                    <groupId>com.enterprise.nucleus</groupId>
                    <artifactId>nucleus-core</artifactId>
                    <version>3.2.1</version>
                </dependency>
                <dependency>
                    <groupId>com.enterprise.nucleus</groupId>
                    <artifactId>nucleus-web</artifactId>
                    <version>3.2.1</version>
                </dependency>
                <dependency>
                    <groupId>org.springframework</groupId>
                    <artifactId>spring-context</artifactId>
                    <version>5.3.20</version>
                </dependency>
            </dependencies>
            <build>
                <plugins>
                    <plugin>
                        <artifactId>nucleus-maven-plugin</artifactId>
                    </plugin>
                </plugins>
            </build>
        </project>
    """))

    # Java source with Nucleus annotations
    src_dir = tmp_path / "src" / "main" / "java" / "com" / "myorg"
    src_dir.mkdir(parents=True)

    svc_file = src_dir / "UserService.java"
    svc_file.write_text(textwrap.dedent("""\
        package com.myorg;

        import com.enterprise.nucleus.annotation.NucleusService;
        import com.enterprise.nucleus.annotation.NucleusConfig;

        @NucleusService
        public class UserService {
            @NucleusConfig("user.cache.ttl")
            private int cacheTtl;

            public User getUser(String id) {
                return userRepo.findById(id);
            }
        }
    """))

    ctrl_file = src_dir / "UserController.java"
    ctrl_file.write_text(textwrap.dedent("""\
        package com.myorg;

        import com.enterprise.nucleus.annotation.NucleusEndpoint;

        @NucleusEndpoint(path = "/api/users")
        public class UserController {
            public List<User> listUsers() {
                return userService.getAll();
            }
        }
    """))

    # Proprietary config files
    resources = tmp_path / "src" / "main" / "resources"
    resources.mkdir(parents=True)

    nucleus_cfg = resources / "nucleus-config.xml"
    nucleus_cfg.write_text(textwrap.dedent("""\
        <?xml version="1.0" encoding="UTF-8"?>
        <nucleus-config>
            <bean id="dataSource" class="com.enterprise.nucleus.db.NucleusDataSource"/>
            <bean id="cacheManager" class="com.enterprise.nucleus.cache.NucleusCacheManager"/>
        </nucleus-config>
    """))

    nucleus_props = resources / "nucleus.properties"
    nucleus_props.write_text(textwrap.dedent("""\
        nucleus.app.name=my-nucleus-app
        nucleus.db.url=jdbc:oracle:thin:@localhost:1521:mydb
        nucleus.cache.enabled=true
    """))

    return tmp_path


@pytest.fixture
def photon_repo(tmp_path):
    """Create a minimal Photon (Spring Boot) reference repo."""
    pom = tmp_path / "pom.xml"
    pom.write_text(textwrap.dedent("""\
        <?xml version="1.0" encoding="UTF-8"?>
        <project xmlns="http://maven.apache.org/POM/4.0.0">
            <modelVersion>4.0.0</modelVersion>
            <parent>
                <groupId>com.enterprise.photon</groupId>
                <artifactId>photon-parent</artifactId>
                <version>2.0.0</version>
            </parent>
            <groupId>com.myorg</groupId>
            <artifactId>my-photon-app</artifactId>
            <version>1.0.0</version>
            <dependencies>
                <dependency>
                    <groupId>org.springframework.boot</groupId>
                    <artifactId>spring-boot-starter-web</artifactId>
                </dependency>
                <dependency>
                    <groupId>org.springframework.boot</groupId>
                    <artifactId>spring-boot-starter-actuator</artifactId>
                </dependency>
            </dependencies>
        </project>
    """))

    src_dir = tmp_path / "src" / "main" / "java" / "com" / "myorg"
    src_dir.mkdir(parents=True)

    app_file = src_dir / "Application.java"
    app_file.write_text(textwrap.dedent("""\
        package com.myorg;

        import org.springframework.boot.SpringApplication;
        import org.springframework.boot.autoconfigure.SpringBootApplication;

        @SpringBootApplication
        public class Application {
            public static void main(String[] args) {
                SpringApplication.run(Application.class, args);
            }
        }
    """))

    ctrl_file = src_dir / "UserController.java"
    ctrl_file.write_text(textwrap.dedent("""\
        package com.myorg;

        import org.springframework.web.bind.annotation.*;

        @RestController
        @RequestMapping("/api/v1/users")
        public class UserController {
            @GetMapping
            public List<UserDto> listUsers() {
                return userService.getAll();
            }

            @GetMapping("/{id}")
            public UserDto getUser(@PathVariable String id) {
                return userService.getById(id);
            }
        }
    """))

    resources = tmp_path / "src" / "main" / "resources"
    resources.mkdir(parents=True)
    (resources / "application.yml").write_text(textwrap.dedent("""\
        spring:
          application:
            name: my-photon-app
          datasource:
            url: jdbc:postgresql://localhost:5432/mydb
            driver-class-name: org.postgresql.Driver
        server:
          port: 8080
    """))

    return tmp_path


@pytest.fixture
def plain_springboot_repo(tmp_path):
    """A plain Spring Boot repo with no enterprise framework."""
    pom = tmp_path / "pom.xml"
    pom.write_text(textwrap.dedent("""\
        <?xml version="1.0" encoding="UTF-8"?>
        <project xmlns="http://maven.apache.org/POM/4.0.0">
            <parent>
                <groupId>org.springframework.boot</groupId>
                <artifactId>spring-boot-starter-parent</artifactId>
                <version>3.2.0</version>
            </parent>
            <groupId>com.example</groupId>
            <artifactId>demo</artifactId>
            <dependencies>
                <dependency>
                    <groupId>org.springframework.boot</groupId>
                    <artifactId>spring-boot-starter-web</artifactId>
                </dependency>
            </dependencies>
        </project>
    """))

    src_dir = tmp_path / "src" / "main" / "java" / "com" / "example"
    src_dir.mkdir(parents=True)
    (src_dir / "App.java").write_text(textwrap.dedent("""\
        package com.example;
        import org.springframework.boot.autoconfigure.SpringBootApplication;
        @SpringBootApplication
        public class App {}
    """))
    (tmp_path / "src" / "main" / "resources").mkdir(parents=True)
    (tmp_path / "src" / "main" / "resources" / "application.properties").write_text("server.port=8080\n")

    return tmp_path


# ---------------------------------------------------------------------------
# Tests: POM parsing
# ---------------------------------------------------------------------------

class TestPomParsing:
    def test_parse_nucleus_pom(self, nucleus_repo):
        data = _parse_pom(nucleus_repo)
        assert data["parent"] is not None
        assert "nucleus" in data["parent"]["artifact"].lower()
        assert data["parent"]["version"] == "3.2.1"
        assert len(data["dependencies"]) == 3
        assert any("nucleus-core" in d["artifact"] for d in data["dependencies"])

    def test_parse_photon_pom(self, photon_repo):
        data = _parse_pom(photon_repo)
        assert data["parent"] is not None
        assert "photon" in data["parent"]["artifact"].lower()

    def test_parse_no_pom(self, tmp_path):
        data = _parse_pom(tmp_path)
        assert data["parent"] is None
        assert data["dependencies"] == []

    def test_parse_plugins(self, nucleus_repo):
        data = _parse_pom(nucleus_repo)
        assert any("nucleus-maven-plugin" in p["artifact"] for p in data["plugins"])


# ---------------------------------------------------------------------------
# Tests: Full detection
# ---------------------------------------------------------------------------

class TestEnterpriseFrameworkDetection:
    def test_detect_nucleus(self, nucleus_repo):
        result = detect_enterprise_frameworks(nucleus_repo)
        assert isinstance(result, EnterpriseFrameworkResult)

        # Should detect Nucleus
        names = [f["name"] for f in result.frameworks_detected]
        assert "Nucleus" in names

        nucleus = next(f for f in result.frameworks_detected if f["name"] == "Nucleus")
        assert nucleus["confidence"] >= 40  # parent POM alone = 40
        assert nucleus["version"] == "3.2.1"
        assert nucleus["category"] == "internal"
        assert len(nucleus["evidence"]) > 0

    def test_detect_nucleus_annotations(self, nucleus_repo):
        result = detect_enterprise_frameworks(nucleus_repo)
        assert len(result.annotations_found) > 0
        ann_names = [a["annotation"] for a in result.annotations_found]
        assert any("NucleusService" in a for a in ann_names)

    def test_detect_nucleus_configs(self, nucleus_repo):
        result = detect_enterprise_frameworks(nucleus_repo)
        assert len(result.proprietary_configs) > 0
        config_files = [c["file"] for c in result.proprietary_configs]
        assert any("nucleus-config.xml" in f for f in config_files)
        assert any("nucleus.properties" in f for f in config_files)

    def test_detect_nucleus_libraries(self, nucleus_repo):
        result = detect_enterprise_frameworks(nucleus_repo)
        assert len(result.internal_libraries) > 0
        lib_names = [f"{l['group']}:{l['artifact']}" for l in result.internal_libraries]
        assert any("nucleus-core" in l for l in lib_names)

    def test_detect_nucleus_plugins(self, nucleus_repo):
        result = detect_enterprise_frameworks(nucleus_repo)
        assert len(result.build_plugins) > 0
        assert any("nucleus-maven-plugin" in p["plugin"] for p in result.build_plugins)

    def test_detect_nucleus_migration_impact(self, nucleus_repo):
        result = detect_enterprise_frameworks(nucleus_repo)
        impact = result.migration_impact
        assert impact["complexity"] == "high"
        assert impact["primary_framework"] == "Nucleus"
        assert "Spring Boot" in impact["target_framework"] or "Photon" in impact["target_framework"]
        assert len(impact["blockers"]) > 0
        assert len(impact["recommendations"]) > 0

    def test_detect_photon(self, photon_repo):
        result = detect_enterprise_frameworks(photon_repo)
        names = [f["name"] for f in result.frameworks_detected]
        assert "Photon" in names

    def test_detect_springboot_as_opensource(self, plain_springboot_repo):
        result = detect_enterprise_frameworks(plain_springboot_repo)
        names = [f["name"] for f in result.frameworks_detected]
        assert "Spring Boot" in names
        # Should NOT be flagged as high complexity
        assert result.migration_impact["complexity"] == "low"

    def test_no_internal_frameworks_in_plain_repo(self, plain_springboot_repo):
        result = detect_enterprise_frameworks(plain_springboot_repo)
        internal = [f for f in result.frameworks_detected if f["category"] == "internal"]
        assert len(internal) == 0

    def test_high_confidence_for_multiple_signals(self, nucleus_repo):
        """Nucleus repo has parent POM + deps + annotations + configs + plugin = very high confidence."""
        result = detect_enterprise_frameworks(nucleus_repo)
        nucleus = next(f for f in result.frameworks_detected if f["name"] == "Nucleus")
        # parent(40) + deps(20*2) + annotations(15*3) + configs(15*2) + plugin(20) = 175 → capped at 100
        assert nucleus["confidence"] == 100


class TestCustomRules:
    def test_extra_rules(self, tmp_path):
        """Test adding custom detection rules."""
        pom = tmp_path / "pom.xml"
        pom.write_text(textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <project xmlns="http://maven.apache.org/POM/4.0.0">
                <parent>
                    <groupId>com.mycompany.atlas</groupId>
                    <artifactId>atlas-parent</artifactId>
                    <version>5.0.0</version>
                </parent>
                <groupId>com.mycompany</groupId>
                <artifactId>my-app</artifactId>
            </project>
        """))

        custom_rules = [{
            "name": "Atlas",
            "category": "internal",
            "detect_by": {
                "parent_pom_keywords": ["atlas"],
                "dependency_groups": ["com.mycompany.atlas"],
                "annotations": [],
                "config_files": ["atlas.yml"],
                "build_plugins": [],
            },
            "migration_notes": {
                "target": "Spring Boot",
                "complexity": "medium",
                "key_changes": ["Migrate Atlas config to application.yml"],
            },
        }]

        result = detect_enterprise_frameworks(tmp_path, extra_rules=custom_rules)
        names = [f["name"] for f in result.frameworks_detected]
        assert "Atlas" in names


# ---------------------------------------------------------------------------
# Tests: Migration context enrichment
# ---------------------------------------------------------------------------

class TestMigrationContextEnrichment:
    """Verify that the reference repo context is rich enough for the agent."""

    def test_reference_consciousness_includes_structure(self, photon_repo):
        """Reference repo consciousness should include directory structure."""
        from src.consciousness.core import build_consciousness
        consciousness = build_consciousness(str(photon_repo), repo_url="")
        rendered = consciousness._render_full(
            max_samples_chars=25000, structure_depth=4, max_sigs=40
        )
        assert "src" in rendered
        assert "java" in rendered
        assert "Application.java" in rendered or "UserController.java" in rendered

    def test_reference_consciousness_includes_code_samples(self, photon_repo):
        """Reference repo consciousness should include actual code samples."""
        from src.consciousness.core import build_consciousness
        consciousness = build_consciousness(str(photon_repo), repo_url="")
        rendered = consciousness._render_full(
            max_samples_chars=25000, structure_depth=4, max_sigs=40
        )
        # Should contain actual code patterns from reference
        assert "@SpringBootApplication" in rendered or "@RestController" in rendered

    def test_reference_consciousness_includes_conventions(self, photon_repo):
        """Reference repo consciousness should include detected conventions."""
        from src.consciousness.core import build_consciousness
        consciousness = build_consciousness(str(photon_repo), repo_url="")
        rendered = consciousness._render_full(
            max_samples_chars=25000, structure_depth=4, max_sigs=40
        )
        assert "Language/build" in rendered
