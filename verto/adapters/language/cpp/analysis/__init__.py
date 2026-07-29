"""AST analysis (libclang) — split by concern: parse infra (`parse`), type analysis
(`types`), site detection (`detect`), and correctness-completeness safety checks
(`safety`). Public API re-exported here so callers use `...cpp.analysis.<name>`
regardless of which submodule owns it.
"""
from .parse import parse_errors, set_parse_args
from .types import _clean_type, aggregate_fields, qualified_name, signature
from .detect import (all_fuse, all_growth, all_list, all_map, all_string_growth,
                     all_umap_growth, byval_in_ast, byval_params, fuse_ast, fuse_in_ast,
                     all_functions, func_span, growth_ast, growth_in_ast, list_ast,
                     list_in_ast, map_ast,
                     map_in_ast, string_growth_in_ast, umap_growth_in_ast)
from .pointers import pointer_length_pairs
from .safety import side_effect_reason, template_candidates

__all__ = ["set_parse_args", "parse_errors", "signature", "qualified_name", "aggregate_fields", "_clean_type",
           "all_growth", "growth_ast", "growth_in_ast",
           "all_string_growth", "string_growth_in_ast",
           "all_map", "map_ast", "map_in_ast",
           "all_umap_growth", "umap_growth_in_ast",
           "all_list", "list_ast", "list_in_ast",
           "all_fuse", "fuse_ast", "fuse_in_ast", "func_span", "all_functions",
           "byval_params", "byval_in_ast", "pointer_length_pairs",
           "side_effect_reason", "template_candidates"]
