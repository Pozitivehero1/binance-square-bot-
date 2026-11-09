"""A chart of the exact source candles, without decorative trade signals."""
from __future__ import annotations

from datetime import datetime, timezone


def chart(story, directory):
    if not story.candles:
        return None
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    rows = story.candles[-289:] if story.range_level is not None else story.candles[-49:]
    dates = [datetime.fromtimestamp((r[6]+1)/1000, timezone.utc) for r in rows]
    values = [r[4] for r in rows]
    positive = values[-1] >= values[0]
    color = "#47dfb2" if positive else "#ff7990"
    with plt.rc_context({"font.family": "DejaVu Sans", "font.size": 12}):
        fig, ax = plt.subplots(figsize=(12, 6.75), dpi=100, facecolor="#101725")
        try:
            ax.set_facecolor("#101725")
            fig.subplots_adjust(left=.09, right=.92, bottom=.22, top=.70)
            fig.text(.08, .90, story.chart_symbol.removesuffix("USDT")+" / USDT",
                     color="#f3f6fc", fontsize=28, weight="bold")
            fig.text(.08, .82, "Цена закрытия · пятиминутные свечи", color="#aab8d0", fontsize=14)
            ax.plot(dates, values, color=color, linewidth=2.6)
            ax.scatter([dates[-1]], [values[-1]], color=color, s=40, zorder=3)
            bounds = values.copy()
            if story.range_level is not None:
                bounds.append(story.range_level)
                ax.axhline(story.range_level, color="#f3c95d", linestyle="--", linewidth=1.4)
                ax.annotate(f"Граница суток · {story.range_level:.8f}".rstrip("0").rstrip("."),
                            (dates[0], story.range_level), xytext=(5, 7), textcoords="offset points",
                            color="#f3c95d", fontsize=11)
            padding = max((max(bounds)-min(bounds))*.18, values[-1]*.001)
            ax.set_ylim(min(bounds)-padding, max(bounds)+padding)
            ax.yaxis.tick_right()
            ax.ticklabel_format(axis="y", style="plain", useOffset=False)
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=timezone.utc))
            ax.grid(axis="y", color="#283449", linewidth=.7, alpha=.7)
            ax.tick_params(colors="#aab8d0", length=0, pad=12)
            for spine in ax.spines.values():
                spine.set_visible(False)
            fig.text(.08, .10, f"Binance Spot · {dates[0]:%d.%m %H:%M} — {dates[-1]:%d.%m %H:%M} UTC",
                     color="#aab8d0", fontsize=11)
            fig.text(.92, .10, "PozitiveHero", color="#f3c95d", ha="right", fontsize=12)
            path = directory / "market.png"
            fig.savefig(path, facecolor=fig.get_facecolor())
            return str(path)
        finally:
            plt.close(fig)
