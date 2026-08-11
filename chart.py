"""Audience Author v9 candlestick renderer.

The renderer deliberately rotates visual composition instead of publishing the
same orange-line/green-zone card every 20 minutes.  All price levels come from
Python's validated public trade plan.
"""
from __future__ import annotations

import logging
import os
import re
import tempfile
from typing import Optional

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)
WATERMARK = os.getenv("CHART_WATERMARK", "PozitiveHero")

BG = "#0f1216"
GRID = "#1e242c"
TEXT = "#e7ebf1"
MUTED = "#8b93a1"
GREEN = "#26de81"
RED = "#ff4757"
ORANGE = "#f5a623"
BLUE = "#4a90e2"
VWAP_COLOR = "#ff8c69"
PANEL = "#111820"


def _fmt_price(value: float) -> str:
    price = float(value)
    absolute = abs(price)
    if absolute >= 1000:
        decimals = 1
    elif absolute >= 100:
        decimals = 1
    elif absolute >= 10:
        decimals = 2
    elif absolute >= 1:
        decimals = 3
    elif absolute >= 0.1:
        decimals = 4
    elif absolute >= 0.01:
        decimals = 5
    elif absolute >= 0.001:
        decimals = 6
    else:
        decimals = 8
    return f"{price:.{decimals}f}".rstrip("0").rstrip(".")


def _to_df(raw_data) -> Optional[pd.DataFrame]:
    if raw_data is None:
        return None
    if isinstance(raw_data, pd.DataFrame):
        frame = raw_data.copy()
        if not isinstance(frame.index, pd.DatetimeIndex):
            if "timestamp" not in frame.columns:
                return None
            frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
            frame.set_index("timestamp", inplace=True)
    else:
        try:
            frame = pd.DataFrame(
                raw_data,
                columns=[
                    "timestamp", "open", "high", "low", "close", "volume", "close_time",
                    "quote_asset_volume", "number_of_trades", "taker_buy_base_asset_volume",
                    "taker_buy_quote_asset_volume", "ignore",
                ],
            )
            frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="ms", utc=True)
            frame.set_index("timestamp", inplace=True)
        except Exception as exc:
            logger.error("Chart dataframe build failed: %s", exc)
            return None

    required = ("open", "high", "low", "close", "volume")
    if any(column not in frame.columns for column in required):
        return None
    for column in required:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame[list(required)].dropna().sort_index()
    frame = frame[~frame.index.duplicated(keep="last")]
    return frame if len(frame) >= 30 else None


def _draw_candles(price_axis, volume_axis, frame: pd.DataFrame) -> None:
    x_values = mdates.date2num(frame.index.to_pydatetime())
    candle_width = float(np.median(np.diff(x_values))) * 0.68 if len(x_values) > 1 else 0.006
    for x, (_, row) in zip(x_values, frame.iterrows()):
        bullish = row["close"] >= row["open"]
        color = GREEN if bullish else RED
        price_axis.vlines(x, row["low"], row["high"], color=color, linewidth=0.8, alpha=0.95)
        body_low = min(row["open"], row["close"])
        body_height = max(
            abs(row["close"] - row["open"]),
            max((row["high"] - row["low"]) * 0.025, abs(row["close"]) * 1e-8),
        )
        price_axis.add_patch(
            Rectangle(
                (x - candle_width / 2, body_low), candle_width, body_height,
                facecolor=color, edgecolor=color, linewidth=0.7, alpha=0.95,
            )
        )
        volume_axis.bar(x, row["volume"], width=candle_width, color=color, alpha=0.50, align="center")


def _decision_caption(mode: str) -> str:
    return {
        "at_level": "КЛЮЧЕВАЯ ЦЕНА",
        "retest_hold": "ВОЗВРАТ К УРОВНЮ",
        "retest_reject": "ВОЗВРАТ К УРОВНЮ",
        "breakout_confirm": "ЗАКРЕПЛЕНИЕ ВЫШЕ",
        "breakdown_confirm": "ЗАКРЕПЛЕНИЕ НИЖЕ",
    }.get(str(mode), "КЛЮЧЕВАЯ ЦЕНА")


def generate_chart(
    symbol: str,
    raw_data,
    basic: str,
    *,
    entry: Optional[float] = None,
    entry_zone_low: Optional[float] = None,
    entry_zone_high: Optional[float] = None,
    tp1: Optional[float] = None,
    tp2: Optional[float] = None,
    tp3: Optional[float] = None,
    stop: Optional[float] = None,
    direction: str = "long",
    support: Optional[float] = None,
    resistance: Optional[float] = None,
    decision_level: Optional[float] = None,
    decision_mode: str = "at_level",
    vol_rel: Optional[float] = None,
    indicator=None,
    visual_style: str = "clean_chart",
    headline: str = "",
    signal_label: str = "",
) -> Optional[str]:
    del symbol, support, resistance
    frame = _to_df(raw_data)
    if frame is None:
        return None
    frame = frame.tail(90).copy()

    styles = {
        "minimal_chart", "event_chart", "trade_map", "scenario_chart",
        "context_chart", "clean_chart",
    }
    style = visual_style if visual_style in styles else "clean_chart"

    frame["EMA20"] = frame["close"].ewm(span=20, adjust=False).mean()
    typical = (frame["high"] + frame["low"] + frame["close"]) / 3.0
    frame["VWAP"] = (typical * frame["volume"]).cumsum() / frame["volume"].cumsum().replace(0, np.nan)

    temp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    path = temp.name
    temp.close()
    figure = None

    try:
        figure = plt.figure(figsize=(9, 8), facecolor=BG)
        grid = figure.add_gridspec(5, 1, hspace=0.06)
        price_axis = figure.add_subplot(grid[:4, 0])
        volume_axis = figure.add_subplot(grid[4, 0], sharex=price_axis)

        for axis in (price_axis, volume_axis):
            axis.set_facecolor(BG)
            axis.grid(True, color=GRID, linewidth=0.65, alpha=0.72)
            axis.tick_params(colors=MUTED, labelsize=8)
            for spine in axis.spines.values():
                spine.set_color(GRID)

        _draw_candles(price_axis, volume_axis, frame)

        # Rotate information density. The chart should add information instead of
        # repeating the same dashboard skeleton in every Square post.
        if style == "minimal_chart":
            price_axis.plot(frame.index, frame["EMA20"], color=ORANGE, linewidth=1.10, alpha=0.82, label="EMA20")
        elif style == "event_chart":
            price_axis.plot(frame.index, frame["EMA20"], color=ORANGE, linewidth=1.20, label="EMA20")
        elif style == "trade_map":
            price_axis.plot(frame.index, frame["EMA20"], color=ORANGE, linewidth=1.05, alpha=0.85, label="EMA20")
            price_axis.plot(frame.index, frame["VWAP"], color=VWAP_COLOR, linewidth=0.90, linestyle="-.", alpha=0.85, label="VWAP")
        elif style == "context_chart":
            price_axis.plot(frame.index, frame["VWAP"], color=VWAP_COLOR, linewidth=1.05, linestyle="-.", label="VWAP")
        else:
            price_axis.plot(frame.index, frame["EMA20"], color=ORANGE, linewidth=1.15, label="EMA20")
            price_axis.plot(frame.index, frame["VWAP"], color=VWAP_COLOR, linewidth=0.88, linestyle="-.", alpha=0.80, label="VWAP")

        current_price = float(frame["close"].iloc[-1])
        decision = float(decision_level if decision_level is not None else (entry if entry is not None else current_price))

        # Entry-zone band is visible only where it is actually useful.
        if style in {"trade_map", "scenario_chart"} and entry_zone_low is not None and entry_zone_high is not None:
            low, high = sorted((float(entry_zone_low), float(entry_zone_high)))
            price_axis.axhspan(low, high, color=BLUE, alpha=0.10)

        # Risk/reward shading varies by style; minimal/event charts stay clean.
        if style in {"trade_map", "scenario_chart", "clean_chart"} and entry is not None and stop is not None:
            price_axis.axhspan(min(float(entry), float(stop)), max(float(entry), float(stop)), color=RED, alpha=0.055)
        if style in {"trade_map", "scenario_chart", "clean_chart"} and entry is not None and tp1 is not None:
            price_axis.axhspan(min(float(entry), float(tp1)), max(float(entry), float(tp1)), color=GREEN, alpha=0.045)

        shown_levels: list[tuple[float, str, str]] = []

        def add_level(value, label: str, color: str, linestyle: str = "--", width: float = 1.2) -> None:
            if value is None:
                return
            numeric = float(value)
            price_axis.axhline(numeric, color=color, linestyle=linestyle, linewidth=width, alpha=0.95)
            shown_levels.append((numeric, f"{label} {_fmt_price(numeric)}", color))

        if style == "trade_map":
            add_level(entry, "ВХОД", BLUE, "-", 1.35)
            add_level(tp1, "TP1", GREEN, "--", 1.00)
            add_level(tp2, "TP2", GREEN, "--", 1.00)
            add_level(tp3, "TP3", GREEN, "--", 1.25)
            add_level(stop, "СТОП", RED, "--", 1.30)
        elif style == "minimal_chart":
            add_level(decision, "УРОВЕНЬ", ORANGE, "-", 1.50)
            add_level(tp1, "TP1", GREEN, "--", 1.15)
            add_level(stop, "СТОП", RED, "--", 1.20)
        elif style == "event_chart":
            add_level(decision, "УРОВЕНЬ", ORANGE, "-", 1.45)
            add_level(tp1, "TP1", GREEN, "--", 1.05)
            add_level(stop, "СТОП", RED, "--", 1.15)
        elif style == "scenario_chart":
            add_level(decision, "РЕШЕНИЕ", ORANGE, "-", 1.50)
            add_level(tp1, "СЦЕНАРИЙ A", GREEN, "--", 1.10)
            add_level(stop, "СЦЕНАРИЙ B", RED, "--", 1.20)
        elif style == "context_chart":
            add_level(decision, "КОНТРОЛЬ", ORANGE, "-", 1.45)
            add_level(tp1, "TP1", GREEN, "--", 1.00)
            add_level(stop, "СТОП", RED, "--", 1.10)
        else:
            add_level(decision, "КОНТРОЛЬ", ORANGE, "-", 1.45)
            add_level(tp1, "TP1", GREEN, "--", 1.10)
            add_level(stop, "СТОП", RED, "--", 1.20)

        # Only trade_map uses a full side panel. Other visuals keep more chart area
        # and look materially different in a scrolling feed.
        if style == "trade_map":
            panel = "ПЛАН\n\n" + "\n".join(label for _, label, _ in shown_levels)
            price_axis.text(
                1.015, 0.96, panel, transform=price_axis.transAxes,
                color=TEXT, fontsize=8.2, fontweight="bold", ha="left", va="top",
                linespacing=1.55, clip_on=False,
                bbox={"boxstyle": "round,pad=0.55", "facecolor": PANEL, "alpha": 0.95, "edgecolor": "#2a3340"},
            )
            right_margin = 0.78
        else:
            right_margin = 0.94

        price_axis.text(
            0.012, 0.965, f"СЕЙЧАС {_fmt_price(current_price)}",
            transform=price_axis.transAxes, color="white", fontsize=9,
            fontweight="bold", ha="left", va="top",
            bbox={"boxstyle": "round,pad=0.25", "facecolor": "#080b10", "alpha": 0.78, "edgecolor": "none"},
        )

        if vol_rel is not None:
            event_prefix = "АКТИВНОСТЬ" if style in {"event_chart", "context_chart"} else "ОБЪЁМ"
            volume_axis.text(
                0.985, 0.86, f"{event_prefix} x{float(vol_rel):.2f}",
                transform=volume_axis.transAxes, color=ORANGE, fontsize=8,
                fontweight="bold", ha="right", va="top",
            )

        # One annotation, only when it adds state information.
        marker = _decision_caption(decision_mode)
        marker_color = ORANGE
        if str(decision_mode) == "retest_hold":
            marker_color = BLUE
        elif str(decision_mode) == "retest_reject":
            marker_color = BLUE
        elif str(decision_mode) == "breakout_confirm":
            marker_color = GREEN
        elif str(decision_mode) == "breakdown_confirm":
            marker_color = RED
        if style not in {"minimal_chart", "trade_map"}:
            price_axis.annotate(
                marker,
                xy=(frame.index[-1], current_price), xytext=(-115, 26), textcoords="offset points",
                arrowprops={"arrowstyle": "->", "color": marker_color},
                color=marker_color, fontsize=8.2, fontweight="bold",
            )

        title = headline.strip() or f"${basic.upper()} · {'LONG' if direction == 'long' else 'SHORT'}"
        title = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "", title).strip()
        if len(title) > 88:
            title = title[:85].rstrip() + "…"
        price_axis.set_title(title, color=TEXT, fontsize=12.2, fontweight="bold", pad=14, loc="left")

        if signal_label and style in {"event_chart", "context_chart"}:
            price_axis.text(
                0.99, 0.965, signal_label.upper(), transform=price_axis.transAxes,
                color=ORANGE, fontsize=8.0, fontweight="bold", ha="right", va="top",
            )

        price_axis.set_ylabel("Цена (USDT)", color="#c8ccd4", fontsize=9)
        volume_axis.set_ylabel("Объём", color="#c8ccd4", fontsize=8)
        handles, _ = price_axis.get_legend_handles_labels()
        if handles and style != "minimal_chart":
            price_axis.legend(
                loc="upper left", bbox_to_anchor=(0.01, 0.91), fontsize=7,
                framealpha=0.18, labelcolor="#c8ccd4",
            )
        plt.setp(price_axis.get_xticklabels(), visible=False)
        volume_axis.xaxis.set_major_formatter(mdates.DateFormatter("%d %b\n%H:%M"))
        volume_axis.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=5, maxticks=9))

        figure.text(
            0.45, 0.50, WATERMARK, color="gray", alpha=0.055,
            fontsize=32, ha="center", va="center", rotation=28,
        )
        figure.subplots_adjust(left=0.09, right=right_margin, top=0.91, bottom=0.09)
        figure.savefig(path, dpi=165, facecolor=BG, bbox_inches="tight")
        plt.close(figure)
        return path
    except Exception as exc:
        logger.error("Chart generation failed: %s", exc)
        if figure is not None:
            plt.close(figure)
        try:
            os.remove(path)
        except OSError:
            pass
        return None
