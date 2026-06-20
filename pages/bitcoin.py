from datetime import datetime, timedelta, timezone

import plotly.graph_objects as go
from shiny import module, render, ui

from db import get_conn
from plots import (
    BTC_ORANGE,
    base_layout,
    busy_guard,
    fmt_age,
    fmt_ehs,
    fmt_sat_vb,
    fmt_usd,
)

RANGES = {
    "all": "Total",
    "1y": "Last year",
    "6m": "Last 6 months",
    "1m": "Last month",
}
RANGE_DAYS = {"1y": 365, "6m": 182, "1m": 30}
SCALES = {"linear": "Linear", "log": "Log"}


def _cutoff(range_key: str):
    days = RANGE_DAYS.get(range_key)
    if days is None:
        return None
    return datetime.now(tz=timezone.utc) - timedelta(days=days)


def _load_prices_daily(cutoff=None, pair: str = "BTC/USD"):
    where = "WHERE pair = ?"
    params = [pair]
    if cutoff is not None:
        where += " AND ts >= ?"
        params.append(cutoff)
    conn = get_conn(readonly=True)
    try:
        return conn.execute(
            f"""
            SELECT date_trunc('day', ts) AS d, arg_max(price, ts) AS price
            FROM prices
            {where}
            GROUP BY 1
            ORDER BY 1
            """,
            params,
        ).fetchall()
    finally:
        conn.close()


def _latest_price(pair: str = "BTC/USD"):
    conn = get_conn(readonly=True)
    try:
        return conn.execute(
            "SELECT ts, price FROM prices WHERE pair = ? ORDER BY ts DESC LIMIT 1",
            [pair],
        ).fetchone()
    finally:
        conn.close()


def _load_tx_daily(cutoff=None):
    # tx_history (blockchain.info, daily) is the canonical series; blocks fills only the
    # most recent days it doesn't cover yet (the live tail, incl. today in progress).
    # If tx_history is empty, the COALESCE falls back to blocks entirely.
    where = ""
    params = []
    if cutoff is not None:
        where = "WHERE d >= ?"
        params.append(cutoff)
    conn = get_conn(readonly=True)
    try:
        return conn.execute(
            f"""
            WITH hist AS (
                SELECT date_trunc('day', ts) AS d, n_tx AS tx
                FROM tx_history
                WHERE source = 'blockchain_info'
            ),
            live AS (
                SELECT date_trunc('day', ts) AS d, sum(tx_count) AS tx
                FROM blocks
                WHERE date_trunc('day', ts) > COALESCE(
                    (SELECT max(d) FROM hist), TIMESTAMP '1970-01-01'
                )
                GROUP BY 1
            )
            SELECT d, tx FROM (
                SELECT d, tx FROM hist
                UNION ALL
                SELECT d, tx FROM live
            )
            {where}
            ORDER BY d
            """,
            params,
        ).fetchall()
    finally:
        conn.close()


def _load_fees_daily(cutoff=None):
    where = "WHERE fee_p50 IS NOT NULL"
    params = []
    if cutoff is not None:
        where += " AND ts >= ?"
        params.append(cutoff)
    conn = get_conn(readonly=True)
    try:
        return conn.execute(
            f"""
            SELECT date_trunc('day', ts) AS d,
                   avg(fee_p10), avg(fee_p50), avg(fee_p90)
            FROM mempool_snapshots
            {where}
            GROUP BY 1
            ORDER BY 1
            """,
            params,
        ).fetchall()
    finally:
        conn.close()


def _load_yearly_prices(pair: str = "BTC/USD"):
    conn = get_conn(readonly=True)
    try:
        return conn.execute(
            """
            WITH daily AS (
                SELECT date_trunc('day', ts) AS d, arg_max(price, ts) AS close
                FROM prices
                WHERE pair = ?
                GROUP BY 1
            )
            SELECT year(d) AS yr, avg(close) AS avg_price
            FROM daily
            GROUP BY 1
            ORDER BY 1
            """,
            [pair],
        ).fetchall()
    finally:
        conn.close()


def _load_latest_block():
    conn = get_conn(readonly=True)
    try:
        return conn.execute(
            """
            SELECT height, hash, ts, tx_count, size
            FROM blocks
            ORDER BY height DESC
            LIMIT 1
            """
        ).fetchone()
    finally:
        conn.close()


def _load_latest_network():
    conn = get_conn(readonly=True)
    try:
        return conn.execute(
            """
            SELECT ts, hash_rate_ehs, difficulty
            FROM network_stats
            ORDER BY ts DESC
            LIMIT 1
            """
        ).fetchone()
    finally:
        conn.close()


@module.ui
def bitcoin_ui():
    return ui.nav_panel(
        "Bitcoin",
        ui.input_radio_buttons("range", "Range", choices=RANGES, selected="all", inline=True),
        ui.h2("Bitcoin · market"),
        ui.output_ui("price_headline"),
        ui.input_radio_buttons("price_scale", "Scale", choices=SCALES, selected="linear", inline=True),
        ui.output_ui("price_chart"),
        ui.h2("Bitcoin · network"),
        ui.output_ui("network_card"),
        ui.h2("Bitcoin · on-chain"),
        ui.output_ui("latest_block_card"),
        ui.output_ui("tx_chart"),
        ui.output_ui("fees_chart"),
        ui.h2("Bitcoin · history"),
        ui.output_ui("yearly_table"),
        value="bitcoin",
    )


@module.server
def bitcoin_server(input, output, session):
    @render.ui
    @busy_guard
    def price_headline():
        rows = _load_prices_daily(_cutoff(input.range()))
        latest = _latest_price()
        if latest is None or not rows:
            return ui.p("No price data yet.")
        latest_ts, latest_price = latest
        age = (datetime.now(tz=timezone.utc) - latest_ts).total_seconds()
        # The "all" range starts in 2010 (~$0.07), so its change is astronomical
        # and meaningless — only show the comparison for the bounded ranges.
        change_span = None
        if input.range() != "all":
            first_price = rows[0][1]
            change = (latest_price - first_price) / first_price * 100 if first_price else 0
            change_color = "#52be80" if change >= 0 else "#e74c3c"
            sign = "+" if change >= 0 else ""
            change_span = ui.tags.span(
                f"{sign}{change:.2f}% {RANGES[input.range()].lower()} · ",
                style=f"color: {change_color}",
            )
        return ui.div(
            ui.h3(fmt_usd(latest_price)),
            ui.p(change_span, fmt_age(age)),
        )

    @render.ui
    @busy_guard
    def price_chart():
        rows = _load_prices_daily(_cutoff(input.range()))
        if not rows:
            return ui.p("No price data yet.")
        fig = go.Figure(
            go.Scatter(
                x=[r[0] for r in rows],
                y=[r[1] for r in rows],
                mode="lines",
                line=dict(color=BTC_ORANGE),
                hovertemplate="%{x|%Y-%m-%d}<br>%{y:$,.0f}<extra></extra>",
            )
        )
        layout = base_layout(f"BTC / USD — daily ({RANGES[input.range()]})", y_title="USD")
        layout["height"] = 320
        fig.update_layout(**layout)
        if input.price_scale() == "log":
            fig.update_yaxes(type="log")
        return ui.HTML(fig.to_html(include_plotlyjs=False, full_html=False))

    @render.ui
    @busy_guard
    def tx_chart():
        rows = _load_tx_daily(_cutoff(input.range()))
        if not rows:
            return ui.p("No block data yet.")
        fig = go.Figure(
            go.Scatter(
                x=[r[0] for r in rows],
                y=[r[1] for r in rows],
                mode="lines",
                line=dict(color=BTC_ORANGE),
                hovertemplate="%{x|%Y-%m-%d}<br>%{y:,.0f} tx<extra></extra>",
            )
        )
        layout = base_layout(
            f"Transactions per day ({RANGES[input.range()]})", y_title="tx / day"
        )
        fig.update_layout(**layout)
        return ui.HTML(fig.to_html(include_plotlyjs=False, full_html=False))

    @render.ui
    @busy_guard
    def fees_chart():
        rows = _load_fees_daily(_cutoff(input.range()))
        if not rows:
            return ui.p("No fee data yet.")
        fig = go.Figure()
        for idx, (label, color) in enumerate(
            [
                ("p10 · low priority", "#52be80"),
                ("p50 · median", "#f4d03f"),
                ("p90 · high priority", "#e74c3c"),
            ],
            start=1,
        ):
            fig.add_trace(go.Scatter(
                x=[r[0] for r in rows],
                y=[r[idx] for r in rows],
                mode="lines",
                name=label,
                line=dict(color=color),
            ))
        fig.update_layout(**base_layout(
            f"Mempool fee rates — sat/vByte ({RANGES[input.range()]})", y_title="sat/vB"
        ))
        latest = rows[-1]
        return ui.div(
            ui.HTML(fig.to_html(include_plotlyjs=False, full_html=False)),
            ui.p(
                "Percentiles of the fee rate (sat/vByte) bid by transactions in the "
                "mempool: p10 is the cheap end (slow to confirm), p50 the median, "
                "p90 the high end (fast). Higher sat/vByte buys faster confirmation.",
                style="opacity: 0.7; font-size: 0.85em;",
            ),
            ui.p(
                f"Latest daily avg: p10 {fmt_sat_vb(latest[1])} · "
                f"p50 {fmt_sat_vb(latest[2])} · "
                f"p90 {fmt_sat_vb(latest[3])} · "
                f"({len(rows)} day(s) in window)"
            ),
        )

    @render.ui
    @busy_guard
    def yearly_table():
        rows = _load_yearly_prices()
        if not rows:
            return ui.p("No price history yet. Run ", ui.tags.code("python -m scripts.backfill prices_history"), ".")
        current_year = datetime.now(tz=timezone.utc).year
        body = []
        prev = None
        for yr, avg_price in rows:
            if prev:
                yoy = (avg_price - prev) / prev * 100
                color = "#52be80" if yoy >= 0 else "#e74c3c"
                yoy_cell = ui.tags.td(f"{yoy:+.1f}%", style=f"color: {color}")
            else:
                yoy_cell = ui.tags.td("—")
            label = f"{int(yr)}*" if int(yr) == current_year else f"{int(yr)}"
            body.append(ui.tags.tr(
                ui.tags.td(label),
                ui.tags.td(fmt_usd(avg_price)),
                yoy_cell,
            ))
            prev = avg_price
        return ui.div(
            ui.h3("Average yearly price (USD)"),
            ui.tags.table(
                ui.tags.thead(ui.tags.tr(
                    ui.tags.th("Year"), ui.tags.th("Avg price"), ui.tags.th("YoY")
                )),
                ui.tags.tbody(*body),
            ),
            ui.p("* current year — partial average.", style="font-size: 12px; color: #888;"),
        )

    @render.ui
    @busy_guard
    def network_card():
        row = _load_latest_network()
        if row is None:
            return ui.p("No network stats yet.")
        ts, hash_rate_ehs, difficulty = row
        age = (datetime.now(tz=timezone.utc) - ts).total_seconds()
        return ui.div(
            ui.h3(f"Hashrate · {fmt_ehs(hash_rate_ehs)}"),
            ui.p(
                f"Difficulty: {difficulty:,.2e} · {fmt_age(age)}"
                if difficulty is not None
                else f"{fmt_age(age)}"
            ),
        )

    @render.ui
    @busy_guard
    def latest_block_card():
        row = _load_latest_block()
        if row is None:
            return ui.div(ui.p("No blocks yet. Run ", ui.tags.code("python -m ingest.runner"), "."))
        height, _hash, ts, tx_count, size = row
        age = (datetime.now(tz=timezone.utc) - ts).total_seconds()
        return ui.div(
            ui.h3(f"Block #{height:,}"),
            ui.p(f"{fmt_age(age)} · {tx_count:,} tx · {size / 1_000_000:.2f} MB"),
        )
