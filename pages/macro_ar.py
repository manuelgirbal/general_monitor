from datetime import datetime, timedelta, timezone

import plotly.graph_objects as go
from shiny import module, render, ui

from db import get_conn
from plots import (
    LEGEND_BELOW,
    add_range_buttons,
    base_layout,
    busy_guard,
    fig_html,
    fmt_age,
    pct_change,
    stat_card,
    stat_grid,
)

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
SEMESTERS = {1: "1S", 7: "2S"}
# BCRA's inflation series go back to 1943; the 1989-91 hyperinflation (~20,000% y/y)
# would flatten everything else, so charts start when the REM survey does.
INFLATION_SINCE = datetime(2004, 1, 1, tzinfo=timezone.utc)


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


def _fmt_pct(v, decimals: int = 1) -> str:
    return "—" if v is None else f"{v:.{decimals}f}%"


def _quarter(ts) -> str:
    return f"{(ts.month - 1) // 3 + 1}T{ts.year}"


def _semester(ts) -> str:
    return f"{SEMESTERS.get(ts.month, '?')}{ts.year}"


def _month(ts) -> str:
    return ts.strftime("%b %Y")


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


def _load_series(series: str, cutoff=None):
    where = "WHERE series = ?"
    params = [series]
    if cutoff is not None:
        where += " AND ts >= ?"
        params.append(cutoff)
    conn = get_conn(readonly=True)
    try:
        return conn.execute(
            f"SELECT ts, value FROM macro_series {where} ORDER BY ts",
            params,
        ).fetchall()
    finally:
        conn.close()


def _load_series_many(series: tuple[str, ...]) -> dict[str, list]:
    conn = get_conn(readonly=True)
    try:
        rows = conn.execute(
            f"""
            SELECT series, ts, value FROM macro_series
            WHERE series IN ({", ".join("?" * len(series))})
            ORDER BY ts
            """,
            list(series),
        ).fetchall()
    finally:
        conn.close()
    out = {s: [] for s in series}
    for s, ts, value in rows:
        out[s].append((ts, value))
    return out


def _last_two(rows):
    if not rows:
        return None, None, None
    ts, last = rows[-1]
    prev = rows[-2][1] if len(rows) > 1 else None
    return ts, last, prev


def _line(rows, color, hover, name=None, scale: float = 1.0):
    return go.Scatter(
        x=[r[0] for r in rows],
        y=[r[1] * scale for r in rows],
        mode="lines",
        name=name,
        line=dict(color=color, width=2),
        hovertemplate=hover,
    )


def _missing(what: str, cmd: str | None = None):
    if cmd:
        return ui.p(f"No {what} data yet. Run ", ui.tags.code(cmd), ".")
    return ui.p(f"No {what} data yet.")


@module.ui
def macro_ar_ui():
    return ui.nav_panel(
        "Macro AR",
        ui.input_radio_buttons("range", "Range", choices=RANGES, selected="1y", inline=True),
        ui.h2("Dólar"),
        ui.output_ui("dolar_cards"),
        ui.output_ui("dolar_chart"),
        ui.h2("Inflación · BCRA"),
        ui.output_ui("inflation_cards"),
        ui.div(
            ui.output_ui("inflation_monthly_chart"),
            ui.output_ui("inflation_yoy_chart"),
            class_="chart-grid",
        ),
        ui.h2("Riesgo país · reservas"),
        ui.output_ui("riesgo_reservas_cards"),
        ui.div(
            ui.output_ui("riesgo_chart"),
            ui.output_ui("reservas_chart"),
            class_="chart-grid",
        ),
        ui.h2("Social · INDEC"),
        ui.output_ui("social_cards"),
        ui.div(
            ui.output_ui("pobreza_chart"),
            ui.output_ui("desocupacion_chart"),
            ui.output_ui("gini_chart"),
            class_="chart-grid",
        ),
        ui.h2("Confianza · Di Tella"),
        ui.output_ui("ditella_cards"),
        ui.div(
            ui.output_ui("icc_chart"),
            ui.output_ui("icg_chart"),
            class_="chart-grid",
        ),
        ui.h2("USDC · supply"),
        ui.output_ui("usdc_card"),
        ui.output_ui("usdc_chart"),
        ui.p(
            "Sources: dolarapi.com and argentinadatos.com (dollar, country risk), "
            "BCRA API (inflation, REM expectations, reserves), datos.gob.ar series API "
            "(INDEC EPH: poverty, unemployment, Gini; Universidad Torcuato Di Tella: "
            "ICC, ICG), DefiLlama (USDC). Low-frequency charts show their full history "
            "and ignore the range selector — use the 5y / 10y / All buttons.",
            class_="note",
        ),
        value="macro_ar",
    )


@module.server
def macro_ar_server(input, output, session):
    @render.ui
    @busy_guard
    def dolar_cards():
        rows = _load_dolar_latest()
        if not rows:
            return _missing("dollar")
        by_casa = {casa: (venta, ts) for casa, venta, ts in rows}
        cards = []
        for casa, color in DOLAR_CHART_CASAS:
            if casa not in by_casa:
                continue
            venta, _ts = by_casa[casa]
            cards.append(stat_card(CASA_LABELS[casa], _fmt_ars(venta), sub="venta", accent=color))
        brecha = None
        if "oficial" in by_casa and "blue" in by_casa and by_casa["oficial"][0]:
            brecha = pct_change(by_casa["blue"][0], by_casa["oficial"][0])
        if brecha is not None:
            cards.append(stat_card("Brecha blue / oficial", f"{brecha:+.1f}%"))
        latest_ts = max(ts for _v, ts in by_casa.values())
        age = (datetime.now(tz=timezone.utc) - latest_ts).total_seconds()
        return stat_grid(*cards, footnote=f"Updated {fmt_age(age)}")

    @render.ui
    @busy_guard
    def dolar_chart():
        rows = _load_dolar_daily(_cutoff(input.range()))
        if not rows:
            return _missing("dollar")
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
        return fig_html(fig)

    @render.ui
    @busy_guard
    def inflation_cards():
        data = _load_series_many(
            ("inflacion_mensual", "inflacion_interanual", "inflacion_esperada")
        )
        if not any(data.values()):
            return _missing("inflation", "python -m scripts.backfill bcra_history")
        cards = []
        ts, last, prev = _last_two(data["inflacion_mensual"])
        if ts is not None:
            cards.append(stat_card(
                "Inflación mensual", _fmt_pct(last),
                sub=f"{_month(ts)} · prev {_fmt_pct(prev)}", accent="#e74c3c",
            ))
        ts, last, prev = _last_two(data["inflacion_interanual"])
        if ts is not None:
            cards.append(stat_card(
                "Inflación interanual", _fmt_pct(last),
                sub=f"{_month(ts)} · prev {_fmt_pct(prev)}", accent="#f4d03f",
            ))
        ts, last, prev = _last_two(data["inflacion_esperada"])
        if ts is not None:
            cards.append(stat_card(
                "Expectativa 12 meses (REM)", _fmt_pct(last),
                sub=f"{_month(ts)} · median", accent="#5dade2",
            ))
        return stat_grid(*cards)

    @render.ui
    @busy_guard
    def inflation_monthly_chart():
        rows = _load_series("inflacion_mensual", INFLATION_SINCE)
        if not rows:
            return _missing("inflation")
        fig = go.Figure(go.Bar(
            x=[r[0] for r in rows],
            y=[r[1] for r in rows],
            marker=dict(color="#e74c3c"),
            hovertemplate="%{x|%b %Y}<br>%{y:.1f}%<extra></extra>",
        ))
        fig.update_layout(**base_layout("Inflación mensual — CPI m/m", y_title="%"))
        add_range_buttons(fig, default_years=5)
        return fig_html(fig)

    @render.ui
    @busy_guard
    def inflation_yoy_chart():
        data = {
            s: _load_series(s, INFLATION_SINCE)
            for s in ("inflacion_interanual", "inflacion_esperada")
        }
        if not data["inflacion_interanual"]:
            return _missing("inflation")
        fig = go.Figure()
        fig.add_trace(_line(
            data["inflacion_interanual"], "#f4d03f",
            "%{x|%b %Y}<br>%{y:.1f}%<extra>Observed</extra>", name="Observed y/y",
        ))
        if data["inflacion_esperada"]:
            fig.add_trace(_line(
                data["inflacion_esperada"], "#5dade2",
                "%{x|%b %Y}<br>%{y:.1f}%<extra>Expected</extra>",
                name="Expected next 12m (REM)",
            ))
        fig.update_layout(**base_layout("Inflación interanual vs expectativa", y_title="%"))
        fig.update_layout(legend=LEGEND_BELOW, height=360)
        add_range_buttons(fig, default_years=5)
        return fig_html(fig)

    @render.ui
    @busy_guard
    def riesgo_reservas_cards():
        riesgo = _load_riesgo(_cutoff(input.range()))
        reservas = _load_series("reservas", _cutoff(input.range()))
        cards = []
        if riesgo:
            ts, valor = riesgo[-1]
            cards.append(stat_card(
                "Riesgo país (EMBI)", f"{int(valor):,} bps",
                delta=(pct_change(valor, riesgo[0][1]), RANGES[input.range()].lower()),
                up_is_good=False,
                sub=ts.strftime("%Y-%m-%d"),
                accent="#e74c3c",
            ))
        if reservas:
            ts, valor = reservas[-1]
            cards.append(stat_card(
                "Reservas BCRA", f"US${valor / 1000:,.1f}B",
                delta=(pct_change(valor, reservas[0][1]), RANGES[input.range()].lower()),
                sub=ts.strftime("%Y-%m-%d"),
                accent="#52be80",
            ))
        if not cards:
            return _missing("country-risk / reserves", "python -m scripts.backfill bcra_history")
        return stat_grid(*cards)

    @render.ui
    @busy_guard
    def riesgo_chart():
        rows = _load_riesgo(_cutoff(input.range()))
        if not rows:
            return _missing(
                "country-risk", "python -m scripts.backfill riesgo_pais_history"
            )
        fig = go.Figure(_line(rows, "#e74c3c", "%{x|%Y-%m-%d}<br>%{y:,.0f} bps<extra></extra>"))
        fig.update_layout(**base_layout(
            f"Riesgo país — EMBI ({RANGES[input.range()]})", y_title="bps"
        ))
        return fig_html(fig)

    @render.ui
    @busy_guard
    def reservas_chart():
        rows = _load_series("reservas", _cutoff(input.range()))
        if not rows:
            return _missing("reserves")
        fig = go.Figure(_line(
            rows, "#52be80", "%{x|%Y-%m-%d}<br>US$%{y:,.0f}M<extra></extra>"
        ))
        fig.update_layout(**base_layout(
            f"Reservas internacionales BCRA ({RANGES[input.range()]})", y_title="USD M"
        ))
        return fig_html(fig)

    @render.ui
    @busy_guard
    def social_cards():
        data = _load_series_many(("pobreza", "desocupacion", "gini"))
        if not any(data.values()):
            return _missing("INDEC")
        cards = []
        ts, last, prev = _last_two(data["pobreza"])
        if ts is not None:
            cards.append(stat_card(
                "Pobreza (personas)", _fmt_pct(last * 100),
                sub=f"{_semester(ts)} · prev {_fmt_pct(prev * 100 if prev else None)}",
                accent="#e74c3c",
            ))
        ts, last, prev = _last_two(data["desocupacion"])
        if ts is not None:
            cards.append(stat_card(
                "Desocupación", _fmt_pct(last * 100),
                sub=f"{_quarter(ts)} · prev {_fmt_pct(prev * 100 if prev else None)}",
                accent="#f4d03f",
            ))
        ts, last, prev = _last_two(data["gini"])
        if ts is not None:
            cards.append(stat_card(
                "Coeficiente de Gini", f"{last:.3f}",
                sub=f"{_quarter(ts)} · prev {prev:.3f}" if prev else _quarter(ts),
                accent="#9b59b6",
            ))
        return stat_grid(
            *cards,
            footnote="EPH, 31 urban agglomerations. Poverty is semiannual; "
            "unemployment and Gini (per-capita household income) are quarterly.",
        )

    @render.ui
    @busy_guard
    def pobreza_chart():
        rows = _load_series("pobreza")
        if not rows:
            return _missing("poverty")
        # INDEC published no EPH poverty data for 2007-2015; break the line there
        # instead of drawing a straight segment across the missing years.
        xs, ys, labels = [], [], []
        for i, (ts, value) in enumerate(rows):
            if i and (ts - rows[i - 1][0]).days > 400:
                xs.append(ts)
                ys.append(None)
                labels.append("")
            xs.append(ts)
            ys.append(value * 100)
            labels.append(_semester(ts))
        fig = go.Figure(go.Scatter(
            x=xs,
            y=ys,
            customdata=labels,
            mode="lines+markers",
            line=dict(color="#e74c3c", width=2),
            marker=dict(size=6),
            connectgaps=False,
            hovertemplate="%{customdata}<br>%{y:.1f}%<extra></extra>",
        ))
        fig.update_layout(**base_layout("Pobreza — % personas (semestral)", y_title="%"))
        add_range_buttons(fig)
        return fig_html(fig)

    @render.ui
    @busy_guard
    def desocupacion_chart():
        rows = _load_series("desocupacion")
        if not rows:
            return _missing("unemployment")
        fig = go.Figure(go.Scatter(
            x=[r[0] for r in rows],
            y=[r[1] * 100 for r in rows],
            customdata=[_quarter(r[0]) for r in rows],
            mode="lines",
            line=dict(color="#f4d03f", width=2),
            hovertemplate="%{customdata}<br>%{y:.1f}%<extra></extra>",
        ))
        fig.update_layout(**base_layout("Desocupación — % PEA (trimestral)", y_title="%"))
        add_range_buttons(fig)
        return fig_html(fig)

    @render.ui
    @busy_guard
    def gini_chart():
        rows = _load_series("gini")
        if not rows:
            return _missing("Gini")
        fig = go.Figure(go.Scatter(
            x=[r[0] for r in rows],
            y=[r[1] for r in rows],
            customdata=[_quarter(r[0]) for r in rows],
            mode="lines",
            line=dict(color="#9b59b6", width=2),
            hovertemplate="%{customdata}<br>%{y:.3f}<extra></extra>",
        ))
        fig.update_layout(**base_layout(
            "Gini — ingreso per cápita familiar (trimestral)", y_title="0 = equal, 1 = unequal"
        ))
        add_range_buttons(fig)
        return fig_html(fig)

    @render.ui
    @busy_guard
    def ditella_cards():
        data = _load_series_many(("icc", "icg"))
        if not any(data.values()):
            return _missing("Di Tella")
        cards = []
        ts, last, prev = _last_two(data["icc"])
        if ts is not None:
            cards.append(stat_card(
                "Confianza del consumidor (ICC)", f"{last:.1f}",
                delta=(pct_change(last, prev), "m/m"),
                sub=f"{_month(ts)} · scale 0–100", accent="#5dade2",
            ))
        ts, last, prev = _last_two(data["icg"])
        if ts is not None:
            cards.append(stat_card(
                "Confianza en el gobierno (ICG)", f"{last:.2f}",
                delta=(pct_change(last, prev), "m/m"),
                sub=f"{_month(ts)} · scale 0–5", accent="#52be80",
            ))
        return stat_grid(*cards)

    @render.ui
    @busy_guard
    def icc_chart():
        rows = _load_series("icc")
        if not rows:
            return _missing("ICC")
        fig = go.Figure(_line(rows, "#5dade2", "%{x|%b %Y}<br>%{y:.1f}<extra></extra>"))
        fig.update_layout(**base_layout("Índice de Confianza del Consumidor", y_title="0–100"))
        add_range_buttons(fig)
        return fig_html(fig)

    @render.ui
    @busy_guard
    def icg_chart():
        rows = _load_series("icg")
        if not rows:
            return _missing("ICG")
        fig = go.Figure(_line(rows, "#52be80", "%{x|%b %Y}<br>%{y:.2f}<extra></extra>"))
        fig.update_layout(**base_layout("Índice de Confianza en el Gobierno", y_title="0–5"))
        add_range_buttons(fig)
        return fig_html(fig)

    @render.ui
    @busy_guard
    def usdc_card():
        row = _load_usdc_latest()
        if row is None:
            return _missing("USDC", "python -m scripts.backfill usdc_history")
        ts, circulating, price = row
        age = (datetime.now(tz=timezone.utc) - ts).total_seconds()
        rows = _load_usdc_daily(_cutoff(input.range()))
        delta = None
        if rows:
            delta = (pct_change(circulating, rows[0][1]), RANGES[input.range()].lower())
        cards = [stat_card(
            "USDC circulating supply", _fmt_usd_compact(circulating),
            delta=delta, sub="global, all chains", accent="#2775ca",
        )]
        if price is not None:
            cards.append(stat_card("USDC peg", f"${price:.4f}"))
        return stat_grid(
            *cards,
            footnote=f"Worldwide USDC across every blockchain — not Argentina-specific. "
            f"Updated {fmt_age(age)}",
        )

    @render.ui
    @busy_guard
    def usdc_chart():
        rows = _load_usdc_daily(_cutoff(input.range()))
        if not rows:
            return _missing("USDC")
        fig = go.Figure(_line(rows, "#2775ca", "%{x|%Y-%m-%d}<br>$%{y:,.0f}<extra></extra>"))
        fig.update_layout(**base_layout(
            f"USDC circulating supply ({RANGES[input.range()]})", y_title="USD"
        ))
        return fig_html(fig)
