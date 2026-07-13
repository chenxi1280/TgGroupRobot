"""Schema Gate 的字段与外键契约比较。"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.schema import Column, Table

_POSTGRES_DIALECT = postgresql.dialect()
_SPACE_PATTERN = re.compile(r"\s+")
_CAST_PATTERN = re.compile(r"::[a-z ]+(?:\[\])?$")


def _normalize_type(value: Any) -> str:
    if hasattr(value, "compile"):
        rendered = value.compile(dialect=_POSTGRES_DIALECT)
    else:
        rendered = value
    normalized = _SPACE_PATTERN.sub(" ", str(rendered).strip().lower())
    aliases = {
        "timestamp with time zone": "timestamptz",
        "character varying": "varchar",
    }
    for source, target in aliases.items():
        normalized = normalized.replace(source, target)
    return normalized


def _normalize_default(value: Any) -> str | None:
    if value is None:
        return None
    normalized = _SPACE_PATTERN.sub(" ", str(value).strip().lower())
    normalized = _CAST_PATTERN.sub("", normalized).strip()
    while normalized.startswith("(") and normalized.endswith(")"):
        normalized = normalized[1:-1].strip()
    return normalized.strip("'\"")


def _model_default(column: Column) -> str | None:
    default = column.server_default
    return _normalize_default(default.arg) if default is not None else None


def _column_issues(table: Table, db_columns: dict[str, dict]) -> list[str]:
    issues: list[str] = []
    for column in table.columns:
        if column.info.get("schema_gate_optional", False):
            continue
        actual = db_columns.get(column.name)
        if actual is None:
            issues.append(f"缺少字段: {table.fullname}.{column.name}")
            continue
        issues.extend(_column_property_issues(table, column, actual))
    return issues


def _column_property_issues(table: Table, column: Column, actual: dict) -> list[str]:
    issues: list[str] = []
    prefix = f"{table.fullname}.{column.name}"
    actual_type = _normalize_type(actual["type"])
    expected_type = _normalize_type(column.type)
    if actual_type != expected_type:
        issues.append(f"字段类型不匹配: {prefix} expected={expected_type} actual={actual_type}")
    if bool(actual["nullable"]) != bool(column.nullable):
        issues.append(
            f"字段可空性不匹配: {prefix} expected={column.nullable} actual={actual['nullable']}"
        )
    expected_default = _model_default(column)
    actual_default = _normalize_default(actual.get("default"))
    if expected_default is not None and actual_default != expected_default:
        issues.append(
            f"字段默认值不匹配: {prefix} expected={expected_default} actual={actual_default}"
        )
    return issues


def _model_foreign_keys(table: Table) -> set[tuple]:
    result: set[tuple] = set()
    for constraint in table.foreign_key_constraints:
        elements = tuple(constraint.elements)
        targets = tuple(element.target_fullname.split(".") for element in elements)
        result.add((
            tuple(column.name for column in constraint.columns),
            tuple((parts[0], parts[1], parts[2]) for parts in targets),
            (elements[0].ondelete or "").upper(),
        ))
    return result


def _database_foreign_keys(inspector: Any, table: Table) -> set[tuple]:
    result: set[tuple] = set()
    for foreign_key in inspector.get_foreign_keys(table.name, schema=table.schema):
        schema = foreign_key.get("referred_schema") or table.schema
        referred_table = foreign_key["referred_table"]
        targets = tuple(
            (schema, referred_table, column)
            for column in foreign_key.get("referred_columns", ())
        )
        ondelete = (foreign_key.get("options", {}).get("ondelete") or "").upper()
        result.add((tuple(foreign_key.get("constrained_columns", ())), targets, ondelete))
    return result


def collect_table_contract_issues(inspector: Any, table: Table) -> list[str]:
    """返回单表的字段属性与外键差异。"""
    columns = inspector.get_columns(table.name, schema=table.schema)
    issues = _column_issues(table, {column["name"]: column for column in columns})
    actual_foreign_keys = _database_foreign_keys(inspector, table)
    for expected in sorted(_model_foreign_keys(table) - actual_foreign_keys):
        issues.append(f"缺少外键: {table.fullname} contract={expected}")
    return issues
