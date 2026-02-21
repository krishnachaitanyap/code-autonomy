"""Tests for Java symbol extraction in src/code_index/symbol_table.py"""

import pytest
from unittest.mock import patch

from src.code_index.symbol_table import (
    SymbolEntry,
    SymbolTable,
    extract_java_symbols_from_source,
    build_symbol_table,
    _estimate_java_end_line,
)


# ---------------------------------------------------------------------------
# Java symbol extraction
# ---------------------------------------------------------------------------

class TestExtractSimpleClass:
    def test_extract_simple_class(self):
        source = """\
package com.example;

public class UserService {
    private String name;
}
"""
        entries = extract_java_symbols_from_source("com/example/UserService.java", source)
        assert len(entries) >= 1
        cls = [e for e in entries if e.name == "UserService"]
        assert len(cls) == 1
        assert cls[0].fqn == "com/example/UserService.java::UserService"
        assert cls[0].symbol_type == "class"
        assert cls[0].language == "java"
        assert cls[0].file_path == "com/example/UserService.java"


class TestExtractClassWithMethods:
    def test_extract_class_with_methods(self):
        source = """\
package com.example;

public class Calculator {
    public int add(int a, int b) {
        return a + b;
    }

    public int subtract(int a, int b) {
        return a - b;
    }
}
"""
        entries = extract_java_symbols_from_source("com/example/Calculator.java", source)
        names = {e.name for e in entries}
        assert "Calculator" in names
        assert "add" in names
        assert "subtract" in names

        # Verify method FQN
        add_entry = [e for e in entries if e.name == "add"][0]
        assert add_entry.fqn == "com/example/Calculator.java::Calculator.add"
        assert add_entry.parent_class == "com/example/Calculator.java::Calculator"
        assert add_entry.symbol_type == "method"
        assert len(add_entry.params) == 2
        assert add_entry.language == "java"


class TestExtractInterface:
    def test_extract_interface(self):
        source = """\
package com.example;

public interface Repository extends Serializable {
    void save(Object entity);
}
"""
        entries = extract_java_symbols_from_source("com/example/Repository.java", source)
        iface = [e for e in entries if e.name == "Repository"]
        assert len(iface) == 1
        assert iface[0].symbol_type == "class"  # stored as class for hierarchy
        assert "Serializable" in iface[0].bases
        assert iface[0].language == "java"


class TestExtractEnum:
    def test_extract_enum(self):
        source = """\
package com.example;

public enum Status {
    ACTIVE, INACTIVE, PENDING;
}
"""
        entries = extract_java_symbols_from_source("com/example/Status.java", source)
        enum_entry = [e for e in entries if e.name == "Status"]
        assert len(enum_entry) == 1
        assert enum_entry[0].symbol_type == "class"
        assert enum_entry[0].language == "java"


class TestExtractAnnotations:
    def test_extract_annotations(self):
        source = """\
package com.example;

import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api")
public class UserController {
    @GetMapping("/users")
    public List<User> getUsers() {
        return null;
    }
}
"""
        entries = extract_java_symbols_from_source("com/example/UserController.java", source)
        cls = [e for e in entries if e.name == "UserController"]
        assert len(cls) == 1
        assert "RestController" in cls[0].decorators

        method = [e for e in entries if e.name == "getUsers"]
        assert len(method) == 1
        assert "GetMapping" in method[0].decorators


class TestExtractInnerClass:
    def test_extract_inner_class(self):
        source = """\
package com.example;

public class Outer {
    public class Inner {
        public void doSomething() {}
    }
}
"""
        entries = extract_java_symbols_from_source("com/example/Outer.java", source)
        names = {e.name for e in entries}
        assert "Outer" in names
        assert "Inner" in names

        inner = [e for e in entries if e.name == "Inner"][0]
        assert inner.fqn == "com/example/Outer.java::Outer.Inner"


class TestExtractConstructor:
    def test_extract_constructor(self):
        source = """\
package com.example;

public class Service {
    public Service(String name) {
        this.name = name;
    }
}
"""
        entries = extract_java_symbols_from_source("com/example/Service.java", source)
        init = [e for e in entries if e.name == "<init>"]
        assert len(init) == 1
        assert init[0].fqn == "com/example/Service.java::Service.<init>"
        assert init[0].parent_class == "com/example/Service.java::Service"


class TestExtractGenerics:
    def test_extract_generics(self):
        source = """\
package com.example;

public class GenericService<T extends Entity> {
    public T findById(Long id) {
        return null;
    }
}
"""
        entries = extract_java_symbols_from_source("com/example/GenericService.java", source)
        cls = [e for e in entries if e.name == "GenericService"]
        assert len(cls) == 1
        assert cls[0].language == "java"


class TestSyntaxErrorReturnsEmpty:
    def test_syntax_error_returns_empty(self):
        source = "public class { broken syntax"
        entries = extract_java_symbols_from_source("Bad.java", source)
        assert entries == []


class TestJavalangNotInstalled:
    def test_javalang_not_installed(self):
        """Mock ImportError for javalang, verify graceful empty return."""
        import builtins
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "javalang":
                raise ImportError("No module named 'javalang'")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            entries = extract_java_symbols_from_source("Foo.java", "public class Foo {}")
            assert entries == []


class TestLargeMethodLineRange:
    def test_estimate_java_end_line(self):
        source = """\
public class Foo {
    public void bar() {
        if (true) {
            System.out.println("hello");
        }
    }
}
"""
        # bar() starts at line 2, should end at line 6
        end = _estimate_java_end_line(source, 2)
        assert end == 6

    def test_estimate_handles_strings_with_braces(self):
        source = """\
public class Foo {
    public String bar() {
        return "{ not a brace }";
    }
}
"""
        end = _estimate_java_end_line(source, 2)
        assert end == 4


# ---------------------------------------------------------------------------
# build_symbol_table with Java files
# ---------------------------------------------------------------------------

class TestBuildSymbolTableJava:
    def test_builds_java_from_directory(self, tmp_path):
        java_dir = tmp_path / "com" / "example"
        java_dir.mkdir(parents=True)
        (java_dir / "Hello.java").write_text(
            "package com.example;\n\n"
            "public class Hello {\n"
            "    public void greet() {}\n"
            "}\n"
        )
        (tmp_path / "main.py").write_text("def main():\n    pass\n")

        table = build_symbol_table(str(tmp_path))
        # Should have Python and Java symbols
        assert table.get_by_fqn("main.py::main") is not None
        # Java symbols should be present (if javalang is available)
        java_entries = [e for e in table.all_entries if e.language == "java"]
        # If javalang is installed, we should have at least class + method
        try:
            import javalang
            assert len(java_entries) >= 1
            assert any(e.name == "Hello" for e in java_entries)
        except ImportError:
            assert java_entries == []

    def test_builds_from_file_contents(self):
        """Test building symbol table from pre-read file contents."""
        file_contents = {
            "app.py": "def main():\n    pass\n",
            "Service.java": (
                "package com.example;\n\n"
                "public class Service {\n"
                "    public void run() {}\n"
                "}\n"
            ),
        }
        table = build_symbol_table(".", file_contents=file_contents)
        assert table.get_by_fqn("app.py::main") is not None

        try:
            import javalang
            assert table.get_by_fqn("Service.java::Service") is not None
        except ImportError:
            pass

    def test_language_field_serialization(self):
        """Test that language field round-trips through to_dict/from_dict."""
        table = SymbolTable()
        table.add(SymbolEntry(
            fqn="Foo.java::Foo", file_path="Foo.java", name="Foo",
            symbol_type="class", line_start=1, line_end=3,
            signature="public class Foo", language="java",
        ))
        table.add(SymbolEntry(
            fqn="bar.py::bar", file_path="bar.py", name="bar",
            symbol_type="function", line_start=1, line_end=2,
            signature="def bar()",
        ))

        data = table.to_dict()
        restored = SymbolTable.from_dict(data)

        java_entry = restored.get_by_fqn("Foo.java::Foo")
        assert java_entry is not None
        assert java_entry.language == "java"

        py_entry = restored.get_by_fqn("bar.py::bar")
        assert py_entry is not None
        assert py_entry.language == "python"
