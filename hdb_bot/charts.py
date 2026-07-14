"""Multi-district monthly average price comparison chart.

Rendered locally with matplotlib (headless "Agg" backend) rather than a
third-party chart-image service — no external account/key needed, and it
keeps the bot's own request-time work independent of yet another live
dependency beyond data.gov.sg and (optionally) Google Maps.
"""
from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker as mticker  # noqa: E402

FIGURE_SIZE = (10, 5.5)
DPI = 150

# Two HDB towns often land within a few thousand dollars of each other, so
# color alone isn't always enough to tell two lines apart at a glance —
# especially on a small phone screen. Cycling marker shape and line style
# per series (on top of matplotlib's own color cycle) keeps every line
# individually traceable even where two of them run close together or cross.
_MARKERS = ["o", "s", "^", "D", "v", "P"]
_LINESTYLES = ["-", "--", "-.", ":"]


def build_price_comparison_chart(
    series: dict[str, list[tuple[str, float]]],
    *,
    price_unit_suffix: str = "",
    title: str = "Average Resale Price Trend",
) -> bytes:
    """Render a multi-line chart comparing monthly average prices.

    `series` maps a display label (e.g. "Bishan", "D19") to a chronologically
    sorted list of (month_str "YYYY-MM", average_price) tuples — see
    stats.monthly_average_series(). Different series commonly cover
    different sets of months; each is plotted against the union of all
    months seen so gaps show as breaks in that series' line rather than
    misleadingly interpolating or shifting other series' points.

    Raises ValueError if there's no data at all to plot.
    """
    all_months = sorted({month for points in series.values() for month, _ in points})
    if not all_months:
        raise ValueError("No data to chart")

    month_index = {month: i for i, month in enumerate(all_months)}

    x_positions = range(len(all_months))

    fig, ax = plt.subplots(figsize=FIGURE_SIZE, dpi=DPI)
    plotted = 0
    for label, points in series.items():
        if not points:
            continue
        y = [float("nan")] * len(all_months)
        for month, avg_price in points:
            y[month_index[month]] = avg_price
        # NaN gaps break the line rather than connecting across missing months.
        ax.plot(
            x_positions, y,
            marker=_MARKERS[plotted % len(_MARKERS)],
            linestyle=_LINESTYLES[plotted % len(_LINESTYLES)],
            markersize=4, linewidth=1.75, label=label,
        )
        plotted += 1

    ax.set_title(title)
    ax.set_ylabel(f"Average Price{f' ({price_unit_suffix})' if price_unit_suffix else ''} (S$)")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _pos: f"${v:,.0f}"))
    ax.set_xticks(range(len(all_months)))
    ax.set_xticklabels(all_months, rotation=45, ha="right", fontsize=8)
    ax.grid(True, axis="y", alpha=0.3)
    ax.legend(loc="upper left", fontsize=9)
    fig.tight_layout()

    buffer = io.BytesIO()
    fig.savefig(buffer, format="png")
    plt.close(fig)
    return buffer.getvalue()


def warm_up() -> None:
    """Render one throwaway tiny chart so any one-time matplotlib cost
    (backend/font-cache initialization) happens now, during startup,
    instead of during a user's first live chart request. See main.py."""
    build_price_comparison_chart({"warm-up": [("2000-01", 0.0)]}, title="warm-up")
