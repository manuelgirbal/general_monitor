from datetime import datetime, timedelta, timezone

import plotly.graph_objects as go
from shiny import App, render, ui

from db import get_conn
from plots import BTC_ORANGE, base_layout, fmt_age, fmt_sat_vb, page_head


def _load_mempool(hours: int = 24):
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=hours)
    conn = get_conn(readonly=True)
    try:
        return conn.execute(
            """
            SELECT ts, tx_count, vsize, fee_p10, fee_p50, fee_p90
            FROM mempool_snapshots
            WHERE ts >= ?
            ORDER BY ts
            """,
            [cutoff],
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


app_ui = ui.page_fluid(
    *page_head(),
    ui.h1("general_monitor"),
    ui.h2("Bitcoin · mempool"),
    ui.output_ui("latest_block_card"),
    ui.output_ui("mempool_chart"),
    ui.output_ui("fees_chart"),
)


def server(input, output, session):
    @render.ui
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

    @render.ui
    def mempool_chart():
        rows = _load_mempool(24)
        if not rows:
            return ui.p("No mempool data yet.")
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=[r[0] for r in rows],
            y=[r[1] for r in rows],
            mode="lines",
            name="TX count",
            line=dict(color=BTC_ORANGE),
        ))
        fig.add_trace(go.Scatter(
            x=[r[0] for r in rows],
            y=[r[2] / 1_000_000 for r in rows],
            mode="lines",
            name="vsize (MvB)",
            yaxis="y2",
            line=dict(color="#5dade2"),
        ))
        layout = base_layout("Mempool size (last 24h)", y_title="TX count")
        layout["yaxis2"] = dict(
            title="vsize (Mega-vBytes)", overlaying="y", side="right", showgrid=False
        )
        fig.update_layout(**layout)
        return ui.HTML(fig.to_html(include_plotlyjs=False, full_html=False))

    @render.ui
    def fees_chart():
        rows = [r for r in _load_mempool(24) if r[3] is not None]
        if not rows:
            return ui.p("No fee data yet.")
        fig = go.Figure()
        for idx, (label, color) in enumerate(
            [("p10", "#52be80"), ("p50", "#f4d03f"), ("p90", "#e74c3c")], start=3
        ):
            fig.add_trace(go.Scatter(
                x=[r[0] for r in rows],
                y=[r[idx] for r in rows],
                mode="lines",
                name=label,
                line=dict(color=color),
            ))
        fig.update_layout(**base_layout("Fee tiers — next block (last 24h)", y_title="sat/vB"))
        latest = rows[-1]
        return ui.div(
            ui.HTML(fig.to_html(include_plotlyjs=False, full_html=False)),
            ui.p(
                f"Now: p10 {fmt_sat_vb(latest[3])} · "
                f"p50 {fmt_sat_vb(latest[4])} · "
                f"p90 {fmt_sat_vb(latest[5])} · "
                f"({len(rows)} snapshots in window)"
            ),
        )


app = App(app_ui, server)
