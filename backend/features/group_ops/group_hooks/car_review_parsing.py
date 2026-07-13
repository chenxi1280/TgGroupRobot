"""车评模板、榜单指令与提交正文解析。"""
from __future__ import annotations

import datetime as dt
import html
import re
from dataclasses import dataclass

_PARSE_SCORE_VALUE_MAX = 100
_TEMPLATE_FIELD_RE = re.compile(r"\{([A-Za-z][A-Za-z0-9_]*)\}")


@dataclass(frozen=True)
class ParsedReview:
    review_text: str
    process_text: str | None
    scores: dict
    missing_labels: list[str]
    invalid_labels: list[str]


@dataclass(frozen=True)
class _ReviewTextValues:
    fields: dict[str, str]
    review_lines: list[str]
    explicit_review: str | None


def render_review_template(template_text: str, values: dict) -> str:
    def replace(match: re.Match[str]) -> str:
        value = values.get(match.group(1), "-")
        return "-" if value is None else html.escape(str(value))

    return _TEMPLATE_FIELD_RE.sub(replace, template_text or "")


def resolve_rank_request(text: str, rank_command: str) -> tuple[str, dt.datetime | None] | None:
    if not rank_command:
        return None
    now = dt.datetime.now(dt.UTC)
    periods = {
        rank_command: None,
        f"本周{rank_command}": now - dt.timedelta(days=7),
        f"本月{rank_command}": now - dt.timedelta(days=30),
    }
    since = periods.get(text)
    return (text, since) if text in periods else None


def parse_review_body(review_body: str, fields: list, *, require_fields: bool) -> ParsedReview:
    values = _collect_review_text_values(review_body, fields)
    scores, missing, invalid = _parse_field_values(
        values.fields,
        fields,
        require_fields=require_fields,
    )
    process_text = values.fields.get("process")
    review_text = _resolve_review_text(values, process_text=process_text)
    return ParsedReview(
        review_text=review_text,
        process_text=process_text,
        scores=scores,
        missing_labels=missing,
        invalid_labels=invalid,
    )


def _collect_review_text_values(review_body: str, fields: list) -> _ReviewTextValues:
    field_values: dict[str, str] = {}
    review_lines: list[str] = []
    explicit_review: str | None = None
    for raw_line in (review_body or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        key, value = match_field_line(line, fields)
        if key is not None:
            field_values[key] = value.strip()
            continue
        label, value = _split_label_value(line)
        if label in {"评价", "车评", "review"}:
            explicit_review = value
        else:
            review_lines.append(line)
    if not review_lines and review_body and not field_values and explicit_review is None:
        review_lines.append(review_body.strip())
    return _ReviewTextValues(field_values, review_lines, explicit_review)


def _parse_field_values(
    field_values: dict[str, str],
    fields: list,
    *,
    require_fields: bool,
) -> tuple[dict, list[str], list[str]]:
    scores: dict = {}
    missing_labels: list[str] = []
    invalid_labels: list[str] = []
    score_values: list[float] = []
    for field in fields:
        _apply_field_value(
            field,
            field_values,
            scores=scores,
            missing_labels=missing_labels,
            invalid_labels=invalid_labels,
            score_values=score_values,
            require_fields=require_fields,
        )
    if score_values:
        scores["total_score"] = _compact_number(sum(score_values) / len(score_values))
    return scores, missing_labels, invalid_labels


def _apply_field_value(
    field,
    field_values: dict[str, str],
    *,
    scores: dict,
    missing_labels: list[str],
    invalid_labels: list[str],
    score_values: list[float],
    require_fields: bool,
) -> None:
    field_key = getattr(field, "field_key", "")
    field_label = getattr(field, "field_label", field_key)
    raw_value = field_values.get(field_key, "")
    if not raw_value:
        if require_fields:
            missing_labels.append(field_label)
        return
    if not _is_score_field(field_key):
        scores[field_key] = raw_value
        return
    score_value = _parse_score_value(raw_value)
    if score_value is None:
        invalid_labels.append(field_label)
        return
    scores[field_key] = _compact_number(score_value)
    score_values.append(score_value)


def _resolve_review_text(values: _ReviewTextValues, *, process_text: str | None) -> str:
    review_text = (
        values.explicit_review
        if values.explicit_review is not None
        else "\n".join(values.review_lines).strip()
    )
    return review_text or process_text or ""


def match_field_line(line: str, fields: list) -> tuple[str | None, str]:
    sorted_fields = sorted(
        fields,
        key=lambda item: len(getattr(item, "field_label", "")),
        reverse=True,
    )
    for field in sorted_fields:
        match = _match_one_field(line, field)
        if match[0] is not None:
            return match
    return None, ""


def _match_one_field(line: str, field) -> tuple[str | None, str]:
    field_key = getattr(field, "field_key", "")
    field_label = getattr(field, "field_label", field_key)
    for label in (field_label, field_key):
        prefix = str(label).strip()
        if not prefix:
            continue
        if line == prefix:
            return field_key, ""
        if not line.startswith(prefix):
            continue
        rest = line[len(prefix):]
        stripped = rest.strip()
        if stripped.startswith((":", "：")):
            return field_key, stripped[1:].strip()
        if rest and rest[0].isspace():
            return field_key, stripped
    return None, ""


def _split_label_value(line: str) -> tuple[str, str]:
    for separator in ("：", ":"):
        if separator in line:
            label, value = line.split(separator, 1)
            return label.strip().lower(), value.strip()
    return line.strip().lower(), ""


def _is_score_field(field_key: str) -> bool:
    return field_key.endswith("_score") or field_key in {"score", "total_score"}


def _parse_score_value(raw_value: str) -> float | None:
    match = re.search(r"\d+(?:\.\d+)?", raw_value)
    if match is None:
        return None
    value = float(match.group(0))
    return value if 0 <= value <= _PARSE_SCORE_VALUE_MAX else None


def _compact_number(value: float) -> int | float:
    rounded = round(value, 2)
    return int(rounded) if rounded.is_integer() else rounded
