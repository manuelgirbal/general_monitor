from datetime import datetime, timedelta, timezone

import plotly.graph_objects as go
from shiny import module, render, ui

from db import get_conn
from plots import base_layout, fmt_age

RANGES = {
    "all": "Total",
    "1y": "Last year",
    "6m": "Last 6 months",
    "1m": "Last month",
}
RANGE_DAYS = {"1y": 365, "6m": 182, "1m": 30}

CASA_LABELS = {
    "oficial": "Oficial",
    "blue": "Blue",
    "bolsa": "MEP",
    "contadoconliqui": "CCL",
    "mayorista": "Mayorista",
    "cripto": "USDC",
    "tarjeta": "Tarjeta",
}
DOLAR_CHART_CASAS = (
    ("oficial", "#5dade2"),
    ("blue", "#52be80"),
    ("bolsa", "#f4d03f"),
    ("contadoconliqui", "#e74c3c"),
    ("cripto", "#2775ca"),
)


def _cutoff(range_key: str):
    days = RANGE_DAYS.get(range_key)
    if days is None:
        return None
    return datetime.now(tz=timezone.utc) - timedelta(days=days)


def _fmt_ars(v) -> str:
    return "—" if v is None else f"${v:,.0f}"


def _fmt_usd_compact(v) -> str:
    if v is None:
        return "—"
    if v >= 1e9:
        return f"${v / 1e9:,.1f}B"
    if v >= 1e6:
        return f"${v / 1e6:,.1f}M"
    return f"${v:,.0f}"


def _load_dolar_latest():
    conn = get_conn(readonly=True)
    try:
        return conn.execute(
            """
            SELECT casa, arg_max(venta, ts) AS venta, max(ts) AS ts
            FROM dolar_rates
            GROUP BY casa
            """
        ).fetchall()
    finally:
        conn.close()


def _load_dolar_daily(cutoff=None):
    where = ""
    params = []
    if cutoff is not None:
        where = "WHERE ts >= ?"
        params.append(cutoff)
    conn = get_conn(readonly=True)
    try:
        return conn.execute(
            f"""
            SELECT date_trunc('day', ts) AS d, casa, arg_max(venta, ts) AS venta
            FROM dolar_rates
            {where}
            GROUP BY 1, 2
            ORDER BY 1
            """,
            params,
        ).fetchall()
    finally:
        conn.close()


def _load_riesgo(cutoff=None):
    where = ""
    params = []
    if cutoff is not None:
        where = "WHERE ts >= ?"
        params.append(cutoff)
    conn = get_conn(readonly=True)
    try:
        return conn.execute(
            f"SELECT ts, valor FROM riesgo_pais {where} ORDER BY ts",
            params,
        ).fetchall()
    finally:
        conn.close()


def _load_usdc_daily(cutoff=None):
    where = ""
    params = []
    if cutoff is not None:
        where = "WHERE ts >= ?"
        params.append(cutoff)
    conn = get_conn(readonly=True)
    try:
        return conn.execute(
            f"""
            SELECT date_trunc('day', ts) AS d, arg_max(circulating, ts) AS circ
            FROM usdc_supply
            {where}
            GROUP BY 1
            ORDER BY 1
            """,
            params,
        ).fetchall()
    finally:
        conn.close()


def _load_usdc_latest():
    conn = get_conn(readonly=True)
    try:
        return conn.execute(
            "SELECT ts, circulating, price FROM usdc_supply ORDER BY ts DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()


@module.ui
def macro_ar_ui():
    return ui.nav_panel(
        "Macro AR",
        ui.input_radio_buttons("range", "Range", choices=RANGES, selected="1y", inline=True),
        ui.h2("Dólar"),
        ui.output_ui("dolar_cards"),
        ui.output_ui("dolar_chart"),
        ui.h2("Riesgo país"),
        ui.output_ui("riesgo_card"),
        ui.output_ui("riesgo_chart"),
        ui.h2("USDC · supply"),
        ui.output_ui("usdc_card"),
        ui.output_ui("usdc_chart"),
        value="macro_ar",
    )


@module.server
def macro_ar_server(input, output, session):
    @render.ui
    def dolar_cards():
        rows = _load_dolar_latest()
        if not rows:
            return ui.p("No dollar data yet.")
        by_casa = {casa: (venta, ts) for casa, venta, ts in rows}
        cards = []
        for casa in ("oficial", "blue", "bolsa", "contadoconliqui", "cripto"):
            if casa not in by_casa:
                continue
            venta, _ts = by_casa[casa]
            cards.append(ui.tags.td(
                ui.h3(_fmt_ars(venta)),
                ui.p(CASA_LABELS[casa], style="opacity: 0.7;"),
            ))
        brecha = None
        if "oficial" in by_casa and "blue" in by_casa and by_casa["oficial"][0]:
            brecha = (by_casa["blue"][0] - by_casa["oficial"][0]) / by_casa["oficial"][0] * 100
        latest_ts = max(ts for _v, ts in by_casa.values())
        age = (datetime.now(tz=timezone.utc) - latest_ts).total_seconds()
        return ui.div(
            ui.tags.table(ui.tags.tbody(ui.tags.tr(*cards)), style="width:auto;"),
            ui.p(
                (f"Brecha blue/oficial: {brecha:+.1f}% · " if brecha is not None else "")
                + fmt_age(age)
            ),
        )

    @render.ui
    def dolar_chart():
        rows = _load_dolar_daily(_cutoff(input.range()))
        if not rows:
            return ui.p("No dollar data yet.")
        series = {casa: ([], []) for casa, _ in DOLAR_CHART_CASAS}
        for d, casa, venta in rows:
            if casa in series:
                series[casa][0].append(d)
                series[casa][1].append(venta)
        fig = go.Figure()
        for casa, color in DOLAR_CHART_CASAS:
            xs, ys = series[casa]
            if not xs:
                continue
            fig.add_trace(go.Scatter(
                x=xs, y=ys, mode="lines", name=CASA_LABELS[casa], line=dict(color=color),
            ))
        fig.update_layout(**base_layout(
            f"Dólar — venta, daily ({RANGES[input.range()]})", y_title="ARS"
        ))
        return ui.HTML(fig.to_html(include_plotlyjs=False, full_html=False))

    @render.ui
    def riesgo_card():
        rows = _load_riesgo()
        if not rows:
            return ui.p("No country-risk data yet. Run ", ui.tags.code("python -m scripts.backfill riesgo_pais_history"), ".")
        ts, valor = rows[-1]
        age = (datetime.now(tz=timezone.utc) - ts).total_seconds()
        return ui.div(ui.h3(f"{int(valor):,} bps"), ui.p(fmt_age(age)))

    @render.ui
    def riesgo_chart():
        rows = _load_riesgo(_cutoff(input.range()))
        if not rows:
            return ui.p("No country-risk data yet.")
        fig = go.Figure(go.Scatter(
            x=[r[0] for r in rows],
            y=[r[1] for r in rows],
            mode="lines",
            line=dict(color="#e74c3c"),
            hovertemplate="%{x|%Y-%m-%d}<br>%{y:,.0f} bps<extra></extra>",
        ))
        fig.update_layout(**base_layout(
            f"Riesgo país — EMBI+ ({RANGES[input.range()]})", y_title="bps"
        ))
        return ui.HTML(fig.to_html(include_plotlyjs=False, full_html=False))

    @render.ui
    def usdc_card():
        row = _load_usdc_latest()
        if row is None:
            return ui.p("No USDC data yet. Run ", ui.tags.code("python -m scripts.backfill usdc_history"), ".")
        ts, circulating, price = row
        age = (datetime.now(tz=timezone.utc) - ts).total_seconds()
        peg = f" · peg ${price:.4f}" if price is not None else ""
        return ui.div(
            ui.h3(_fmt_usd_compact(circulating)),
            ui.p(f"Global circulating supply, all chains{peg} · {fmt_age(age)}"),
            ui.p(
                "Worldwide USDC in circulation across every blockchain — not "
                "Argentina-specific.",
                style="opacity: 0.7; font-size: 0.85em;",
            ),
        )

    @render.ui
    def usdc_chart():
        rows = _load_usdc_daily(_cutoff(input.range()))
        if not rows:
            return ui.p("No USDC data yet.")
        fig = go.Figure(go.Scatter(
            x=[r[0] for r in rows],
            y=[r[1] for r in rows],
            mode="lines",
            line=dict(color="#2775ca"),
            hovertemplate="%{x|%Y-%m-%d}<br>$%{y:,.0f}<extra></extra>",
        ))
        fig.update_layout(**base_layout(
            f"USDC circulating supply ({RANGES[input.range()]})", y_title="USD"
        ))
        return ui.HTML(fig.to_html(include_plotlyjs=False, full_html=False))
