from datetime import datetime, timedelta, timezone

import plotly.graph_objects as go
from shiny import module, render, ui

from db import get_conn
from plots import (
    LEGEND_BELOW,
    base_layout,
    busy_guard,
    fig_html,
    fmt_age,
    stat_card,
    stat_grid,
)

RANGES = {
    "all": "Total",
    "90d": "90 days",
    "30d": "30 days",
    "7d": "7 days",
    "48h": "48 hours",
}
RANGE_HOURS = {"90d": 2160, "30d": 720, "7d": 168, "48h": 48}

REGION_SADI = 1002
# CAMMESA reports every 5 min; a full AR day has 288 points.
POINTS_PER_DAY = 288
DAY_MS = 86_400_000
# AR has no DST, so a fixed offset maps UTC to the local calendar day.
AR_OFFSET = "INTERVAL 3 HOUR"
# Averaging step per range, to keep long ranges light: (SQL bucket, label).
STEPS = {
    "48h": ("ts", "5-min"),
    "7d": ("date_trunc('hour', ts)", "hourly avg"),
    "30d": ("date_trunc('hour', ts)", "hourly avg"),
    "90d": (f"date_trunc('day', ts - {AR_OFFSET})", "daily avg"),
    "all": (f"date_trunc('day', ts - {AR_OFFSET})", "daily avg"),
}
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

# Stack order is bottom-to-top: dispatchable baseload first, imports on top.
GEN_SOURCES = (
    ("nuclear", "Nuclear", "#9b59b6"),
    ("hidraulico", "Hidráulica", "#5dade2"),
    ("termico", "Térmica", "#e74c3c"),
    ("renovable", "Renovable", "#52be80"),
    ("importacion", "Importación", "#f4d03f"),
)


def _cutoff(range_key: str):
    hours = RANGE_HOURS.get(range_key)
    if hours is None:
        return EPOCH
    return datetime.now(tz=timezone.utc) - timedelta(hours=hours)


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


def _load_generation_window(cutoff, bucket: str):
    conn = get_conn(readonly=True)
    try:
        return conn.execute(
            f"""
            SELECT {bucket} AS t, avg(hidraulico), avg(termico), avg(nuclear),
                   avg(renovable), avg(importacion)
            FROM cammesa_generation
            WHERE region = ? AND ts >= ?
            GROUP BY 1
            ORDER BY 1
            """,
            [REGION_SADI, cutoff],
        ).fetchall()
    finally:
        conn.close()


def _load_generation_daily():
    conn = get_conn(readonly=True)
    try:
        return conn.execute(
            f"""
            SELECT date_trunc('day', ts - {AR_OFFSET}) AS d, count(*) AS n,
                   avg(total), avg(hidraulico), avg(termico), avg(nuclear),
                   avg(renovable), avg(importacion)
            FROM cammesa_generation
            WHERE region = ?
            GROUP BY 1
            ORDER BY 1
            """,
            [REGION_SADI],
        ).fetchall()
    finally:
        conn.close()


def _load_demand(cutoff, bucket: str):
    conn = get_conn(readonly=True)
    try:
        return conn.execute(
            f"""
            SELECT {bucket} AS t, avg(dem), avg(temp)
            FROM cammesa_demand
            WHERE region = ? AND ts >= ?
            GROUP BY 1
            ORDER BY 1
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
        ui.output_ui("gen_daily_chart"),
        ui.h2("Demanda · SADI"),
        ui.output_ui("demand_chart"),
        ui.p(
            "Fuente: CAMMESA (Total del SADI). CAMMESA's generation-by-source feed only "
            "exposes the current day, so this history is built by polling and starts "
            "when the ingest did; days the ingest missed stay empty. Demand is "
            "backfilled from CAMMESA's by-date endpoint.",
            class_="note",
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
        cards = [stat_card(
            "Generación total", f"{total / 1000:,.1f} GW" if total else "—",
            sub="SADI, last reading",
        )]
        for key, label, color in GEN_SOURCES:
            v = by_key[key]
            pct = f"{v / total * 100:.0f}%" if v is not None and total else "—"
            cards.append(stat_card(label, pct, sub=_fmt_mw(v), accent=color))
        age = (datetime.now(tz=timezone.utc) - ts).total_seconds()
        return stat_grid(*cards, footnote=f"Updated {fmt_age(age)}")

    @render.ui
    @busy_guard
    def gen_chart():
        bucket, step = STEPS[input.range()]
        rows = _load_generation_window(_cutoff(input.range()), bucket)
        if not rows:
            return ui.p("No generation data in this range yet.")
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
            f"Generación por fuente — {step} ({RANGES[input.range()]})", y_title="MW"
        ))
        return fig_html(fig)

    @render.ui
    @busy_guard
    def gen_daily_chart():
        rows = _load_generation_daily()
        if not rows:
            return ui.p("No generation data yet.")
        days = [r[0] for r in rows]
        coverage = [min(r[1] / POINTS_PER_DAY, 1) * 100 for r in rows]
        col = {"hidraulico": 3, "termico": 4, "nuclear": 5, "renovable": 6, "importacion": 7}
        fig = go.Figure()
        for key, label, color in GEN_SOURCES:
            shares = [
                (r[col[key]] or 0) / r[2] * 100 if r[2] else None for r in rows
            ]
            fig.add_trace(go.Bar(
                x=days, y=shares, name=label, marker=dict(color=color),
                customdata=coverage,
                width=DAY_MS * 0.85,
                hovertemplate=(
                    "%{x|%Y-%m-%d}<br>%{y:.1f}%<br>day coverage %{customdata:.0f}%"
                    "<extra>" + label + "</extra>"
                ),
            ))
        layout = base_layout(
            f"Matriz diaria — % of generation ({len(rows)} day(s))",
            y_title="%",
        )
        layout["barmode"] = "stack"
        layout["bargap"] = 0.15
        fig.update_layout(**layout)
        fig.update_yaxes(range=[0, 100])
        fig.update_layout(legend=LEGEND_BELOW, height=360)
        return fig_html(fig)

    @render.ui
    @busy_guard
    def demand_chart():
        bucket, step = STEPS[input.range()]
        rows = _load_demand(_cutoff(input.range()), bucket)
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
            f"Demanda — SADI, {step} ({RANGES[input.range()]})", y_title="MW"
        ))
        return fig_html(fig)
