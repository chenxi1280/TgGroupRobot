from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping


class DeliveryStatus(str, Enum):
    pending = "pending"
    processing = "processing"
    retryable_failed = "retryable_failed"
    succeeded = "succeeded"
    permanent_failed = "permanent_failed"
    uncertain = "uncertain"
    cancelled = "cancelled"


MetadataItems = tuple[tuple[str, object], ...]


def _freeze_metadata(metadata: Mapping[str, object] | None) -> MetadataItems:
    if metadata is None:
        return ()
    return tuple(sorted(metadata.items()))


@dataclass(frozen=True, slots=True)
class DeliveryOutcome:
    status: DeliveryStatus
    message_id: int | None = None
    error_code: str | None = None
    message: str | None = None
    metadata: MetadataItems = ()

    @classmethod
    def success(
        cls,
        message_id: int | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> DeliveryOutcome:
        return cls(
            status=DeliveryStatus.succeeded,
            message_id=message_id,
            metadata=_freeze_metadata(metadata),
        )

    @classmethod
    def retryable_failure(cls, error_code: str, message: str) -> DeliveryOutcome:
        return cls(
            status=DeliveryStatus.retryable_failed,
            error_code=error_code,
            message=message,
        )

    @classmethod
    def permanent_failure(cls, error_code: str, message: str) -> DeliveryOutcome:
        return cls(
            status=DeliveryStatus.permanent_failed,
            error_code=error_code,
            message=message,
        )

    @classmethod
    def uncertain(cls, error_code: str, message: str) -> DeliveryOutcome:
        return cls(
            status=DeliveryStatus.uncertain,
            error_code=error_code,
            message=message,
        )
