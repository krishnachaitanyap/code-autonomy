"""Project understanding and indexing."""
# Lazy re-exports to avoid circular imports at package init time.
# Direct imports from submodules (e.g., from src.consciousness.core import X) always work.


def __getattr__(name):
    import importlib

    _MODULE_MAP = {
        "ProjectConsciousness": "src.consciousness.core",
        "ConsciousnessStore": "src.consciousness.core",
        "FileConsciousnessStore": "src.consciousness.core",
        "build_consciousness": "src.consciousness.core",
        "build_or_load_consciousness": "src.consciousness.core",
        "get_store": "src.consciousness.core",
        "_format_structure": "src.consciousness.core",
    }

    if name in _MODULE_MAP:
        mod = importlib.import_module(_MODULE_MAP[name])
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
