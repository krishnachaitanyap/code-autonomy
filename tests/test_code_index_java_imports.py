"""Tests for Java import resolution in src/code_index/import_resolver.py"""

import pytest

from src.code_index.symbol_table import SymbolEntry, SymbolTable
from src.code_index.import_resolver import resolve_java_imports, resolve_imports


def _make_java_symbol_table() -> SymbolTable:
    """Build a SymbolTable with Java symbols for testing."""
    st = SymbolTable()
    st.add(SymbolEntry(
        fqn="com/example/service/UserService.java::UserService",
        file_path="com/example/service/UserService.java",
        name="UserService", symbol_type="class",
        line_start=3, line_end=20,
        signature="public class UserService",
        language="java",
    ))
    st.add(SymbolEntry(
        fqn="com/example/service/UserService.java::UserService.findById",
        file_path="com/example/service/UserService.java",
        name="findById", symbol_type="method",
        line_start=5, line_end=10,
        signature="public User findById(Long id)",
        parent_class="com/example/service/UserService.java::UserService",
        language="java",
    ))
    st.add(SymbolEntry(
        fqn="com/example/model/User.java::User",
        file_path="com/example/model/User.java",
        name="User", symbol_type="class",
        line_start=3, line_end=15,
        signature="public class User",
        language="java",
    ))
    st.add(SymbolEntry(
        fqn="com/example/util/Constants.java::Constants",
        file_path="com/example/util/Constants.java",
        name="Constants", symbol_type="class",
        line_start=3, line_end=10,
        signature="public class Constants",
        language="java",
    ))
    st.add(SymbolEntry(
        fqn="com/example/util/Constants.java::Constants.MAX_SIZE",
        file_path="com/example/util/Constants.java",
        name="MAX_SIZE", symbol_type="method",
        line_start=5, line_end=5,
        signature="public static final int MAX_SIZE = 100",
        parent_class="com/example/util/Constants.java::Constants",
        language="java",
    ))
    st.add(SymbolEntry(
        fqn="com/example/service/OrderService.java::OrderService",
        file_path="com/example/service/OrderService.java",
        name="OrderService", symbol_type="class",
        line_start=3, line_end=20,
        signature="public class OrderService",
        language="java",
    ))
    return st


class TestSingleTypeImport:
    def test_single_type_import(self):
        st = _make_java_symbol_table()
        file_contents = {
            "com/example/controller/UserController.java": (
                "package com.example.controller;\n\n"
                "import com.example.service.UserService;\n"
                "import com.example.model.User;\n\n"
                "public class UserController {\n"
                "}\n"
            ),
            "com/example/service/UserService.java": "",
            "com/example/model/User.java": "",
            "com/example/util/Constants.java": "",
            "com/example/service/OrderService.java": "",
        }
        # Add a symbol for the controller file
        st.add(SymbolEntry(
            fqn="com/example/controller/UserController.java::UserController",
            file_path="com/example/controller/UserController.java",
            name="UserController", symbol_type="class",
            line_start=6, line_end=7,
            signature="public class UserController",
            language="java",
        ))

        result = resolve_java_imports(".", st, file_contents)

        controller_imports = result.get("com/example/controller/UserController.java", {})
        assert "UserService" in controller_imports
        assert controller_imports["UserService"] == "com/example/service/UserService.java::UserService"
        assert "User" in controller_imports
        assert controller_imports["User"] == "com/example/model/User.java::User"


class TestStaticImport:
    def test_static_import(self):
        st = _make_java_symbol_table()
        file_contents = {
            "com/example/app/App.java": (
                "package com.example.app;\n\n"
                "import static com.example.util.Constants.MAX_SIZE;\n\n"
                "public class App {\n"
                "}\n"
            ),
            "com/example/service/UserService.java": "",
            "com/example/model/User.java": "",
            "com/example/util/Constants.java": "",
            "com/example/service/OrderService.java": "",
        }
        st.add(SymbolEntry(
            fqn="com/example/app/App.java::App",
            file_path="com/example/app/App.java",
            name="App", symbol_type="class",
            line_start=5, line_end=6,
            signature="public class App",
            language="java",
        ))

        result = resolve_java_imports(".", st, file_contents)

        app_imports = result.get("com/example/app/App.java", {})
        assert "MAX_SIZE" in app_imports


class TestWildcardImport:
    def test_wildcard_import(self):
        st = _make_java_symbol_table()
        file_contents = {
            "com/example/app/App.java": (
                "package com.example.app;\n\n"
                "import com.example.service.*;\n\n"
                "public class App {\n"
                "}\n"
            ),
            "com/example/service/UserService.java": "",
            "com/example/model/User.java": "",
            "com/example/util/Constants.java": "",
            "com/example/service/OrderService.java": "",
        }
        st.add(SymbolEntry(
            fqn="com/example/app/App.java::App",
            file_path="com/example/app/App.java",
            name="App", symbol_type="class",
            line_start=5, line_end=6,
            signature="public class App",
            language="java",
        ))

        result = resolve_java_imports(".", st, file_contents)

        app_imports = result.get("com/example/app/App.java", {})
        # Should import all classes from service package
        assert "UserService" in app_imports
        assert "OrderService" in app_imports


class TestSamePackageImplicit:
    def test_same_package_implicit(self):
        """Classes in the same directory should be automatically visible."""
        st = _make_java_symbol_table()
        file_contents = {
            "com/example/service/UserService.java": "",
            "com/example/service/OrderService.java": "",
            "com/example/model/User.java": "",
            "com/example/util/Constants.java": "",
        }

        result = resolve_java_imports(".", st, file_contents)

        # UserService and OrderService are in the same package
        us_imports = result.get("com/example/service/UserService.java", {})
        assert "OrderService" in us_imports

        os_imports = result.get("com/example/service/OrderService.java", {})
        assert "UserService" in os_imports


class TestExternalImportSkipped:
    def test_external_import_skipped(self):
        """Imports of java.util.List and other stdlib should not appear."""
        st = _make_java_symbol_table()
        file_contents = {
            "com/example/app/App.java": (
                "package com.example.app;\n\n"
                "import java.util.List;\n"
                "import java.util.Map;\n"
                "import com.example.model.User;\n\n"
                "public class App {\n"
                "}\n"
            ),
            "com/example/service/UserService.java": "",
            "com/example/model/User.java": "",
            "com/example/util/Constants.java": "",
            "com/example/service/OrderService.java": "",
        }
        st.add(SymbolEntry(
            fqn="com/example/app/App.java::App",
            file_path="com/example/app/App.java",
            name="App", symbol_type="class",
            line_start=7, line_end=8,
            signature="public class App",
            language="java",
        ))

        result = resolve_java_imports(".", st, file_contents)

        app_imports = result.get("com/example/app/App.java", {})
        # java.util.List/Map are external, should not be in results
        assert "List" not in app_imports
        assert "Map" not in app_imports
        # But in-repo User should be there
        assert "User" in app_imports


class TestMixedPythonJavaRepo:
    def test_mixed_repo_imports(self, tmp_path):
        """Test resolve_imports works for mixed Python+Java repos."""
        # Python files
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "__init__.py").write_text("")
        (tmp_path / "src" / "utils.py").write_text(
            "def helper():\n    pass\n"
        )
        (tmp_path / "src" / "main.py").write_text(
            "from src.utils import helper\n\n"
            "def run():\n    helper()\n"
        )
        # Java files
        java_dir = tmp_path / "com" / "example"
        java_dir.mkdir(parents=True)
        (java_dir / "Service.java").write_text(
            "package com.example;\n\n"
            "public class Service {\n"
            "    public void run() {}\n"
            "}\n"
        )

        from src.code_index.symbol_table import build_symbol_table
        st = build_symbol_table(str(tmp_path))

        result = resolve_imports(str(tmp_path), st)

        # Python imports should still work
        assert "src/main.py" in result
        assert "helper" in result["src/main.py"]
