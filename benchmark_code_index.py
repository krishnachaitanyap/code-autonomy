#!/usr/bin/env python3
"""Benchmark each CodeIndex component individually."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

REPO = str(Path(__file__).parent)

def bench(label, fn):
    start = time.perf_counter()
    result = fn()
    elapsed = time.perf_counter() - start
    return elapsed, result

# 1. Symbol Table
print("=" * 60)
print("COMPONENT BENCHMARKS (90 files, ~15K lines)")
print("=" * 60)

from src.code_index.symbol_table import build_symbol_table
t, st = bench("Symbol Table", lambda: build_symbol_table(REPO))
print(f"1. Symbol Table:       {t:.3f}s  ({len(st)} symbols, {len(st.all_files)} files)")

# 2. Import Resolver
from src.code_index.import_resolver import resolve_imports
t2, im = bench("Import Resolver", lambda: resolve_imports(REPO, st))
total_imports = sum(len(v) for v in im.values())
print(f"2. Import Resolver:    {t2:.3f}s  ({len(im)} files with imports, {total_imports} resolved)")

# 3. Dependency Graph
from src.code_index.graph_builder import build_dependency_graph
t3, dg = bench("Dependency Graph", lambda: build_dependency_graph(REPO, st, im))
fwd_edges = sum(len(v) for v in dg.forward.values())
rev_edges = sum(len(v) for v in dg.reverse.values())
print(f"3. Dependency Graph:   {t3:.3f}s  ({len(dg.forward)} callers, {fwd_edges} fwd edges, {rev_edges} rev edges)")

# 4. Class Hierarchy
from src.code_index.hierarchy import build_class_hierarchy
t4, ch = bench("Class Hierarchy", lambda: build_class_hierarchy(st, im))
print(f"4. Class Hierarchy:    {t4:.3f}s  ({len(ch.parents)} classes with parents, {len(ch.children)} with children)")

# 5. Entity Embeddings (with sentence-transformers)
from src.code_index.entity_embeddings import EntityEmbeddings
def build_emb():
    e = EntityEmbeddings()
    e.build(REPO, st)
    return e
t5, emb = bench("Entity Embeddings", build_emb)
print(f"5. Entity Embeddings:  {t5:.3f}s  ({emb.count} entities embedded)")

# 6. Full build_code_index
from src.code_index.storage import build_code_index
t6, ci = bench("Full CodeIndex", lambda: build_code_index(REPO))
print(f"6. Full CodeIndex:     {t6:.3f}s  ({ci.total_symbols} symbols, {ci.total_files} files)")

# 7. Cache save + load
from src.code_index.storage import _save_code_index, _load_code_index
import tempfile
cache_dir = Path(tempfile.mkdtemp())
t7_save, _ = bench("Cache Save", lambda: _save_code_index(ci, cache_dir))
print(f"7. Cache Save:         {t7_save:.3f}s")

t7_load, loaded = bench("Cache Load", lambda: _load_code_index(ci.repo_id, cache_dir))
print(f"8. Cache Load:         {t7_load:.3f}s  ({loaded.total_symbols if loaded else 0} symbols)")

# 9. Tool queries
from src.code_index.tools import execute_code_index_tool
t8, _ = bench("find_callers", lambda: execute_code_index_tool(ci, "find_callers", {"symbol_name": "execute_tool"}))
print(f"9. find_callers:       {t8*1000:.2f}ms")

t9, _ = bench("find_dependents", lambda: execute_code_index_tool(ci, "find_dependents", {"file_path": "src/agent/tools.py"}))
print(f"10. find_dependents:   {t9*1000:.2f}ms")

t10, _ = bench("impact_analysis", lambda: execute_code_index_tool(ci, "impact_analysis", {"file_path": "src/agent/tools.py"}))
print(f"11. impact_analysis:   {t10*1000:.2f}ms")

t11, _ = bench("describe_entity", lambda: execute_code_index_tool(ci, "describe_entity", {"symbol_name": "build_agent_tools"}))
print(f"12. describe_entity:   {t11*1000:.2f}ms")

t12, _ = bench("find_similar", lambda: execute_code_index_tool(ci, "find_similar", {"query": "execute shell command safely"}))
print(f"13. find_similar:      {t12*1000:.2f}ms")

# Verification gate
from src.code_index.verifier import post_edit_verification_gate
t13, _ = bench("verify gate", lambda: post_edit_verification_gate(REPO, ["src/agent/tools.py"], ci, {}))
print(f"14. verify gate:       {t13*1000:.2f}ms")

print()
print("=" * 60)
print("EXTRAPOLATION TO 5000 FILES")
print("=" * 60)
scale = 5000 / 90
print(f"Scale factor: {scale:.1f}x (90 files → 5000 files)")
print()

# Linear components (file I/O + AST parsing)
print(f"Symbol Table:       {t * scale:.1f}s  (linear in files — AST parse each)")
print(f"Import Resolver:    {t2 * scale:.1f}s  (linear in files — AST parse for imports)")

# Call graph is O(files) for extraction + O(edges) for resolution
# Edges scale roughly quadratically in dense repos, but typically O(n*avg_degree)
edge_scale = scale * 3  # edges grow faster than files in larger repos
print(f"Dependency Graph:   {t3 * edge_scale:.1f}s  (O(files * avg_calls) — edge resolution)")

# Hierarchy is fast — only processes classes
print(f"Class Hierarchy:    {t4 * scale:.1f}s  (linear in classes)")

# Embeddings: model.encode() is the bottleneck — batch encoding scales linearly with entities
# But model load is fixed cost (~2s)
model_load_time = 2.0  # estimated fixed cost
encode_per_entity = (t5 - model_load_time) / max(emb.count, 1)
est_entities_5k = int(len(st) * scale)
print(f"Entity Embeddings:  {model_load_time + encode_per_entity * est_entities_5k:.1f}s  ({est_entities_5k} entities, model load ~2s fixed)")

# Total
total_no_emb = (t + t2) * scale + t3 * edge_scale + t4 * scale
total_with_emb = total_no_emb + model_load_time + encode_per_entity * est_entities_5k
print()
print(f"TOTAL (without embeddings):  {total_no_emb:.1f}s")
print(f"TOTAL (with embeddings):     {total_with_emb:.1f}s")
print(f"Cache load (any size):       {t7_load:.2f}s  (JSON parse, near-constant)")

print()
print("=" * 60)
print("BOTTLENECK ANALYSIS")
print("=" * 60)
pct_st = t / t6 * 100
pct_ir = t2 / t6 * 100
pct_dg = t3 / t6 * 100
pct_ch = t4 / t6 * 100
pct_emb = t5 / t6 * 100
print(f"Symbol Table:      {pct_st:5.1f}%")
print(f"Import Resolver:   {pct_ir:5.1f}%")
print(f"Dependency Graph:  {pct_dg:5.1f}%")
print(f"Class Hierarchy:   {pct_ch:5.1f}%")
print(f"Entity Embeddings: {pct_emb:5.1f}%  ← dominant cost")

# Cleanup
import shutil
shutil.rmtree(cache_dir)
