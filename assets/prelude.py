import importlib.util
from pathlib import Path

import plotly.graph_objects as go
from dash import Dash, Input, Output, dcc, html

_HELPER_SPEC = importlib.util.spec_from_file_location(
    "dash_server_generated_exasol_helper",
    Path(__file__).with_name("dash_server_exasol.py"),
)
assert _HELPER_SPEC is not None and _HELPER_SPEC.loader is not None
_HELPER_MODULE = importlib.util.module_from_spec(_HELPER_SPEC)
_HELPER_SPEC.loader.exec_module(_HELPER_MODULE)
load_row = _HELPER_MODULE.load_row
load_rows = _HELPER_MODULE.load_rows
has_error = _HELPER_MODULE.has_error
render_error_panel = _HELPER_MODULE.render_error_panel

# --- Design tokens (validated palette; light surface) -----------------------
SURFACE = "#fcfcfb"
PAGE = "#f9f9f7"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
BORDER = "rgba(11,11,11,0.10)"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]
SERIES_1, SERIES_2 = SERIES[0], SERIES[1]
CRITICAL = "#d03b3b"
GOOD = "#006300"
BAD = "#d03b3b"
FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'

CARD = {
    "backgroundColor": SURFACE,
    "border": f"1px solid {BORDER}",
    "borderRadius": "12px",
    "padding": "1.1rem 1.25rem",
}
GRID_2 = {
    "display": "grid",
    "gridTemplateColumns": "repeat(auto-fit, minmax(340px, 1fr))",
    "gap": "0.9rem",
    "marginTop": "0.9rem",
}
KPI_GRID = {
    "display": "grid",
    "gridTemplateColumns": "repeat(auto-fit, minmax(215px, 1fr))",
    "gap": "0.9rem",
}
PAGE_STYLE = {
    "fontFamily": FONT,
    "backgroundColor": PAGE,
    "padding": "2rem",
    "minHeight": "100vh",
    "boxSizing": "border-box",
}
DROPDOWN = {"minWidth": "220px", "fontSize": "13px"}


def _f(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _i(value):
    return int(_f(value))


def _money(value):
    amount = _f(value)
    if abs(amount) >= 1_000_000_000:
        return f"${amount / 1_000_000_000:,.2f}B"
    if abs(amount) >= 1_000_000:
        return f"${amount / 1_000_000:,.1f}M"
    if abs(amount) >= 1_000:
        return f"${amount / 1_000:,.0f}K"
    return f"${amount:,.0f}"


def _flag(text, good):
    """State is carried by a glyph and a word, never by colour alone."""
    return html.Span(
        f"{'▼' if good else '▲'} {text}",
        style={"color": GOOD if good else BAD, "fontSize": "12px", "fontWeight": 600},
    )


def _state(text, tone="neutral"):
    """A descriptive state label. No arrow — arrows are reserved for changes."""
    colour = {"good": GOOD, "bad": BAD, "neutral": INK_2}[tone]
    return html.Span(text, style={"color": colour, "fontSize": "12px", "fontWeight": 600})


def _delta(value, unit, higher_is_better=True, suffix="vs prior year"):
    amount = _f(value)
    rising = amount >= 0
    good = rising if higher_is_better else not rising
    return html.Span(
        f"{'▲' if rising else '▼'} {abs(amount):,.2f}{unit} {suffix}",
        style={"color": GOOD if good else BAD, "fontSize": "12px", "fontWeight": 600},
    )


def _tile(label, value, note=None, flag=None):
    children = [
        html.Div(label, style={"fontSize": "12px", "color": INK_2, "letterSpacing": "0.02em"}),
        html.Div(value, style={"fontSize": "30px", "fontWeight": 650, "color": INK,
                               "margin": "0.35rem 0 0.3rem"}),
    ]
    if flag is not None:
        children.append(flag)
    if note:
        children.append(html.Div(note, style={"fontSize": "12px", "color": MUTED, "marginTop": "0.25rem"}))
    return html.Div(children, style=CARD)


def _base_figure(title, y_title, height=320, x_title=None):
    figure = go.Figure()
    figure.update_layout(
        title={"text": title, "font": {"size": 14, "color": INK}, "x": 0, "xanchor": "left"},
        height=height,
        margin={"l": 60, "r": 24, "t": 46, "b": 48},
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        font={"family": FONT, "color": INK_2, "size": 12},
        hovermode="x unified",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0, "font": {"size": 11}},
        xaxis={"showgrid": False, "linecolor": AXIS, "tickfont": {"color": MUTED}, "ticks": "outside",
               "tickcolor": AXIS,
               "title": {"text": x_title, "font": {"size": 11, "color": MUTED}} if x_title else None},
        yaxis={"title": {"text": y_title, "font": {"size": 11, "color": MUTED}}, "gridcolor": GRID,
               "zerolinecolor": AXIS, "linecolor": "rgba(0,0,0,0)", "tickfont": {"color": MUTED}},
    )
    return figure


def _empty_figure(message, height=320):
    figure = _base_figure("", "", height=height)
    figure.add_annotation(text=message, showarrow=False, font={"color": MUTED, "size": 12})
    figure.update_xaxes(visible=False)
    figure.update_yaxes(visible=False)
    return figure


def _table(rows, columns, min_width="760px"):
    header = html.Thead(
        html.Tr([
            html.Th(label, style={"textAlign": align, "padding": "0.5rem 0.75rem",
                                  "borderBottom": f"1px solid {AXIS}", "fontSize": "12px",
                                  "color": INK_2, "fontWeight": 600})
            for label, align, _ in columns
        ])
    )
    body = html.Tbody([
        html.Tr([
            html.Td(render(row), style={"textAlign": align, "padding": "0.45rem 0.75rem",
                                        "borderBottom": f"1px solid {GRID}", "fontSize": "13px",
                                        "color": INK, "fontVariantNumeric": "tabular-nums",
                                        "whiteSpace": "nowrap"})
            for _, align, render in columns
        ])
        for row in rows
    ])
    return html.Div(
        html.Table([header, body],
                   style={"borderCollapse": "collapse", "width": "100%", "minWidth": min_width}),
        style={"overflowX": "auto"},
    )


def _notes(title, items):
    return html.Div(
        [
            html.Strong(title, style={"color": INK_2}),
            html.Ul(items, style={"margin": "0.5rem 0 0", "paddingLeft": "1.1rem"}),
        ],
        style={"fontSize": "12px", "color": MUTED, "marginTop": "1.25rem", "lineHeight": 1.6},
    )


def _header(title, filters):
    return html.Div(
        [
            html.Div([
                html.H1(title, style={"fontSize": "24px", "margin": 0, "color": INK, "fontWeight": 650}),
                html.Div(id="asof-caption",
                         style={"color": INK_2, "fontSize": "13px", "marginTop": "0.35rem"}),
            ]),
            html.Div(filters, style={"display": "flex", "gap": "0.75rem", "alignItems": "flex-end"}),
        ],
        style={"display": "flex", "justifyContent": "space-between", "alignItems": "flex-end",
               "gap": "1.5rem", "flexWrap": "wrap", "marginBottom": "1.25rem"},
    )


def _filter(component_id, label, placeholder):
    return html.Div([
        html.Label(label, style={"fontSize": "11px", "color": MUTED}),
        dcc.Dropdown(id=component_id, options=[], value=None, placeholder=placeholder, style=DROPDOWN),
    ])
