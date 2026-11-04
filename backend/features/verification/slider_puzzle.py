from __future__ import annotations

import base64
import hashlib
import io
import random
import secrets

from PIL import Image, ImageDraw

WIDTH, HEIGHT, PIECE_SIZE = 320, 160, 48
MAX_POSITION = WIDTH - PIECE_SIZE
TOLERANCE = 4


def new_puzzle() -> tuple[str, str]:
    return secrets.token_hex(24), str(secrets.randbelow(MAX_POSITION - 95) + 80)


def puzzle_id(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()[:32]


def _png(image: Image.Image) -> str:
    data = io.BytesIO()
    image.save(data, format="PNG")
    return "data:image/png;base64," + base64.b64encode(data.getvalue()).decode()


def render_puzzle(seed: str, position: int) -> dict:
    rng = random.Random(seed)
    image = Image.new("RGB", (WIDTH, HEIGHT), "#b7d9d4")
    draw = ImageDraw.Draw(image)
    for row in range(HEIGHT):
        draw.line((0, row, WIDTH, row), fill=(125 + row // 3, 181 + row // 4, 178 + row // 5))
    for _ in range(28):
        x, y, radius = rng.randrange(WIDTH), rng.randrange(HEIGHT), rng.randrange(12, 65)
        color = rng.choice(("#427466", "#679685", "#8db39c", "#d8c99c", "#ece0bb"))
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)
    for _ in range(22):
        x, y = rng.randrange(WIDTH), rng.randrange(HEIGHT)
        draw.line((x, y, x + rng.randrange(8, 45), y + rng.randrange(5, 30)), fill="#f4efdb", width=2)
    top = rng.randrange(24, HEIGHT - PIECE_SIZE - 8)
    mask = Image.new("L", (PIECE_SIZE, PIECE_SIZE))
    shape = ImageDraw.Draw(mask)
    shape.rectangle((2, 10, 37, 45), fill=255)
    shape.ellipse((12, 1, 28, 17), fill=255)
    shape.ellipse((29, 20, 45, 36), fill=255)
    shape.ellipse((-6, 20, 10, 36), fill=0)
    piece = image.crop((position, top, position + PIECE_SIZE, top + PIECE_SIZE)).convert("RGBA")
    piece.putalpha(mask)
    image.paste("#264a41", (position, top), mask)
    return {
        "id": puzzle_id(seed), "background": _png(image), "piece": _png(piece),
        "width": WIDTH, "height": HEIGHT, "piece_size": PIECE_SIZE, "top": top,
    }
