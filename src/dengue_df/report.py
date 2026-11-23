"""Prévia estática em PNG (matplotlib): previsão de um município e cobertura dos intervalos.

Útil para conferir resultados sem abrir o painel interativo.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from dengue_df.painel_dados import faixas, serie_observada  # noqa: E402

AZUL, AZUL_CLARO, AZUL_MEDIO = "#2a78d6", "#b7d3f6", "#86b6ef"
LARANJA = "#eb6834"
TINTA, TINTA_2, GRADE = "#0b0b0b", "#52514e", "#e4e3df"


def _estilo(ax):
    for lado in ("top", "right"):
        ax.spines[lado].set_visible(False)
    for lado in ("left", "bottom"):
        ax.spines[lado].set_color(GRADE)
    ax.tick_params(colors=TINTA_2, labelsize=9)
    ax.grid(axis="y", color=GRADE, linewidth=0.8)
    ax.set_axisbelow(True)


def figura_previsao(saidas: dict[str, pd.DataFrame], geocode: int, modelo: str, destino: Path,
                    aviso: str | None = None) -> Path:
    painel, prev, lim = saidas["painel"], saidas["previsao"], saidas["limiares"]
    nome = painel.loc[painel["geocode"] == geocode, "nome"].iloc[0] if "nome" in painel else str(geocode)
    obs = serie_observada(painel, geocode, 52)
    f = faixas(prev, geocode, modelo)
    limiar = lim.loc[lim["geocode"] == geocode, "limiar_casos"].iloc[0]

    fig, ax = plt.subplots(figsize=(11.5, 4.6), dpi=130)
    _estilo(ax)
    ax.plot(obs["inicio_semana"], obs["y"], color=TINTA, linewidth=2, label="Observado")
    nc = obs[obs["nowcast"]]
    if len(nc):
        ax.plot(nc["inicio_semana"], nc["y"], "o", color=TINTA, markersize=4, markerfacecolor="white",
                label="Estimativa de nowcasting")
    if not f.empty:
        ancora = obs.iloc[[-1]].rename(columns={"inicio_semana": "semana_alvo", "y": "q0.5"})
        x = pd.concat([ancora["semana_alvo"], f["semana_alvo"]])
        def faixa(col):
            return pd.concat([ancora["q0.5"], f[col]])
        ax.fill_between(x, faixa("q0.05"), faixa("q0.95"), color=AZUL_CLARO, linewidth=0, label="Intervalo de 90%")
        ax.fill_between(x, faixa("q0.25"), faixa("q0.75"), color=AZUL_MEDIO, linewidth=0, label="Intervalo de 50%")
        ax.plot(x, faixa("q0.5"), color=AZUL, linewidth=2, label="Mediana prevista")
    ax.axhline(limiar, color=TINTA_2, linestyle="--", linewidth=1)
    ax.annotate("limiar de alerta", (1.0, limiar), xycoords=("axes fraction", "data"), xytext=(0, 4),
                textcoords="offset points", fontsize=8, color=TINTA_2, ha="right")
    ax.set_title(f"{nome}: casos semanais e previsão ({modelo})", loc="left", fontsize=12, color=TINTA)
    ax.set_ylabel("Casos por semana", color=TINTA_2, fontsize=9)
    ax.set_ylim(top=max(ax.get_ylim()[1], limiar * 1.15))
    ax.legend(frameon=False, fontsize=8, loc="upper left", bbox_to_anchor=(1.01, 1.0))
    if aviso:
        fig.text(0.01, 0.01, aviso, fontsize=8, color=LARANJA)
    fig.tight_layout()
    destino.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(destino)
    plt.close(fig)
    return destino


def figura_cobertura(cobertura: pd.DataFrame, destino: Path) -> Path:
    cores = [AZUL, LARANJA, "#1baf7a"]
    fig, ax = plt.subplots(figsize=(5.2, 4.6), dpi=130)
    _estilo(ax)
    ax.plot([0, 1], [0, 1], color=TINTA_2, linestyle="--", linewidth=1, label="calibração perfeita")
    for cor, (modelo, d) in zip(cores, cobertura.groupby("modelo", sort=True)):
        ax.plot(d["cobertura_nominal"], d["cobertura_empirica"], "-o", color=cor, linewidth=2,
                markersize=6, label=modelo)
    ax.set_xlim(0.4, 1)
    ax.set_ylim(0.4, 1)
    ax.set_xlabel("Cobertura nominal do intervalo", color=TINTA_2, fontsize=9)
    ax.set_ylabel("Cobertura observada no backtest", color=TINTA_2, fontsize=9)
    ax.set_title("Os intervalos cobrem o que prometem?", loc="left", fontsize=12, color=TINTA)
    ax.legend(frameon=False, fontsize=8, loc="lower right")
    fig.tight_layout()
    fig.savefig(destino)
    plt.close(fig)
    return destino
