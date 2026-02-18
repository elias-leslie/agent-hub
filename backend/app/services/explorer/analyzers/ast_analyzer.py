"""AST analyzer for extracting Python code metrics.

Parses Python source files to extract function and class metadata
for code quality analysis.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path
from typing import TypedDict

logger = logging.getLogger(__name__)


class FunctionEntry(TypedDict):
    """Metadata for a function or method."""

    name: str
    lines: int
    start_line: int
    params: list[str]
    has_docstring: bool


class ClassEntry(TypedDict):
    """Metadata for a class."""

    name: str
    methods: list[str]
    lines: int
    start_line: int
    has_docstring: bool


class ParseResult(TypedDict):
    """Result of parsing a Python file."""

    functions: list[FunctionEntry]
    classes: list[ClassEntry]
    max_nesting: int


def _count_lines(node: ast.AST) -> int:
    """Count lines spanned by an AST node."""
    end_lineno = getattr(node, "end_lineno", None)
    lineno = getattr(node, "lineno", None)
    if end_lineno is not None and lineno is not None:
        return int(end_lineno - lineno + 1)
    return 0


def _has_docstring(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> bool:
    """Check if a function or class has a docstring."""
    if (
        node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    ):
        return isinstance(node.body[0].value.value, str)
    return False


def _get_param_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """Extract parameter names from a function definition."""
    params = []
    for arg in node.args.args:
        params.append(arg.arg)
    for arg in node.args.posonlyargs:
        params.append(arg.arg)
    for arg in node.args.kwonlyargs:
        params.append(arg.arg)
    if node.args.vararg:
        params.append(f"*{node.args.vararg.arg}")
    if node.args.kwarg:
        params.append(f"**{node.args.kwarg.arg}")
    return params


class NestingVisitor(ast.NodeVisitor):
    """Visitor to calculate maximum nesting depth."""

    def __init__(self) -> None:
        self.max_depth = 0
        self.current_depth = 0

    def visit_If(self, node: ast.If) -> None:
        self._visit_nesting_node(node)

    def visit_For(self, node: ast.For) -> None:
        self._visit_nesting_node(node)

    def visit_While(self, node: ast.While) -> None:
        self._visit_nesting_node(node)

    def visit_With(self, node: ast.With) -> None:
        self._visit_nesting_node(node)

    def visit_Try(self, node: ast.Try) -> None:
        self._visit_nesting_node(node)

    def _visit_nesting_node(self, node: ast.AST) -> None:
        self.current_depth += 1
        self.max_depth = max(self.max_depth, self.current_depth)
        self.generic_visit(node)
        self.current_depth -= 1


def _calculate_max_nesting(tree: ast.AST) -> int:
    """Calculate maximum nesting depth in the AST."""
    visitor = NestingVisitor()
    visitor.visit(tree)
    return visitor.max_depth


def parse_python_file(file_path: str | Path) -> ParseResult:
    """Parse a Python file and extract function/class metrics.

    Args:
        file_path: Path to Python source file

    Returns:
        ParseResult with functions, classes, and max_nesting

    Raises:
        FileNotFoundError: If file doesn't exist
        SyntaxError: If file has invalid Python syntax
    """
    path = Path(file_path)
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))

    functions: list[FunctionEntry] = []
    classes: list[ClassEntry] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            # Skip methods (they're handled with classes)
            # Check if parent is a class
            parent = getattr(node, "_parent", None)
            if parent is not None and isinstance(parent, ast.ClassDef):
                continue

            functions.append(
                FunctionEntry(
                    name=node.name,
                    lines=_count_lines(node),
                    start_line=node.lineno,
                    params=_get_param_names(node),
                    has_docstring=_has_docstring(node),
                )
            )

        elif isinstance(node, ast.ClassDef):
            methods = []
            for item in node.body:
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                    methods.append(item.name)

            classes.append(
                ClassEntry(
                    name=node.name,
                    methods=methods,
                    lines=_count_lines(node),
                    start_line=node.lineno,
                    has_docstring=_has_docstring(node),
                )
            )

    max_nesting = _calculate_max_nesting(tree)

    return ParseResult(
        functions=functions,
        classes=classes,
        max_nesting=max_nesting,
    )
