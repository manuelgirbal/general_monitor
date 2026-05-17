from datetime import timezone

from shiny import App, render, ui

from db import get_conn
from plots import page_head


def _load_runs(limit: int = 50):
    conn = get_conn(readonly=True)
    try:
        return conn.execute(
            """
            SELECT ts, source, status, latency_ms, error
            FROM ingest_runs
            ORDER BY ts DESC
            LIMIT ?
            """,
            [limit],
        ).fetchall()
    finally:
        conn.close()


app_ui = ui.page_fluid(
    *page_head(),
    ui.h1("general_monitor · admin"),
    ui.h2("Recent ingest runs"),
    ui.output_ui("runs_table"),
)


def server(input, output, session):
    @render.ui
    def runs_table():
        rows = _load_runs(50)
        if not rows:
            return ui.p("No ingest runs yet.")
        header = ui.tags.thead(
            ui.tags.tr(
                ui.tags.th("ts (UTC)"),
                ui.tags.th("source"),
                ui.tags.th("status"),
                ui.tags.th("ms"),
                ui.tags.th("error"),
            )
        )
        body = ui.tags.tbody(*[
            ui.tags.tr(
                ui.tags.td(ts.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")),
                ui.tags.td(source),
                ui.tags.td(
                    status,
                    style="color: #2e7d32" if status == "ok" else "color: #c62828",
                ),
                ui.tags.td("" if latency_ms is None else str(latency_ms)),
                ui.tags.td(error or ""),
            )
            for ts, source, status, latency_ms, error in rows
        ])
        return ui.tags.table(
            header,
            body,
            style="width:100%; border-collapse: collapse; font-family: monospace;",
        )


app = App(app_ui, server)
