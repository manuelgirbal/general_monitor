from shiny import ui

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
"""


def page_head():
    return [
        ui.tags.style(DARK_CSS),
        ui.tags.script(src=PLOTLY_CDN),
    ]


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


def fmt_sat_vb(v) -> str:
    return "—" if v is None else f"{v:.2f} sat/vB"


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
