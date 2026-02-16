"""Tests for src/code_index/symbol_table.py"""

import pytest

from src.code_index.symbol_table import (
    SymbolEntry,
    SymbolTable,
    extract_symbols_from_source,
    build_symbol_table,
)


# ---------------------------------------------------------------------------
# SymbolEntry creation
# ---------------------------------------------------------------------------

class TestSymbolEntry:
    def test_basic_creation(self):
        entry = SymbolEntry(
            fqn="src/foo.py::bar",
            file_path="src/foo.py",
            name="bar",
            symbol_type="function",
            line_start=10,
            line_end=20,
            signature="def bar(x: int) -> str",
        )
        assert entry.fqn == "src/foo.py::bar"
        assert entry.name == "bar"
        assert entry.symbol_type == "function"
        assert entry.line_start == 10
        assert entry.line_end == 20

    def test_method_with_parent(self):
        entry = SymbolEntry(
            fqn="src/foo.py::MyClass.method",
            file_path="src/foo.py",
            name="method",
            symbol_type="method",
            line_start=15,
            line_end=25,
            signature="def method(self)",
            parent_class="src/foo.py::MyClass",
        )
        assert entry.parent_class == "src/foo.py::MyClass"

    def test_class_with_bases(self):
        entry = SymbolEntry(
            fqn="src/foo.py::Child",
            file_path="src/foo.py",
            name="Child",
            symbol_type="class",
            line_start=1,
            line_end=30,
            signature="class Child(Base)",
            bases=["Base"],
        )
        assert entry.bases == ["Base"]


# ---------------------------------------------------------------------------
# SymbolTable lookups
# ---------------------------------------------------------------------------

class TestSymbolTable:
    @pytest.fixture
    def table(self):
        t = SymbolTable()
        t.add(SymbolEntry(
            fqn="a.py::foo", file_path="a.py", name="foo",
            symbol_type="function", line_start=1, line_end=5,
            signature="def foo()",
        ))
        t.add(SymbolEntry(
            fqn="b.py::foo", file_path="b.py", name="foo",
            symbol_type="function", line_start=10, line_end=20,
            signature="def foo(x)",
        ))
        t.add(SymbolEntry(
            fqn="a.py::Bar", file_path="a.py", name="Bar",
            symbol_type="class", line_start=7, line_end=30,
            signature="class Bar",
        ))
        return t

    def test_get_by_fqn(self, table):
        entry = table.get_by_fqn("a.py::foo")
        assert entry is not None
        assert entry.name == "foo"
        assert entry.file_path == "a.py"

    def test_get_by_fqn_not_found(self, table):
        assert table.get_by_fqn("nonexistent") is None

    def test_get_by_name_multiple(self, table):
        entries = table.get_by_name("foo")
        assert len(entries) == 2
        files = {e.file_path for e in entries}
        assert files == {"a.py", "b.py"}

    def test_get_by_name_not_found(self, table):
        assert table.get_by_name("nope") == []

    def test_get_by_file(self, table):
        entries = table.get_by_file("a.py")
        assert len(entries) == 2
        names = {e.name for e in entries}
        assert names == {"foo", "Bar"}

    def test_get_by_file_not_found(self, table):
        assert table.get_by_file("z.py") == []

    def test_len(self, table):
        assert len(table) == 3

    def test_all_fqns(self, table):
        assert table.all_fqns == {"a.py::foo", "b.py::foo", "a.py::Bar"}

    def test_all_files(self, table):
        assert table.all_files == {"a.py", "b.py"}

    def test_serialization_roundtrip(self, table):
        data = table.to_dict()
        restored = SymbolTable.from_dict(data)
        assert len(restored) == 3
        assert restored.get_by_fqn("a.py::foo") is not None
        assert restored.get_by_fqn("a.py::Bar") is not None


# ---------------------------------------------------------------------------
# AST extraction
# ---------------------------------------------------------------------------

class TestExtractSymbols:
    def test_extract_function(self):
        source = "def hello(name: str) -> str:\n    '''Say hello.'''\n    return f'Hello {name}'"
        entries = extract_symbols_from_source("mod.py", source)
        assert len(entries) == 1
        e = entries[0]
        assert e.fqn == "mod.py::hello"
        assert e.symbol_type == "function"
        assert e.name == "hello"
        assert e.line_start == 1
        assert "name: str" in e.params
        assert e.return_type == "str"
        assert e.docstring_summary == "Say hello."

    def test_extract_class_with_methods(self):
        source = (
            "class Animal:\n"
            "    '''An animal.'''\n"
            "    def speak(self) -> str:\n"
            "        '''Make a sound.'''\n"
            "        pass\n"
        )
        entries = extract_symbols_from_source("zoo.py", source)
        names = {e.name for e in entries}
        assert "Animal" in names
        assert "speak" in names

        animal = [e for e in entries if e.name == "Animal"][0]
        assert animal.symbol_type == "class"
        assert animal.docstring_summary == "An animal."

        speak = [e for e in entries if e.name == "speak"][0]
        assert speak.symbol_type == "method"
        assert speak.parent_class == "zoo.py::Animal"
        assert speak.docstring_summary == "Make a sound."

    def test_extract_async_function(self):
        source = "async def fetch(url: str) -> bytes:\n    pass"
        entries = extract_symbols_from_source("net.py", source)
        assert len(entries) == 1
        assert entries[0].symbol_type == "async function"

    def test_extract_class_with_bases(self):
        source = "class Dog(Animal):\n    pass"
        entries = extract_symbols_from_source("pets.py", source)
        assert len(entries) == 1
        assert entries[0].bases == ["Animal"]

    def test_extract_decorated_function(self):
        source = "@staticmethod\ndef helper():\n    pass"
        entries = extract_symbols_from_source("util.py", source)
        assert len(entries) == 1
        assert "staticmethod" in entries[0].decorators

    def test_syntax_error_returns_empty(self):
        entries = extract_symbols_from_source("bad.py", "def :")
        assert entries == []

    def test_empty_source(self):
        entries = extract_symbols_from_source("empty.py", "")
        assert entries == []


# ---------------------------------------------------------------------------
# build_symbol_table (integration-level, uses tmp_path)
# ---------------------------------------------------------------------------

class TestBuildSymbolTable:
    def test_builds_from_directory(self, tmp_path):
        (tmp_path / "mod.py").write_text("def greet():\n    pass\n\nclass Greeter:\n    pass\n")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "helper.py").write_text("def _internal():\n    pass\n")

        table = build_symbol_table(str(tmp_path))
        assert len(table) >= 3
        assert table.get_by_fqn("mod.py::greet") is not None
        assert table.get_by_fqn("mod.py::Greeter") is not None
        assert table.get_by_fqn("sub/helper.py::_internal") is not None

    def test_skips_non_python(self, tmp_path):
        (tmp_path / "data.json").write_text("{}")
        (tmp_path / "code.py").write_text("def func():\n    pass\n")
        table = build_symbol_table(str(tmp_path))
        assert len(table) == 1
