"""Production Python structural quality gate."""
from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

MAX_FILE_LINES = 500
MAX_FUNCTION_LINES = 50
MAX_NESTING_DEPTH = 3
MAX_POSITIONAL_PARAMETERS = 3
MAX_CYCLOMATIC_COMPLEXITY = 10
ALLOWED_COMPARISON_NUMBERS = frozenset({-1, 0, 1})
FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef
NESTING_NODES = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With, ast.AsyncWith, ast.Match)


@dataclass(frozen=True)
class MetricViolation:
    path: Path
    line: int
    rule: str
    detail: str

    def format(self) -> str:
        return f"{self.path}:{self.line}: {self.rule} {self.detail}"


def _function_line_count(node: FunctionNode, lines: list[str]) -> int:
    end_line = getattr(node, "end_lineno", getattr(node, "lineno", 1))
    return sum(bool(line.strip()) for line in lines[node.lineno - 1:end_line])


def _positional_parameter_count(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    parameters = [*node.args.posonlyargs, *node.args.args]
    if parameters and parameters[0].arg in {"self", "cls"}:
        parameters = parameters[1:]
    return len(parameters)


class _FunctionMetricVisitor(ast.NodeVisitor):
    def __init__(self, target: ast.AST) -> None:
        self.target = target
        self.complexity = 1
        self.max_nesting = 0
        self.magic_comparisons: list[tuple[int, int | float]] = []
        self._nesting = 0

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node is self.target:
            self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        if node is self.target:
            self.generic_visit(node)

    def generic_visit(self, node: ast.AST) -> None:
        is_nested = isinstance(node, NESTING_NODES)
        if is_nested:
            self._nesting += 1
            self.max_nesting = max(self.max_nesting, self._nesting)
        self.complexity += _complexity_increment(node)
        if isinstance(node, ast.Compare):
            self.magic_comparisons.extend(_magic_comparison_values(node))
        super().generic_visit(node)
        if is_nested:
            self._nesting -= 1


def _complexity_increment(node: ast.AST) -> int:
    if isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.IfExp)):
        return 1
    if isinstance(node, ast.Try):
        return len(node.handlers) + bool(node.orelse)
    if isinstance(node, ast.BoolOp):
        return max(len(node.values) - 1, 0)
    if isinstance(node, ast.Match):
        return len(node.cases)
    if isinstance(node, ast.comprehension):
        return 1 + len(node.ifs)
    return 0


def _numeric_value(node: ast.AST) -> int | float | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        value = _numeric_value(node.operand)
        return -value if value is not None else None
    return None


def _magic_comparison_values(node: ast.Compare) -> list[tuple[int, int | float]]:
    values = []
    for operand in (node.left, *node.comparators):
        value = _numeric_value(operand)
        if value is not None and value not in ALLOWED_COMPARISON_NUMBERS:
            values.append((operand.lineno, value))
    return values


def _function_violations(
    path: Path, node: FunctionNode, lines: list[str]
) -> list[MetricViolation]:
    name = getattr(node, "name", "<function>")
    visitor = _FunctionMetricVisitor(node)
    visitor.visit(node)
    values = (
        ("QF001", _function_line_count(node, lines), MAX_FUNCTION_LINES, "nonblank lines"),
        ("QF002", visitor.max_nesting, MAX_NESTING_DEPTH, "nesting depth"),
        ("QF003", _positional_parameter_count(node), MAX_POSITIONAL_PARAMETERS, "positional parameters"),
        ("QF004", visitor.complexity, MAX_CYCLOMATIC_COMPLEXITY, "cyclomatic complexity"),
    )
    violations = [
        MetricViolation(path, node.lineno, rule, f"{name}: {label} {actual} > {limit}")
        for rule, actual, limit, label in values
        if actual > limit
    ]
    violations.extend(
        MetricViolation(path, line, "QF005", f"{name}: unnamed comparison number {value}")
        for line, value in visitor.magic_comparisons
    )
    return violations


def inspect_python_file(path: Path) -> list[MetricViolation]:
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    violations = []
    if len(lines) > MAX_FILE_LINES:
        violations.append(MetricViolation(path, 1, "QF000", f"file lines {len(lines)} > {MAX_FILE_LINES}"))
    tree = ast.parse(source, filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            violations.extend(_function_violations(path, node, lines))
    return violations


def inspect_paths(paths: Iterable[Path]) -> list[MetricViolation]:
    violations = []
    for path in sorted(paths):
        violations.extend(inspect_python_file(path))
    return violations


def inspect_backend(root: Path) -> list[MetricViolation]:
    return inspect_paths((root / "backend").rglob("*.py"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=Path.cwd())
    args = parser.parse_args()
    violations = inspect_backend(args.root.resolve())
    for violation in violations:
        print(violation.format())
    print(f"quality metric violations: {len(violations)}")
    return int(bool(violations))


if __name__ == "__main__":
    raise SystemExit(main())
