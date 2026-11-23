"""Gráficos Plotly do painel. Paleta: azul para a previsão, tinta neutra para o observado."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

AZUL = "#2a78d6"
BANDA_90 = "rgba(42, 120, 214, 0.20)"
BANDA_50 = "rgba(42, 120, 214, 0.40)"
TINTA = "#52514e"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]


def _layout(fig: go.Figure, titulo_y: str, altura: int = 420) -> go.Figure:
    fig.update_layout(
        height=altura,
        margin=dict(l=10, r=10, t=30, b=10),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        yaxis=dict(title=titulo_y, rangemode="tozero", gridcolor="rgba(128,128,128,0.18)"),
        xaxis=dict(showgrid=False),
    )
    return fig


def fan_chart(obs: pd.DataFrame, faixas: pd.DataFrame, limiar: float | None,
              titulo_y: str = "Casos por semana") -> go.Figure:
    """Observado + mediana prevista com intervalos de 50% e 90% e linha do limiar de alerta."""
    fig = go.Figure()
    if not faixas.empty:
        # Ancora as faixas na última semana observada para a previsão "sair" da série.
        ultima = obs.iloc[-1]
        f = faixas.copy()
        if f["semana_alvo"].min() > ultima["inicio_semana"]:
            ancora = {c: ultima["y"] for c in f.columns if c.startswith("q")}
            ancora["semana_alvo"] = ultima["inicio_semana"]
            f = pd.concat([pd.DataFrame([ancora]), f], ignore_index=True)
        x = f["semana_alvo"]
        for lo, hi, cor, nome in (("q0.05", "q0.95", BANDA_90, "Intervalo de 90%"),
                                  ("q0.25", "q0.75", BANDA_50, "Intervalo de 50%")):
            fig.add_trace(go.Scatter(x=x, y=f[hi], mode="lines", line=dict(width=0),
                                     hoverinfo="skip", showlegend=False))
            fig.add_trace(go.Scatter(x=x, y=f[lo], mode="lines", line=dict(width=0), fill="tonexty",
                                     fillcolor=cor, name=nome,
                                     customdata=f[hi], hovertemplate=f"{nome}: %{{y:.0f}}–%{{customdata:.0f}}<extra></extra>"))
        fig.add_trace(go.Scatter(x=x, y=f["q0.5"], mode="lines", line=dict(color=AZUL, width=2),
                                 name="Mediana prevista", hovertemplate="Mediana: %{y:.0f}<extra></extra>"))

    fig.add_trace(go.Scatter(x=obs["inicio_semana"], y=obs["y"], mode="lines",
                             line=dict(color=TINTA, width=2), name="Observado",
                             hovertemplate="Observado: %{y:.0f}<extra></extra>"))
    nc = obs[obs["nowcast"].astype(bool)]
    if len(nc):
        fig.add_trace(go.Scatter(x=nc["inicio_semana"], y=nc["y"], mode="markers",
                                 marker=dict(size=9, color="white", line=dict(color=TINTA, width=2)),
                                 name="Nowcasting (semanas recentes)",
                                 hovertemplate="Nowcasting: %{y:.0f}<extra></extra>"))
    if limiar is not None:
        fig.add_hline(y=limiar, line=dict(color=TINTA, dash="dash", width=1),
                      annotation_text="limiar de alerta", annotation_position="top right")
    return _layout(fig, titulo_y)


def barras_risco(ranking: pd.DataFrame) -> go.Figure:
    """Probabilidade de ultrapassar o limiar, por município (uma cor: magnitude)."""
    r = ranking.sort_values("prob_alerta")
    fig = go.Figure(go.Bar(
        x=r["prob_alerta"], y=r["nome"], orientation="h", marker=dict(color=AZUL),
        text=[f"{p:.0%}" for p in r["prob_alerta"]], textposition="outside",
        customdata=r[["mediana", "li_90", "ls_90", "limiar_casos"]].to_numpy(),
        hovertemplate=("%{y}<br>Probabilidade de alerta: %{x:.0%}<br>Mediana: %{customdata[0]:.0f} casos"
                       "<br>IC 90%: %{customdata[1]:.0f}–%{customdata[2]:.0f}"
                       "<br>Limiar: %{customdata[3]:.0f} casos<extra></extra>"),
    ))
    fig.update_layout(height=max(320, 28 * len(r) + 80), margin=dict(l=10, r=40, t=10, b=10),
                      xaxis=dict(range=[0, 1.1], tickformat=".0%", title="Probabilidade de ultrapassar o limiar",
                                 gridcolor="rgba(128,128,128,0.18)"),
                      yaxis=dict(title=None), hovermode="closest")
    return fig


def cobertura(tab: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=[0.4, 1], y=[0.4, 1], mode="lines", name="Calibração perfeita",
                             line=dict(color=TINTA, dash="dash", width=1), hoverinfo="skip"))
    for cor, (modelo, d) in zip(SERIES, tab.groupby("modelo", sort=True)):
        fig.add_trace(go.Scatter(x=d["cobertura_nominal"], y=d["cobertura_empirica"], mode="lines+markers",
                                 line=dict(color=cor, width=2), marker=dict(size=9), name=modelo,
                                 hovertemplate=f"{modelo}<br>Nominal: %{{x:.0%}}<br>Observada: %{{y:.0%}}<extra></extra>"))
    fig.update_layout(height=380, margin=dict(l=10, r=10, t=10, b=10), hovermode="closest",
                      xaxis=dict(title="Cobertura nominal", tickformat=".0%", range=[0.4, 1]),
                      yaxis=dict(title="Cobertura observada", tickformat=".0%", range=[0.4, 1],
                                 gridcolor="rgba(128,128,128,0.18)"),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0))
    return fig


def confiabilidade(tab: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=[0, 1], y=[0, 1], mode="lines", name="Calibração perfeita",
                             line=dict(color=TINTA, dash="dash", width=1), hoverinfo="skip"))
    for cor, (modelo, d) in zip(SERIES, tab.groupby("modelo", sort=True)):
        fig.add_trace(go.Scatter(x=d["prob_media"], y=d["freq_observada"], mode="lines+markers",
                                 line=dict(color=cor, width=2), marker=dict(size=9), name=modelo,
                                 customdata=d["n"],
                                 hovertemplate=f"{modelo}<br>Prevista: %{{x:.0%}}<br>Observada: %{{y:.0%}}"
                                               "<br>N: %{customdata}<extra></extra>"))
    fig.update_layout(height=380, margin=dict(l=10, r=10, t=10, b=10), hovermode="closest",
                      xaxis=dict(title="Probabilidade de alerta prevista", tickformat=".0%", range=[0, 1]),
                      yaxis=dict(title="Frequência observada de alerta", tickformat=".0%", range=[0, 1],
                                 gridcolor="rgba(128,128,128,0.18)"),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0))
    return fig
