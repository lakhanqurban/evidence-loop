from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SymbolInfo:
    name: str
    kind: str
    lineno: int
    end_lineno: int | None = None


def find_python_symbols(file_path: str | Path) -> list[SymbolInfo]:
    source = Path(file_path).read_text(encoding="utf-8")
    tree = ast.parse(source)
    symbols: list[SymbolInfo] = []

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.append(SymbolInfo(node.name, "function", node.lineno, getattr(node, "end_lineno", None)))
        elif isinstance(node, ast.ClassDef):
            symbols.append(SymbolInfo(node.name, "class", node.lineno, getattr(node, "end_lineno", None)))
    return symbols


def summarize_changed_file(file_path: str | Path) -> dict[str, object]:
    symbols = find_python_symbols(file_path)
    return {
        "path": str(file_path),
        "symbol_count": len(symbols),
        "symbols": [
            {
                "name": symbol.name,
                "kind": symbol.kind,
                "lineno": symbol.lineno,
                "end_lineno": symbol.end_lineno,
            }
            for symbol in symbols
        ],
    }
