"""Generate a readable square setup card for Binance Square."""
from __future__ import annotations

import logging
import math
import os
import tempfile
from typing import Tuple

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

WATERMARK = os.getenv("CARD_WATERMARK", "PozitiveHero")


def _get_font(size: int, bold: bool = False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _fmt_price(value: float) -> str:
    price = float(value)
    absolute = abs(price)
    if absolute >= 1000:
        return f"{price:.2f}"
    if absolute >= 1:
        return f"{price:.4f}".rstrip("0").rstrip(".")
    if absolute >= 0.01:
        return f"{price:.6f}".rstrip("0").rstrip(".")
    return f"{price:.10f}".rstrip("0").rstrip(".")


def _draw_pattern(draw: ImageDraw.ImageDraw, width: int, height: int) -> None:
    for x in range(-height, width * 2, 54):
        draw.line((x, 0, x + height, height), fill=(255, 255, 255, 10), width=1)
    for x in range(40, width, 90):
        for y in range(40, height, 90):
            radius = 7 + int(3 * math.sin((x + y) / 130))
            draw.ellipse(
                (x - radius, y - radius, x + radius, y + radius),
                outline=(255, 255, 255, 18),
                width=1,
            )


def _centered_text(draw, y: int, text: str, font, fill, width: int) -> int:
    box = draw.textbbox((0, 0), text, font=font)
    text_width = box[2] - box[0]
    draw.text(((width - text_width) / 2, y), text, font=font, fill=fill)
    return box[3] - box[1]


def generate_card(
    basic: str,
    direction: str,
    entry: float,
    tp1: float,
    tp2: float,
    tp3: float,
    stop: float,
    rr: float,
    confidence: float,
    change_1h: float,
) -> str:
    width, height = 1080, 1080
    image = Image.new("RGB", (width, height), (10, 15, 27))
    draw = ImageDraw.Draw(image, "RGBA")

    for y in range(height):
        ratio = y / max(height - 1, 1)
        draw.line(
            (0, y, width, y),
            fill=(
                int(10 + 12 * ratio),
                int(15 + 18 * ratio),
                int(27 + 26 * ratio),
                255,
            ),
        )
    _draw_pattern(draw, width, height)

    is_long = direction == "long"
    accent: Tuple[int, int, int, int] = (46, 204, 113, 255) if is_long else (255, 71, 87, 255)
    green = (46, 204, 113, 255)
    red = (255, 71, 87, 255)
    white = (246, 248, 252, 255)
    muted = (155, 166, 184, 255)
    panel = (17, 25, 42, 225)

    draw.rectangle((0, 0, width, 16), fill=accent)
    draw.rounded_rectangle((55, 48, width - 55, height - 55), radius=34, fill=(8, 13, 24, 150), outline=(255, 255, 255, 24), width=2)

    title_font = _get_font(76, bold=True)
    direction_font = _get_font(42, bold=True)
    section_font = _get_font(25, bold=True)
    value_font = _get_font(35, bold=True)
    small_font = _get_font(21, bold=False)
    footer_font = _get_font(18, bold=False)

    _centered_text(draw, 78, f"${basic.upper()}", title_font, white, width)
    _centered_text(draw, 170, "LONG SETUP" if is_long else "SHORT SETUP", direction_font, accent, width)

    def draw_metric(x: int, y: int, box_width: int, label: str, value: str, value_color=white) -> None:
        draw.rounded_rectangle((x, y, x + box_width, y + 116), radius=20, fill=panel, outline=(255, 255, 255, 20), width=1)
        draw.text((x + 20, y + 16), label, font=section_font, fill=muted)
        draw.text((x + 20, y + 55), value, font=value_font, fill=value_color)

    margin = 82
    gap = 22
    half = (width - 2 * margin - gap) // 2
    third = (width - 2 * margin - 2 * gap) // 3

    draw_metric(margin, 250, half, "ВХОД", _fmt_price(entry), white)
    draw_metric(margin + half + gap, 250, half, "СТОП", _fmt_price(stop), red)

    y_targets = 392
    draw_metric(margin, y_targets, third, "TP1", _fmt_price(tp1), green)
    draw_metric(margin + third + gap, y_targets, third, "TP2", _fmt_price(tp2), green)
    draw_metric(margin + 2 * (third + gap), y_targets, third, "TP3", _fmt_price(tp3), green)

    y_stats = 534
    draw_metric(margin, y_stats, third, "R/R", f"{rr:.2f}", (255, 214, 92, 255))
    draw_metric(margin + third + gap, y_stats, third, "SETUP SCORE", f"{confidence:.0f}/100", (100, 200, 255, 255))
    change_color = green if change_1h >= 0 else red
    draw_metric(margin + 2 * (third + gap), y_stats, third, "ИЗМ. 1H", f"{change_1h:+.2f}%", change_color)

    info_y = 706
    draw.rounded_rectangle((margin, info_y, width - margin, info_y + 150), radius=22, fill=panel, outline=(255, 255, 255, 20), width=1)
    draw.text((margin + 24, info_y + 20), "ТЕХНИЧЕСКИЙ ПЛАН", font=section_font, fill=accent)
    draw.text(
        (margin + 24, info_y + 62),
        "Уровни рассчитаны по ATR и структуре рынка.\nСетап отменяется при достижении стоп-уровня.",
        font=small_font,
        fill=white,
        spacing=10,
    )

    hashtag = f"#{basic.upper()}  #{'LONG' if is_long else 'SHORT'}  #TechnicalAnalysis"
    _centered_text(draw, 890, hashtag, small_font, muted, width)
    _centered_text(draw, 940, "Не финансовая рекомендация", footer_font, muted, width)

    watermark_box = draw.textbbox((0, 0), WATERMARK, font=footer_font)
    watermark_width = watermark_box[2] - watermark_box[0]
    draw.text((width - watermark_width - 78, height - 88), WATERMARK, font=footer_font, fill=(120, 130, 148, 150))

    temp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    path = temp.name
    temp.close()
    image.save(path, "PNG", optimize=True)
    logger.info("Card generated: %s", path)
    return path
