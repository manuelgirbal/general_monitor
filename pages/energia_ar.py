from datetime import datetime, timedelta, timezone

import plotly.graph_objects as go
from shiny import module, render, ui

from db import get_conn
from plots import base_layout, busy_guard, fmt_age

RANGES = {"30d": "30 days", "7d": "7 days", "48h": "48 hours"}
RANGE_HOURS = {"30d": 720, "7d": 168, "48h": 48}

REGION_SADI = 1002
GEN_WINDOW_HOURS = 24

# Stack order is bottom-to-top: dispatchable baseload first, imports on top.
GEN_SOURCES = (
    ("nuclear", "Nuclear", "#9b59b6"),
    ("hidraulico", "Hidráulica", "#5dade2"),
    ("termico", "Térmica", "#e74c3c"),
    ("renovable", "Renovable", "#52be80"),
    ("importacion", "Importación", "#f4d03f"),
)


def _cutoff(range_key: str):
    return datetime.now(tz=timezone.utc) - timedelta(hours=RANGE_HOURS[range_key])


def _fmt_mw(v) -> str:
    return "—" if v is None else f"{v:,.0f} MW"


def _load_generation_latest():
    conn = get_conn(readonly=True)
    try:
        return conn.execute(
            """
            SELECT ts, total, hidraulico, termico, nuclear, renovable, importacion
            FROM cammesa_generation
            WHERE region = ?
            ORDER BY ts DESC
            LIMIT 1
            """,
            [REGION_SADI],
        ).fetchone()
    finally:
        conn.close()


def _load_generation_window(hours: int):
    conn = get_conn(readonly=True)
    try:
        return conn.execute(
            f"""
            SELECT ts, hidraulico, termico, nuclear, renovable, importacion
            FROM cammesa_generation
            WHERE region = ?
              AND ts >= (SELECT max(ts) FROM cammesa_generation WHERE region = ?)
                        - INTERVAL {int(hours)} HOUR
            ORDER BY ts
            """,
            [REGION_SADI, REGION_SADI],
        ).fetchall()
    finally:
        conn.close()


def _load_demand(cutoff):
    conn = get_conn(readonly=True)
    try:
        return conn.execute(
            """
            SELECT ts, dem, temp
            FROM cammesa_demand
            WHERE region = ? AND ts >= ?
            ORDER BY ts
            """,
            [REGION_SADI, cutoff],
        ).fetchall()
    finally:
        conn.close()


@module.ui
def energia_ar_ui():
    return ui.nav_panel(
        "Energía AR",
        ui.input_radio_buttons("range", "Range", choices=RANGES, selected="7d", inline=True),
        ui.h2("Generación · matriz eléctrica"),
        ui.output_ui("gen_cards"),
        ui.output_ui("gen_chart"),
        ui.h2("Demanda · SADI"),
        ui.output_ui("demand_chart"),
        ui.p(
            "Fuente: CAMMESA (Total del SADI). La generación acumula hacia "
            "adelante desde que arranca el ingest; el histórico multi-día se "
            "llena con el tiempo.",
            style="opacity: 0.7; font-size: 0.85em;",
        ),
        value="energia_ar",
    )


@module.server
def energia_ar_server(input, output, session):
    @render.ui
    @busy_guard
    def gen_cards():
        row = _load_generation_latest()
        if row is None:
            return ui.p("No generation data yet. Run ", ui.tags.code("python -m ingest.runner"), ".")
        ts, total, hid, ter, nuc, ren, imp = row
        by_key = {
            "hidraulico": hid, "termico": ter, "nuclear": nuc,
            "renovable": ren, "importacion": imp,
        }
        cards = []
        for key, label, _color in GEN_SOURCES:
            v = by_key[key]
            pct = f"{v / total * 100:.0f}%" if v is not None and total else "—"
            cards.append(ui.tags.td(
                ui.h3(pct),
                ui.p(f"{label} · {_fmt_mw(v)}", style="opacity: 0.7;"),
            ))
        age = (datetime.now(tz=timezone.utc) - ts).total_seconds()
        return ui.div(
            ui.h3(f"Total {_fmt_mw(total)}"),
            ui.tags.table(ui.tags.tbody(ui.tags.tr(*cards)), style="width:auto;"),
            ui.p(fmt_age(age)),
        )

    @render.ui
    @busy_guard
    def gen_chart():
        rows = _load_generation_window(GEN_WINDOW_HOURS)
        if not rows:
            return ui.p("No generation data yet.")
        ts = [r[0] for r in rows]
        cols = {
            "hidraulico": [r[1] for r in rows],
            "termico": [r[2] for r in rows],
            "nuclear": [r[3] for r in rows],
            "renovable": [r[4] for r in rows],
            "importacion": [r[5] for r in rows],
        }
        fig = go.Figure()
        for key, label, color in GEN_SOURCES:
            fig.add_trace(go.Scatter(
                x=ts, y=cols[key], mode="lines", name=label,
                line=dict(width=0.5, color=color), stackgroup="one",
                hovertemplate="%{y:,.0f} MW<extra>" + label + "</extra>",
            ))
        fig.update_layout(**base_layout(
            f"Generación por fuente — last {GEN_WINDOW_HOURS}h", y_title="MW"
        ))
        return ui.HTML(fig.to_html(include_plotlyjs=False, full_html=False))

    @render.ui
    @busy_guard
    def demand_chart():
        rows = _load_demand(_cutoff(input.range()))
        if not rows:
            return ui.p("No demand data yet.")
        fig = go.Figure(go.Scatter(
            x=[r[0] for r in rows],
            y=[r[1] for r in rows],
            customdata=[r[2] for r in rows],
            mode="lines",
            line=dict(color="#f7931a", width=1),
            hovertemplate="%{x|%Y-%m-%d %H:%M}<br>%{y:,.0f} MW · %{customdata:.0f}°C<extra></extra>",
        ))
        fig.update_layout(**base_layout(
            f"Demanda — SADI ({RANGES[input.range()]})", y_title="MW"
        ))
        return ui.HTML(fig.to_html(include_plotlyjs=False, full_html=False))
