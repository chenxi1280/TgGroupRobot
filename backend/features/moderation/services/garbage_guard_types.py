from __future__ import annotations

from dataclasses import dataclass, field

from backend.features.moderation.services.moderation_warning_service import WarningResult


@dataclass(frozen=True)
class GarbageViolation:
    rule_id: str
    rule: str
    detail: str
    message_ids_to_delete: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class GarbagePunishmentResult:
    applied: bool
    action_label: str
    warning: WarningResult | None = None
    threshold_reached: bool = False
    delete_requested: bool = False
    delete_applied: bool = False
    escalation_requested: bool = False
    escalation_applied: bool = False
