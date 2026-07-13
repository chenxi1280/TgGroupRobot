"""抽奖内定中奖人、奖品指派与引用解析。"""

from __future__ import annotations

import re

WINNER_FIELD_PREFIXES = (
    "内定中奖人",
    "内设中奖人",
    "预设中奖人",
    "指定中奖人",
    "中奖人员",
)
CONFIG_FIELD_NAMES = {
    "开奖时间",
    "最低积分",
    "参与费用",
    "最大人数",
    "满员人数",
    "入群天数",
    "邀请人数",
    "活跃消息数",
    "统计天数",
    "入围人数",
    "关注目标",
}
DIRECT_USER_ID_LINK_PATTERNS = (
    re.compile(r"tg://user\?id=(\d+)", flags=re.IGNORECASE),
    re.compile(r"tg://openmessage\?user_id=(\d+)", flags=re.IGNORECASE),
    re.compile(
        r"(?:https?://)?(?:t\.me|telegram\.me)/user\?id=(\d+)", flags=re.IGNORECASE
    ),
)
USERNAME_REFERENCE_PATTERNS = (
    re.compile(r"(?<![\w/])@([A-Za-z][A-Za-z0-9_]{4,31})"),
    re.compile(
        r"(?:https?://)?(?:t\.me|telegram\.me)/(?!user\?id=|c/|joinchat/|\+)(@?[A-Za-z][A-Za-z0-9_]{4,31})(?:[/?#]|$)",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"tg://resolve\?domain=([A-Za-z][A-Za-z0-9_]{4,31})", flags=re.IGNORECASE
    ),
)
CLEAR_WINNER_MARKERS = ("可选", "无", "不设置", "留空", "跳过", "随机", "0")
RANDOM_WINNER_MARKERS = {"随机", "不内定", "无", "跳过", "留空", "0"}
PRESET_PAIR_PARTS = 2


def split_config_line(line: str) -> tuple[str, str] | None:
    for separator in (":", "："):
        if separator in line:
            key, value = line.split(separator, 1)
            return key.strip(), value.strip()
    return None


def is_winner_field(line: str) -> bool:
    split = split_config_line(line)
    return split is not None and split[0] in WINNER_FIELD_PREFIXES


def parse_direct_winner_ids(value: str) -> list[int]:
    ids: list[int] = []
    for pattern in DIRECT_USER_ID_LINK_PATTERNS:
        for match in pattern.finditer(value):
            _append_unique_positive(ids, int(match.group(1)))
    for raw_token in re.split(r"[\s,，、;；\n]+", value):
        token = raw_token.strip().strip("<>()[]{}，,。.;；")
        if re.fullmatch(r"\d+", token):
            _append_unique_positive(ids, int(token))
    return ids


def _append_unique_positive(values: list[int], value: int) -> None:
    if value > 0 and value not in values:
        values.append(value)


def extract_winner_usernames(value: str) -> list[str]:
    usernames: list[str] = []
    seen: set[str] = set()
    for pattern in USERNAME_REFERENCE_PATTERNS:
        for match in pattern.finditer(value):
            username = match.group(1).lstrip("@")
            normalized = username.lower()
            if normalized not in seen:
                seen.add(normalized)
                usernames.append(username)
    return usernames


def collect_winner_reference_values(text: str) -> list[str]:
    values: list[str] = []
    winner_block = False
    for raw_line in text.strip().split("\n")[1:]:
        line = raw_line.strip()
        if not line:
            continue
        if line == "奖品:":
            winner_block = False
            continue
        split_line = split_config_line(line)
        if is_winner_field(line):
            field_value = split_line[1]
            if field_value:
                values.append(field_value)
            else:
                winner_block = True
            continue
        if winner_block and (
            split_line is None or split_line[0] not in CONFIG_FIELD_NAMES
        ):
            values.append(line)
        elif winner_block:
            winner_block = False
    return values


def _parse_winner_ids(value: str, *, allow_unresolved_refs: bool = False) -> list[int]:
    ids = parse_direct_winner_ids(value)
    usernames = extract_winner_usernames(value)
    has_content = bool(value.strip()) and not any(
        marker in value for marker in CLEAR_WINNER_MARKERS
    )
    if usernames and not allow_unresolved_refs:
        raise ValueError(
            "内定中奖人如使用 @用户名或用户链接，请通过分步创建发送，或填写数字用户ID"
        )
    if has_content and not ids and not usernames and not allow_unresolved_refs:
        raise ValueError("内定中奖人请填写 Telegram 数字用户ID，多个ID用逗号分隔")
    return ids


def validate_unique_prize_names(prizes: list[dict]) -> None:
    seen: set[str] = set()
    duplicates: list[str] = []
    for prize in prizes:
        name = str(prize.get("name") or "").strip()
        if name and name in seen and name not in duplicates:
            duplicates.append(name)
        if name:
            seen.add(name)
    if duplicates:
        raise ValueError("奖品名称不能重复：" + "、".join(duplicates))


def _prize_names(prizes: list[dict]) -> set[str]:
    return {
        str(prize.get("name") or "").strip()
        for prize in prizes
        if str(prize.get("name") or "").strip()
    }


def _split_preset_assignment_value(
    value: str, prizes: list[dict]
) -> tuple[str | None, str]:
    text = value.strip()
    prize_names = sorted(_prize_names(prizes), key=len, reverse=True)
    for prize_name in prize_names:
        for separator in (":", "：", "=", "＝"):
            prefix = f"{prize_name}{separator}"
            if text.startswith(prefix):
                return prize_name, text[len(prefix) :].strip()
    _raise_if_malformed_preset_assignment(text, prize_names)
    return None, text


def _has_winner_reference(value: str) -> bool:
    return bool(parse_direct_winner_ids(value) or extract_winner_usernames(value))


def _format_available_prize_names(prize_names: list[str]) -> str:
    return "、".join(prize_names) if prize_names else "无"


def _raise_if_malformed_preset_assignment(text: str, prize_names: list[str]) -> None:
    if not text or re.match(r"^(?:https?|tg)://", text, flags=re.IGNORECASE):
        return
    separator_match = re.match(r"^([^:：=＝]{1,80})\s*[:：=＝]\s*(.+)$", text)
    if separator_match and _has_winner_reference(
        separator_match.group(PRESET_PAIR_PARTS)
    ):
        prize_name = separator_match.group(1).strip()
        available = _format_available_prize_names(prize_names)
        raise ValueError(f"内定中奖奖品不存在：{prize_name}。可用奖品：{available}")
    parts = text.split(maxsplit=1)
    if len(parts) != PRESET_PAIR_PARTS:
        return
    maybe_prize, winner_value = parts
    if not _has_winner_reference(winner_value) or _has_winner_reference(maybe_prize):
        return
    if maybe_prize in prize_names:
        raise ValueError(f"指定奖品请使用格式：{maybe_prize}: 用户")
    available = _format_available_prize_names(prize_names)
    raise ValueError(
        f"内定中奖奖品不存在：{maybe_prize}。"
        f"如需指定奖品，请使用格式：奖品名称: 用户；可用奖品：{available}"
    )


def _prize_quantity_by_name(prizes: list[dict]) -> dict[str, int]:
    quantities: dict[str, int] = {}
    for prize in prizes:
        name = str(prize.get("name") or "").strip()
        if name:
            quantities[name] = quantities.get(name, 0) + int(
                prize.get("quantity", 1) or 1
            )
    return quantities


def validate_preset_winner_assignments(
    assignments: list[dict], prizes: list[dict]
) -> None:
    if not assignments:
        return
    quantity_by_name = _prize_quantity_by_name(prizes)
    counts: dict[str, int] = {}
    for item in assignments:
        prize_name = str(item.get("prize_name") or "").strip()
        if prize_name not in quantity_by_name:
            raise ValueError(f"内定中奖奖品不存在：{prize_name}")
        counts[prize_name] = counts.get(prize_name, 0) + 1
    for prize_name, count in counts.items():
        if count > quantity_by_name[prize_name]:
            raise ValueError(f"内定中奖人超过奖品「{prize_name}」的中奖人数")


def _append_assignment(
    assignments: list[dict],
    winner_ids: list[int],
    *,
    user_id: int,
    prize_name: str | None,
) -> None:
    if user_id not in winner_ids:
        winner_ids.append(user_id)
    assigned = any(int(item.get("user_id") or 0) == user_id for item in assignments)
    if prize_name is not None and not assigned:
        assignments.append({"user_id": user_id, "prize_name": prize_name})


def parse_preset_winner_values(
    values: list[str],
    prizes: list[dict],
    *,
    allow_unresolved_refs: bool = False,
) -> tuple[list[int], list[dict]]:
    winner_ids: list[int] = []
    assignments: list[dict] = []
    require_assignment = len(_prize_names(prizes)) > 1
    for value in values:
        prize_name, winner_value = _split_preset_assignment_value(value, prizes)
        winner_value = winner_value.strip()
        if not winner_value or winner_value in RANDOM_WINNER_MARKERS:
            continue
        if (
            require_assignment
            and prize_name is None
            and _has_winner_reference(winner_value)
        ):
            raise ValueError(
                "多个奖品时，请逐个奖品设置内定中奖人，格式：奖品名称: 用户；"
                "不指定的奖品请写：奖品名称: 随机"
            )
        parsed_ids = _parse_winner_ids(
            winner_value,
            allow_unresolved_refs=allow_unresolved_refs,
        )
        for user_id in parsed_ids:
            _append_assignment(
                assignments,
                winner_ids,
                user_id=user_id,
                prize_name=prize_name,
            )
    validate_preset_winner_assignments(assignments, prizes)
    return winner_ids, assignments
