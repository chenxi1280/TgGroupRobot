from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest_asyncio
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.shared.async_tasks import cancel_background_tasks


@pytest.fixture(autouse=True)
def _isolate_fake_callback_receipts():
    # Tests reuse synthetic callback IDs; real Telegram callback IDs are unique.
    # Object-ID fallbacks on tiny query doubles may also be recycled by Python.
    from backend.platform.telegram.errors import _ANSWERED_CALLBACK_IDS, _ANSWERED_CALLBACK_QUEUE
    _ANSWERED_CALLBACK_IDS.clear()
    _ANSWERED_CALLBACK_QUEUE.clear()
    yield
    _ANSWERED_CALLBACK_IDS.clear()
    _ANSWERED_CALLBACK_QUEUE.clear()


@pytest_asyncio.fixture(autouse=True)
async def _cleanup_managed_background_tasks():
    yield
    await cancel_background_tasks()
    await asyncio.sleep(0)
