from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest_asyncio

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.shared.async_tasks import cancel_background_tasks


@pytest_asyncio.fixture(autouse=True)
async def _cleanup_managed_background_tasks():
    yield
    await cancel_background_tasks()
    await asyncio.sleep(0)
