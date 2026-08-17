"""Render v11.1 outcome cards from one fact-locked outcome object."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import math
import os
from pathlib import Path
import tempfile
from typing import Optional

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps
from matplotlib import font_manager

from runtime import PROJECT_DIR

logger = logging.getLogger(__name__)


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    try:
        prop = font_manager.FontProperties(family="DejaVu Sans", weight="bold" if bold else "normal")
        return ImageFont.truetype(font_manager.findfont(prop), size=size)
    except Exception:
        return ImageFont.load_default()


def _fmt_price(value: float) -> str:
    absolute = abs(float(value))
    if absolute >= 1000: decimals = 1
    elif absolute >= 100: decimals = 1
    elif absolute >= 10: decimals = 2
    elif absolute >= 1: decimals = 3
    elif absolute >= 0.1: decimals = 4
    elif absolute >= 0.01: decimals = 5
    elif absolute >= 0.001: decimals = 6
    else: decimals = 8
    return f"{float(value):.{decimals}f}".rstrip("0").rstrip(".")


def _avatar_path() -> Path:
    raw = (os.getenv("OUTCOME_AVATAR_PATH") or "assets/pozitivehero_avatar.png").strip()
    path = Path(raw).expanduser()
    return path if path.is_absolute() else PROJECT_DIR / path


def _rounded_avatar(path: Path, size: int = 94) -> Image.Image:
    image = Image.open(path).convert("RGB")
    image = ImageOps.fit(image, (size, size), method=Image.Resampling.LANCZOS, centering=(0.5, 0.35))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((2, 2, size - 2, size - 2), fill=255)
    ring = Image.new("RGBA", (size + 10, size + 10), (0, 0, 0, 0))
    ring_draw = ImageDraw.Draw(ring)
    ring_draw.ellipse((1, 1, size + 8, size + 8), fill=(35, 39, 46, 255))
    ring.paste(image.convert("RGBA"), (5, 5), mask)
    return ring


def generate_outcome_card(
    *,
    symbol: str,
    direction: str,
    event_kind: str,
    target_name: str = "",
    entry: float,
    reached_price: float,
    rr: float,
    move_pct: float,
    stop: Optional[float] = None,
    original_post_id: str = "",
    event_time: str = "",
) -> str:
    event_kind = str(event_kind or "")
    target_name = str(target_name or "").lower()
    if event_kind == "target_complete" and target_name != "tp3":
        raise ValueError("target_complete card requires TP3 as the reached target")
    if event_kind == "target" and target_name not in {"tp1", "tp2", "tp3"}:
        raise ValueError("partial target card requires TP1/TP2/TP3")

    width, height = 1080, 1350
    avatar_path = _avatar_path()
    if not avatar_path.is_file():
        raise FileNotFoundError(f"Outcome avatar not found: {avatar_path}")

    avatar = Image.open(avatar_path).convert("RGB")
    bg = ImageOps.fit(avatar, (width, height), method=Image.Resampling.LANCZOS, centering=(0.50, 0.38))
    bg = ImageEnhance.Contrast(bg).enhance(1.08)
    bg = ImageEnhance.Color(bg).enhance(0.75)
    bg = bg.filter(ImageFilter.GaussianBlur(radius=2.2))
    canvas = bg.convert("RGBA")

    success = event_kind in {"target", "target_complete"}
    accent = (38, 208, 155, 255) if success else (255, 82, 104, 255)
    accent_soft = (15, 96, 75, 130) if success else (105, 22, 34, 145)

    # Dark left-to-right overlay plus an accent glow behind the portrait.
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    px = overlay.load()
    for x in range(width):
        t = x / max(1, width - 1)
        alpha = int(242 - 105 * t)
        for y in range(height):
            px[x, y] = (3, 5, 8, alpha)
    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    gdraw.ellipse((520, 60, 1220, 760), fill=accent_soft)
    glow = glow.filter(ImageFilter.GaussianBlur(95))
    canvas = Image.alpha_composite(canvas, glow)
    canvas = Image.alpha_composite(canvas, overlay)

    draw = ImageDraw.Draw(canvas)
    margin = 64
    small_avatar = _rounded_avatar(avatar_path, 94)
    canvas.alpha_composite(small_avatar, (margin, 58))
    draw.text((margin + 125, 70), "PozitiveHero", font=_font(35, True), fill=(248, 249, 250, 255))
    try:
        if event_time:
            dt = datetime.fromisoformat(event_time.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            offset = int(os.getenv("ANALYTICS_TZ_OFFSET", "3"))
            shown_time = dt.astimezone(timezone(timedelta(hours=offset))).strftime("%d.%m.%Y  %H:%M")
        else:
            shown_time = ""
    except Exception:
        shown_time = ""
    draw.text((margin + 125, 116), shown_time, font=_font(22), fill=(170, 176, 186, 255))

    y = 300
    market = f"{symbol.upper()} / USDT"
    draw.text((margin, y), market, font=_font(61, True), fill=(250, 250, 251, 255))
    draw.text((margin, y + 82), direction.upper(), font=_font(33, True), fill=accent)

    if success:
        status = "TP3 · ALL TARGETS HIT" if event_kind == "target_complete" else f"{target_name.upper()} HIT"
        big_value = f"+{abs(rr):.2f}R"
        sub_value = f"{abs(move_pct):.2f}% move from entry"
    else:
        status = "SETUP INVALIDATED"
        big_value = "STOP HIT"
        sub_value = "risk boundary reached"
    draw.text((margin, y + 145), status, font=_font(33, True), fill=(235, 238, 241, 255))
    draw.text((margin, y + 245), big_value, font=_font(104, True), fill=accent)
    draw.text((margin, y + 365), sub_value, font=_font(31), fill=accent)

    label_font = _font(24)
    value_font = _font(39, True)
    row_y = 865
    draw.text((margin, row_y), "ENTRY", font=label_font, fill=(142, 149, 159, 255))
    draw.text((margin, row_y + 40), _fmt_price(entry), font=value_font, fill=(250, 250, 251, 255))
    draw.text((570, row_y), "REACHED" if success else "STOP", font=label_font, fill=(142, 149, 159, 255))
    draw.text((570, row_y + 40), _fmt_price(reached_price), font=value_font, fill=(250, 250, 251, 255))
    if success and stop is not None:
        draw.text((margin, row_y + 125), "RISK BOUNDARY", font=label_font, fill=(142, 149, 159, 255))
        draw.text((margin, row_y + 165), _fmt_price(stop), font=_font(31, True), fill=(205, 210, 217, 255))

    # Footer intentionally avoids referral/donation CTAs.
    draw.line((margin, 1160, width - margin, 1160), fill=(79, 85, 94, 255), width=2)
    draw.text((margin, 1206), "BINANCE SQUARE  ·  TRADE OUTCOME", font=_font(27, True), fill=(240, 185, 11, 255))
    draw.text((margin, 1252), "@PozitiveHero", font=_font(25), fill=(205, 210, 217, 255))
    if original_post_id:
        tail = str(original_post_id)[-10:]
        draw.text((width - margin - 245, 1252), f"setup · {tail}", font=_font(20), fill=(130, 138, 149, 255))

    handle = tempfile.NamedTemporaryFile(prefix="square_outcome_", suffix=".png", delete=False)
    path = handle.name
    handle.close()
    canvas.convert("RGB").save(path, format="PNG", optimize=True)
    return path
