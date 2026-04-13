from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field


@dataclass
class SpamViolation:
    blocked: bool
    rule: str = ""
    detail: str = ""
    message_ids_to_delete: list[int] = field(default_factory=list)


@dataclass
class SpamMessageRecord:
    at: dt.datetime
    text_norm: str
    message_id: int
