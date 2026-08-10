"""Candlestick chart renderer built only on matplotlib and pandas."""
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
CHART_STYLE = 'Binance Premium Dark'
WATERMARK = os.getenv("CHART_WATERMARK", "PozitiveHero")


def _fmt_price(value: float) -> str:
    price = float(value)
    absolute = abs(price)
    if absolute >= 100:
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
                    "timestamp",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "close_time",
                    "quote_asset_volume",
                    "number_of_trades",
                    "taker_buy_base_asset_volume",
                    "taker_buy_quote_asset_volume",
                    "ignore",
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
    if len(x_values) > 1:
        candle_width = float(np.median(np.diff(x_values))) * 0.68
    else:
        candle_width = 0.006

    for x, (_, row) in zip(x_values, frame.iterrows()):
        bullish = row["close"] >= row["open"]
        color = "#26de81" if bullish else "#ff4757"
        price_axis.vlines(x, row["low"], row["high"], color=color, linewidth=0.8, alpha=0.95)
        body_low = min(row["open"], row["close"])
        body_height = abs(row["close"] - row["open"])
        minimum_body = max((row["high"] - row["low"]) * 0.025, abs(row["close"]) * 1e-8)
        body_height = max(body_height, minimum_body)
        price_axis.add_patch(
            Rectangle(
                (x - candle_width / 2, body_low),
                candle_width,
                body_height,
                facecolor=color,
                edgecolor=color,
                linewidth=0.7,
                alpha=0.95,
            )
        )
        volume_axis.bar(x, row["volume"], width=candle_width, color=color, alpha=0.50, align="center")


def generate_chart(
    symbol: str,
    raw_data,
    basic: str,
    *,
    entry: Optional[float] = None,
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
    del symbol
    frame = _to_df(raw_data)
    if frame is None:
        return None
    frame = frame.tail(90).copy()
    human_visual = visual_style in {
        "clean_chart", "context_chart", "level_map", "split_scenario", "journal_card"
    }

    frame["EMA20"] = frame["close"].ewm(span=20, adjust=False).mean()
    frame["EMA50"] = frame["close"].ewm(span=50, adjust=False).mean()
    frame["EMA200"] = frame["close"].ewm(span=200, adjust=False).mean()
    middle = frame["close"].rolling(20).mean()
    deviation = frame["close"].rolling(20).std(ddof=0)
    frame["BB_H"] = middle + 2 * deviation
    frame["BB_L"] = middle - 2 * deviation
    typical = (frame["high"] + frame["low"] + frame["close"]) / 3.0
    frame["VWAP"] = (typical * frame["volume"]).cumsum() / frame["volume"].cumsum().replace(0, np.nan)

    temp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    path = temp.name
    temp.close()

    figure = None
    try:
        figure = plt.figure(figsize=(9, 8), facecolor="#0f1216")
        grid = figure.add_gridspec(5, 1, hspace=0.06)
        price_axis = figure.add_subplot(grid[:4, 0])
        volume_axis = figure.add_subplot(grid[4, 0], sharex=price_axis)

        for axis in (price_axis, volume_axis):
            axis.set_facecolor("#0f1216")
            axis.grid(True, color="#1e242c", linewidth=0.65, alpha=0.75)
            axis.tick_params(colors="#8b93a1", labelsize=8)
            for spine in axis.spines.values():
                spine.set_color("#1e242c")

        _draw_candles(price_axis, volume_axis, frame)
        # Human Feed charts deliberately show less. The old chart looked like a
        # terminal screenshot: EMA20/50/200, VWAP, seven levels and a trade-plan
        # panel. In a mobile feed the job of the picture is to make the *one*
        # decision level obvious, not to repeat the whole analysis.
        if visual_style == "level_map":
            price_axis.plot(frame.index, frame["VWAP"], color="#ff8c69", linewidth=1.15, linestyle="-.", label="VWAP")
        elif visual_style == "context_chart":
            price_axis.plot(frame.index, frame["EMA20"], color="#f5a623", linewidth=1.20, label="EMA20")
            price_axis.plot(frame.index, frame["VWAP"], color="#ff8c69", linewidth=0.95, linestyle="-.", label="VWAP")
        else:
            price_axis.plot(frame.index, frame["EMA20"], color="#f5a623", linewidth=1.25, label="EMA20")
            price_axis.plot(frame.index, frame["VWAP"], color="#ff8c69", linewidth=0.95, linestyle="-.", label="VWAP")

        if not human_visual:
            try:
                change = ((float(frame["close"].iloc[-1]) / float(frame["close"].iloc[-20]) - 1) * 100)
                volume_now = float(frame["volume"].iloc[-1])
                volume_avg = float(frame["volume"].tail(20).mean())
                info = f"20 свечей: {change:+.2f}% | Объём x{(volume_now/volume_avg if volume_avg else 0):.2f}"
                price_axis.text(
                    0.015, 0.035, info,
                    transform=price_axis.transAxes,
                    fontsize=8,
                    color="white",
                    bbox={"boxstyle": "round,pad=0.35", "facecolor": "#111820", "alpha": 0.8, "edgecolor": "none"},
                )
            except Exception:
                pass

        if entry is not None and stop is not None:
            price_axis.axhspan(min(entry, stop), max(entry, stop), color="#ff4757", alpha=0.07)
        reward_level = tp1 if human_visual else tp3
        if entry is not None and reward_level is not None:
            price_axis.axhspan(min(entry, reward_level), max(entry, reward_level), color="#26de81", alpha=0.055)

        levels = []

        def add_level(value, label: str, color: str, style: str, width: float):
            if value is None:
                return
            numeric = float(value)
            price_axis.axhline(numeric, color=color, linestyle=style, linewidth=width, alpha=0.95)
            levels.append((numeric, f"{label} {_fmt_price(numeric)}", color))

        if human_visual:
            shown_decision = decision_level
            if shown_decision is None:
                shown_decision = resistance if direction == "long" else support
            decision_caption = {
                "at_level": "КОНТРОЛЬ",
                "retest_hold": "УРОВЕНЬ",
                "retest_reject": "УРОВЕНЬ",
                "breakout_confirm": "ПОДТВЕРЖДЕНИЕ",
                "breakdown_confirm": "ПОДТВЕРЖДЕНИЕ",
            }.get(str(decision_mode), "УРОВЕНЬ")
            add_level(shown_decision, decision_caption, "#f5a623", "-", 1.6)
            add_level(tp1, "ЦЕЛЬ", "#26de81", "--", 1.25)
            add_level(stop, "ОТМЕНА", "#ff4757", "--", 1.35)
            plan_labels = [label for _, label, _ in levels]
            panel_title = "ПЛАН"
        else:
            add_level(entry, "ENTRY", "#ffffff", "-", 1.6)
            add_level(tp1, "TP1", "#26de81", "--", 1.1)
            add_level(tp2, "TP2", "#26de81", "--", 1.1)
            add_level(tp3, "TP3", "#26de81", "--", 1.4)
            add_level(stop, "STOP", "#ff4757", "--", 1.6)
            add_level(support, "SUP", "#2ecc71", ":", 0.9)
            add_level(resistance, "RES", "#e74c3c", ":", 0.9)
            plan_labels = [label for _, label, _ in levels if not label.startswith(("SUP", "RES"))]
            panel_title = "LEVEL MAP" if visual_style == "level_map" else "MARKET CONTEXT" if visual_style == "context_chart" else "TRADE PLAN"

        price_axis.text(
            1.015,
            0.96,
            panel_title + "\n\n" + "\n".join(plan_labels),
            transform=price_axis.transAxes,
            color="#e7ebf1",
            fontsize=8.5 if human_visual else 8.2,
            fontweight="bold",
            ha="left",
            va="top",
            linespacing=1.6,
            clip_on=False,
            bbox={
                "boxstyle": "round,pad=0.55",
                "facecolor": "#111820",
                "alpha": 0.94,
                "edgecolor": "#2a3340",
            },
        )

        current_price = float(frame["close"].iloc[-1])
        price_axis.text(
            0.012,
            0.965,
            f"СЕЙЧАС {_fmt_price(current_price)}" if human_visual else f"LAST {_fmt_price(current_price)}",
            transform=price_axis.transAxes,
            color="white",
            fontsize=9,
            fontweight="bold",
            ha="left",
            va="top",
            bbox={"boxstyle": "round,pad=0.25", "facecolor": "#080b10", "alpha": 0.78, "edgecolor": "none"},
        )

        if vol_rel is not None:
            volume_axis.text(
                0.985,
                0.86,
                f"ОБЪЁМ x{vol_rel:.2f}" if human_visual else f"REL VOL x{vol_rel:.2f}",
                transform=volume_axis.transAxes,
                color="#f5a623",
                fontsize=8,
                fontweight="bold",
                ha="right",
                va="top",
            )

        marker = None
        marker_color = "#f5a623"
        if human_visual and decision_level is not None:
            if decision_mode == "at_level":
                marker, marker_color = "ПРОВЕРКА УРОВНЯ", "#f5a623"
            elif decision_mode in {"retest_hold", "retest_reject"}:
                marker, marker_color = "РЕТЕСТ", "#4a90e2"
            elif decision_mode == "breakout_confirm":
                marker, marker_color = "ЖДУ ЗАКРЕПЛЕНИЕ ВЫШЕ", "#26de81"
            elif decision_mode == "breakdown_confirm":
                marker, marker_color = "ЖДУ ЗАКРЕПЛЕНИЕ НИЖЕ", "#ff4757"
        elif indicator is not None:
            if direction == "long" and indicator.breakout_up:
                marker, marker_color = ("ПРОБОЙ" if human_visual else "BREAKOUT"), "#26de81"
            elif direction == "short" and indicator.breakout_down:
                marker, marker_color = ("ПРОБОЙ ВНИЗ" if human_visual else "BREAKDOWN"), "#ff4757"
            elif direction == "long" and indicator.pullback_long:
                marker, marker_color = ("РЕТЕСТ" if human_visual else "PULLBACK"), "#4a90e2"
            elif direction == "short" and indicator.pullback_short:
                marker, marker_color = ("РЕТЕСТ" if human_visual else "RETEST"), "#4a90e2"
            elif indicator.liquidity_sweep:
                marker = "СНЯТИЕ ЛИКВИДНОСТИ" if human_visual else "LIQUIDITY SWEEP"

        if marker:
            price_axis.annotate(
                marker,
                xy=(frame.index[-1], current_price),
                xytext=(-105, 28),
                textcoords="offset points",
                arrowprops={"arrowstyle": "->", "color": marker_color},
                color=marker_color,
                fontsize=8.5,
                fontweight="bold",
            )

        title = headline.strip() or f"{basic.upper()}/USDT · 15m · {'LONG' if direction == 'long' else 'SHORT'}"
        # Keep emoji in the Square post, but strip them from the matplotlib title
        # because the bundled runner font does not reliably contain emoji glyphs.
        title = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "", title).strip()
        if len(title) > 92:
            title = title[:89].rstrip() + "…"
        price_axis.set_title(title, color="#e7ebf1", fontsize=12.5, fontweight="bold", pad=14, loc="left")
        if signal_label:
            price_axis.text(
                0.99, 0.965, signal_label.upper(), transform=price_axis.transAxes,
                color="#f5a623", fontsize=8.2, fontweight="bold", ha="right", va="top",
            )
        price_axis.set_ylabel("Цена (USDT)" if human_visual else "Price (USDT)", color="#c8ccd4", fontsize=9)
        volume_axis.set_ylabel("Объём" if human_visual else "Volume", color="#c8ccd4", fontsize=8)
        handles, legend_labels = price_axis.get_legend_handles_labels()
        if handles:
            price_axis.legend(loc="upper left", bbox_to_anchor=(0.01, 0.91), fontsize=7, framealpha=0.18, labelcolor="#c8ccd4")
        plt.setp(price_axis.get_xticklabels(), visible=False)
        volume_axis.xaxis.set_major_formatter(mdates.DateFormatter("%d %b\n%H:%M"))
        volume_axis.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=5, maxticks=9))

        figure.text(
            0.42,
            0.50,
            WATERMARK,
            color="gray",
            alpha=0.07,
            fontsize=34,
            ha="center",
            va="center",
            rotation=28,
        )
        figure.subplots_adjust(left=0.09, right=0.78, top=0.91, bottom=0.09)
        figure.savefig(path, dpi=165, facecolor="#0f1216", bbox_inches="tight")
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
