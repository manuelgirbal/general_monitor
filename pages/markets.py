from datetime import datetime, timedelta, timezone

import plotly.graph_objects as go
from shiny import module, render, ui

from db import get_conn
from plots import base_layout, busy_guard, fig_html, pct_change, stat_card, stat_grid

RANGES = {
    "all": "Total",
    "5y": "Last 5 years",
    "1y": "Last year",
    "6m": "Last 6 months",
    "1m": "Last month",
}
RANGE_DAYS = {"5y": 1826, "1y": 365, "6m": 182, "1m": 30}

# symbol -> (label, unit, color, value format)
ASSETS = {
    "^GSPC": ("S&P 500", "points", "#5dade2", "{:,.0f}"),
    "HG=F": ("Cobre", "USD / lb", "#e67e22", "${:,.2f}"),
    "GC=F": ("Oro", "USD / oz", "#f4d03f", "${:,.0f}"),
    "BZ=F": ("Brent", "USD / bbl", "#e74c3c", "${:,.2f}"),
    "NG=F": ("Gas natural (Henry Hub)", "USD / MMBtu", "#52be80", "${:,.2f}"),
}


def _cutoff(range_key: str):
    days = RANGE_DAYS.get(range_key)
    if days is None:
        return None
    return datetime.now(tz=timezone.utc) - timedelta(days=days)


def _load_closes(cutoff=None) -> dict[str, list]:
    where = ""
    params = []
    if cutoff is not None:
        where = "WHERE ts >= ?"
        params.append(cutoff)
    conn = get_conn(readonly=True)
    try:
        rows = conn.execute(
            f"SELECT symbol, ts, close FROM market_daily {where} ORDER BY ts",
            params,
        ).fetchall()
    finally:
        conn.close()
    out = {s: [] for s in ASSETS}
    for symbol, ts, close in rows:
        if symbol in out:
            out[symbol].append((ts, close))
    return out


@module.ui
def markets_ui():
    return ui.nav_panel(
        "Mercados",
        ui.input_radio_buttons("range", "Range", choices=RANGES, selected="1y", inline=True),
        ui.h2("Commodities · índices"),
        ui.output_ui("cards"),
        ui.output_ui("indexed_chart"),
        ui.output_ui("asset_charts"),
        ui.p(
            "Daily closes (front-month futures for commodities) from Yahoo Finance's "
            "public chart endpoint — unofficial and delayed; reference only. Copper, "
            "gold and energy prices frame Argentina's mining and Vaca Muerta outlook; "
            "the S&P 500 is the global risk-appetite benchmark.",
            class_="note",
        ),
        value="markets",
    )


@module.server
def markets_server(input, output, session):
    @render.ui
    @busy_guard
    def cards():
        data = _load_closes(_cutoff(input.range()))
        if not any(data.values()):
            return ui.p(
                "No market data yet. Run ",
                ui.tags.code("python -m scripts.backfill markets_history"),
                ".",
            )
        tiles = []
        for symbol, (label, unit, color, fmt) in ASSETS.items():
            rows = data[symbol]
            if not rows:
                continue
            ts, last = rows[-1]
            prev = rows[-2][1] if len(rows) > 1 else None
            day = pct_change(last, prev)
            sub = f"{unit} · {ts:%Y-%m-%d}"
            if day is not None:
                sub += f" · 1d {day:+.1f}%"
            tiles.append(stat_card(
                label, fmt.format(last),
                delta=(pct_change(last, rows[0][1]), RANGES[input.range()].lower()),
                sub=sub,
                accent=color,
            ))
        return stat_grid(*tiles)

    @render.ui
    @busy_guard
    def indexed_chart():
        data = _load_closes(_cutoff(input.range()))
        # Series start on different dates (S&P 1970, Brent 2007); index all of
        # them from the latest common start so the comparison is like-for-like.
        starts = [rows[0][0] for rows in data.values() if rows]
        common_start = max(starts) if starts else None
        fig = go.Figure()
        for symbol, (label, _unit, color, _fmt) in ASSETS.items():
            rows = [r for r in data[symbol] if r[0] >= common_start]
            if not rows or not rows[0][1]:
                continue
            base = rows[0][1]
            fig.add_trace(go.Scatter(
                x=[r[0] for r in rows],
                y=[r[1] / base * 100 for r in rows],
                mode="lines",
                name=label,
                line=dict(color=color, width=2),
                hovertemplate="%{x|%Y-%m-%d}<br>%{y:.1f}<extra>" + label + "</extra>",
            ))
        if not fig.data:
            return ui.p("No market data yet.")
        layout = base_layout(
            f"Relative performance — indexed to 100 at range start ({RANGES[input.range()]})",
            y_title="index",
        )
        layout["height"] = 380
        fig.update_layout(**layout)
        fig.add_hline(y=100, line=dict(color="#555", width=1, dash="dot"))
        if input.range() in ("all", "5y"):
            fig.update_yaxes(type="log")
        return fig_html(fig)

    @render.ui
    @busy_guard
    def asset_charts():
        data = _load_closes(_cutoff(input.range()))
        charts = []
        for symbol, (label, unit, color, _fmt) in ASSETS.items():
            rows = data[symbol]
            if not rows:
                continue
            fig = go.Figure(go.Scatter(
                x=[r[0] for r in rows],
                y=[r[1] for r in rows],
                mode="lines",
                line=dict(color=color, width=2),
                hovertemplate="%{x|%Y-%m-%d}<br>%{y:,.2f}<extra></extra>",
            ))
            layout = base_layout(label, y_title=unit)
            layout["height"] = 280
            fig.update_layout(**layout)
            charts.append(fig_html(fig))
        return ui.div(*charts, class_="chart-grid")
