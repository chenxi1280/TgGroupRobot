from __future__ import annotations

import asyncio
import json
import secrets
from pathlib import Path

from backend.shared.services.base import ValidationError

ENGINE = Path(__file__).resolve().parents[4] / "miniapp" / "dist-room" / "engine.mjs"
# Conservative per-seat bound: 3 capped wins + 3 capped flower-pig
# payments, 12 opponent kongs and 3 transfers of up to 6 points.
RESERVE_UNITS = 3 * 16 + 3 * 16 + 12 * 2 + 3 * 6


async def mahjong(op: str, **payload) -> dict:
    process = await asyncio.create_subprocess_exec(
        "node", str(ENGINE), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
    )
    raw = json.dumps({"op": op, "seed": secrets.randbits(32), **payload}).encode()
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(raw), timeout=8)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise
    if process.returncode:
        raise RuntimeError("Sichuan engine exited unsuccessfully")
    result = json.loads(stdout)
    if error := result.get("error"):
        raise ValidationError(error)
    return result
