from datetime import datetime, timedelta, timezone

import plotly.graph_objects as go
from shiny import App, render, ui

from db import get_conn, init_schema


def _load_mempool_recent(hours: int = 24):
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=hours)
    conn = get_conn(readonly=True)
    try:
        return conn.execute(
            "SELECT ts, tx_count FROM mempool_snapshots WHERE ts >= ? ORDER BY ts",
            [cutoff],
        ).fetchall()
    finally:
        conn.close()


app_ui = ui.page_fluid(
    ui.h1("general_monitor"),
    ui.h2("Bitcoin · mempool"),
    ui.output_ui("mempool_chart"),
)


def server(input, output, session):
    @output
    @render.ui
    def mempool_chart():
        rows = _load_mempool_recent(24)
        if not rows:
            return ui.p(
                "No data yet. Run ",
                ui.tags.code("python -m ingest.runner"),
                " first.",
            )
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=[r[0] for r in rows],
                y=[r[1] for r in rows],
                mode="lines",
                name="TX count",
            )
        )
        fig.update_layout(
            title="Mempool TX count (last 24h)",
            xaxis_title="UTC",
            yaxis_title="TX count",
            margin=dict(l=40, r=20, t=50, b=40),
            height=400,
        )
        return ui.HTML(fig.to_html(include_plotlyjs="cdn", full_html=False))


init_schema()
app = App(app_ui, server)
