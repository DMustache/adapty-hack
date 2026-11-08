"""Plotly figures. Colors: one categorical order (blue, orange, aqua); gray for reference lines."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

BLUE, ORANGE, AQUA, GRAY = "#2a78d6", "#eb6834", "#1baf7a", "#8a8984"


def _layout(fig: go.Figure, title: str, x: str, y: str, yfmt: str = None) -> go.Figure:
    fig.update_layout(title=title, xaxis_title=x, yaxis_title=y, hovermode="x unified",
                      margin=dict(l=10, r=10, t=50, b=10), legend=dict(orientation="h", y=-0.2))
    fig.update_xaxes(tickformat=".0%", showgrid=False)
    if yfmt:
        fig.update_yaxes(tickformat=yfmt)
    return fig


def revenue_curve(sim: pd.DataFrame, test_discount: float | None) -> go.Figure:
    base = sim.attrs["baseline_rev"]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=sim.discount, y=sim.rev_p95, line=dict(width=0), showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=sim.discount, y=sim.rev_p05, fill="tonexty", line=dict(width=0),
                             fillcolor="rgba(42,120,214,0.18)", name=sim.attrs.get("interval_label", "90% interval"),
                             hovertemplate="P05–P95: $%{y:.2f}"))
    fig.add_trace(go.Scatter(x=sim.discount, y=sim.rev_mean, line=dict(color=BLUE, width=2), mode="lines+markers",
                             marker=dict(size=8), name="Expected net revenue / exposed user",
                             hovertemplate="$%{y:.2f}"))
    fig.add_hline(y=base, line=dict(color=GRAY, dash="dash", width=1.5),
                  annotation_text=f"No discount: ${base:.2f}", annotation_position="bottom right")
    if test_discount:
        fig.add_vline(x=test_discount, line=dict(color=ORANGE, width=2),
                      annotation_text=f"Test candidate {test_discount:.0%}", annotation_position="top left")
    return _layout(fig, "Net contribution per eligible user over the horizon (after refunds, store fee, variable cost)",
                   "Discount", "USD per eligible user", "$.2f")


def breakeven_vs_assumed(sim: pd.DataFrame) -> go.Figure:
    s = sim[sim.discount > 0]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=s.discount, y=s.assumed_lift_p95, line=dict(width=0), showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=s.discount, y=s.assumed_lift_p05, fill="tonexty", line=dict(width=0),
                             fillcolor="rgba(235,104,52,0.18)", name="Assumed lift, 90% range (ASSUMED)",
                             hovertemplate="P05: %{y:.0%}"))
    fig.add_trace(go.Scatter(x=s.discount, y=s.assumed_lift_mode, line=dict(color=ORANGE, width=2, dash="dot"),
                             name="Assumed lift, most likely (ASSUMED)", hovertemplate="%{y:.0%}"))
    fig.add_trace(go.Scatter(x=s.discount, y=s.breakeven_lift, line=dict(color=BLUE, width=2), mode="lines+markers",
                             marker=dict(size=8), name="Break-even lift (CALCULATED: data + ρ, k)",
                             hovertemplate="%{y:.0%}"))
    return _layout(fig, "Conversion lift needed vs. lift assumed", "Discount",
                   "Relative conversion lift", ".0%")


def survival_curves(survivals: dict, products=("weekly", "monthly")) -> go.Figure:
    fig = go.Figure()
    for p, color in zip(products, (BLUE, ORANGE)):
        sv = survivals[p]
        n = len(sv.s)
        obs = min(sv.observed_periods, n)
        x = list(range(1, n + 1))
        fig.add_trace(go.Scatter(x=x[:obs], y=sv.s[:obs], line=dict(color=color, width=2), name=f"{p} (estimated from data)",
                                 hovertemplate="period %{x}: %{y:.0%}"))
        if obs < n:
            fig.add_trace(go.Scatter(x=x[obs - 1:], y=sv.s[obs - 1:], line=dict(color=color, width=2, dash="dot"),
                                     name=f"{p} (extrapolated tail, {sv.tail_retention:.1%}/period)",
                                     hovertemplate="period %{x}: %{y:.0%}"))
    fig.update_layout(title="Share of payers still paying, by paid period", xaxis_title="Paid period #",
                      yaxis_title="Still paying", hovermode="x unified", margin=dict(l=10, r=10, t=50, b=10),
                      legend=dict(orientation="h", y=-0.2))
    fig.update_yaxes(tickformat=".0%", range=[0, 1.02])
    return fig


def price_vs_conversion(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure(go.Scatter(
        x=df.price_index, y=df.conversion, mode="markers+text", text=df.country, textposition="top center",
        marker=dict(size=10, color=BLUE, line=dict(color="white", width=2)),
        customdata=df.installs,
        hovertemplate="%{text}: price %{x:.0%} of US, conversion %{y:.1%}<br>%{customdata} installs<extra></extra>"))
    fig.update_layout(title="Regional price vs. conversion (observational — confounded by country)",
                      xaxis_title="Local price as % of US price", yaxis_title="Install → paid conversion",
                      margin=dict(l=10, r=10, t=50, b=10))
    fig.update_xaxes(tickformat=".0%")
    fig.update_yaxes(tickformat=".0%")
    return fig


def sensitivity_heatmap(grid: pd.DataFrame, param: str, param_label: str,
                        lift_range: tuple[float, float]) -> go.Figure:
    """Best discount (under the assumptions) for each (assumed lift at 20% off) x (second assumption)."""
    pv = grid.pivot(index=param, columns="lift_at_20", values="best_discount")
    text = [[("✕" if v != v else ("—" if v == 0 else f"{v:.0%}")) for v in row] for row in pv.values]
    fig = go.Figure(go.Heatmap(
        z=pv.values, x=list(pv.columns), y=[f"{v:g}" for v in pv.index], text=text, texttemplate="%{text}",
        colorscale=[[0, "#eef1f5"], [0.01, "#cfe0f6"], [0.5, "#5b9be6"], [1, "#0d3b78"]], zmin=0, zmax=0.5,
        xgap=2, ygap=2, colorbar=dict(title="Best<br>discount", tickformat=".0%"),
        hovertemplate=f"Lift from 20% off: %{{x:.0%}}<br>{param_label}: %{{y}}"
                      "<br>Best discount under these assumptions: %{z:.0%}<extra></extra>"))
    fig.add_vrect(x0=lift_range[0], x1=lift_range[1], line=dict(color=ORANGE, width=2), fillcolor="rgba(0,0,0,0)",
                  annotation_text="your assumed range", annotation_position="top left")
    fig.update_layout(title="Best discount under each assumption (— = keep full price, ✕ = lift impossible under ceiling)",
                      xaxis_title="Assumed conversion lift from a 20% discount", yaxis_title=param_label,
                      margin=dict(l=10, r=10, t=60, b=10))
    fig.update_xaxes(tickformat=".0%")
    return fig
