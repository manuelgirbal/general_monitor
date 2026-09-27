import functools

from shiny import ui

from db import DBBusy

PLOTLY_TEMPLATE = "plotly_dark"
PLOTLY_CDN = "https://cdn.plot.ly/plotly-2.35.2.min.js"
BTC_ORANGE = "#f7931a"
BG = "#111"

DARK_CSS = """
html, body { background: #111; color: #eee; margin: 0;
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }
.container-fluid { padding: 24px; max-width: 1100px; margin: 0 auto; }
h1, h2, h3 { color: #fff; font-weight: 400; margin: 0.4em 0; }
h1 { font-size: 1.8em; }
h2 { font-size: 1.3em; color: #f7931a; border-bottom: 1px solid #333;
    padding-bottom: 6px; }
h3 { font-size: 1.1em; color: #ccc; }
p { color: #bbb; }
table { border-collapse: collapse; width: 100%; margin-top: 12px;
    font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 13px; }
th, td { padding: 6px 10px; border-bottom: 1px solid #2a2a2a; text-align: left; }
th { color: #888; font-weight: 600; }
code { background: #222; color: #f7931a; padding: 2px 5px; border-radius: 3px; }
a { color: #5dade2; }
.js-plotly-plot { margin: 12px 0; border: 1px solid #222; border-radius: 4px; }
.navbar { background: #1a1a1a !important; border-bottom: 1px solid #333; }
.navbar .navbar-brand { color: #fff !important; font-weight: 400; }
.navbar .nav-link { color: #bbb !important; }
.navbar .nav-link.active { color: #f7931a !important; }
.stat-grid { display: grid; gap: 12px; margin: 12px 0;
    grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); }
.stat-card { background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 8px;
    padding: 14px 16px; border-top: 3px solid var(--accent, #2a2a2a); min-width: 0; }
.stat-card .stat-label { color: #999; font-size: 0.8em; letter-spacing: 0.02em;
    margin: 0 0 6px; }
.stat-card .stat-value { color: #fff; font-size: 1.7em; font-weight: 600;
    line-height: 1.1; margin: 0; white-space: nowrap; }
.stat-card .stat-delta { font-size: 0.85em; margin: 6px 0 0; }
.stat-card .stat-sub { color: #888; font-size: 0.8em; margin: 4px 0 0; }
.stat-footnote { color: #777; font-size: 0.8em; margin: -4px 0 12px; }
.chart-grid { display: grid; gap: 0 16px;
    grid-template-columns: repeat(auto-fit, minmax(420px, 1fr)); }
@media (max-width: 520px) { .chart-grid { grid-template-columns: 1fr; } }
.note { opacity: 0.7; font-size: 0.85em; }
"""

UP_COLOR = "#52be80"
DOWN_COLOR = "#e74c3c"


def page_head():
    return [
        ui.tags.style(DARK_CSS),
        ui.tags.script(src=PLOTLY_CDN),
    ]


def busy_guard(fn):
    """Wrap a render.ui body so a DB write-lock shows a soft notice, not a stack."""
    @functools.wraps(fn)
    def wrapper():
        try:
            return fn()
        except DBBusy:
            return ui.p("Data refreshing…", style="opacity: 0.5;")
    return wrapper


def stat_card(label: str, value: str, sub=None, delta=None, up_is_good=True, accent=None):
    """KPI tile. `delta` is (pct_change, period_label); its color encodes direction × good/bad."""
    children = [
        ui.p(label, class_="stat-label"),
        ui.p(value, class_="stat-value"),
    ]
    if delta is not None and delta[0] is not None:
        pct, period = delta
        good = (pct >= 0) == up_is_good
        arrow = "▲" if pct >= 0 else "▼"
        children.append(ui.p(
            f"{arrow} {pct:+.1f}% {period}",
            class_="stat-delta",
            style=f"color: {UP_COLOR if good else DOWN_COLOR};",
        ))
    if sub:
        children.append(ui.p(sub, class_="stat-sub"))
    style = f"--accent: {accent};" if accent else None
    return ui.div(*children, class_="stat-card", style=style)


def stat_grid(*cards, footnote=None):
    grid = ui.div(*[c for c in cards if c is not None], class_="stat-grid")
    if footnote:
        return ui.div(grid, ui.p(footnote, class_="stat-footnote"))
    return grid


def pct_change(new, old):
    if new is None or not old:
        return None
    return (new - old) / old * 100


def base_layout(title: str, y_title: str = "", x_title: str = "UTC") -> dict:
    return dict(
        template=PLOTLY_TEMPLATE,
        title=title,
        xaxis_title=x_title,
        yaxis_title=y_title,
        margin=dict(l=50, r=30, t=50, b=40),
        height=320,
        paper_bgcolor=BG,
        plot_bgcolor=BG,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )


LEGEND_BELOW = dict(orientation="h", yanchor="top", y=-0.2, xanchor="left", x=0)


def fig_html(fig):
    return ui.HTML(fig.to_html(include_plotlyjs=False, full_html=False))


def add_range_buttons(fig, default_years=None):
    """Client-side zoom buttons for long, low-frequency series that ignore the page range."""
    fig.update_xaxes(rangeselector=dict(
        buttons=[
            dict(count=5, label="5y", step="year", stepmode="backward"),
            dict(count=10, label="10y", step="year", stepmode="backward"),
            dict(step="all", label="All"),
        ],
        bgcolor="#222", activecolor="#444", font=dict(color="#ddd"),
        x=0, y=1.0, yanchor="bottom",
    ))
    if default_years:
        end = max(max(t.x) for t in fig.data if len(t.x))
        fig.update_xaxes(range=[end.replace(year=end.year - default_years), end])
    return fig


def fmt_sat_vb(v) -> str:
    return "—" if v is None else f"{v:.2f} sat/vB"


def fmt_usd(v) -> str:
    return "—" if v is None else f"${v:,.0f}"


def fmt_ehs(v) -> str:
    return "—" if v is None else f"{v:,.1f} EH/s"


def fmt_int(v) -> str:
    return "—" if v is None else f"{int(v):,}"


def fmt_age(seconds: float) -> str:
    if seconds is None:
        return "—"
    if seconds < 60:
        return f"{int(seconds)}s ago"
    if seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    if seconds < 86400:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        return f"{h}h {m}m ago"
    return f"{int(seconds // 86400)}d ago"
