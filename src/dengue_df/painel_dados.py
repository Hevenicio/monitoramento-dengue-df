"""Funções puras que preparam os dados exibidos no painel (testáveis sem Streamlit)."""

from __future__ import annotations

import pandas as pd

from dengue_df.epiweek import rotulo_temporada


def serie_observada(painel: pd.DataFrame, geocode: int, semanas: int = 104) -> pd.DataFrame:
    d = painel[painel["geocode"] == geocode].sort_values("inicio_semana")
    return d.tail(semanas)[["inicio_semana", "y", "nowcast"]]


def faixas(previsoes: pd.DataFrame, geocode: int, modelo: str, **filtros) -> pd.DataFrame:
    """Previsões de um município e modelo em formato largo (uma coluna por quantil)."""
    d = previsoes[(previsoes["geocode"] == geocode) & (previsoes["modelo"] == modelo)]
    for col, val in filtros.items():
        d = d[d[col] == val]
    if d.empty:
        return pd.DataFrame()
    largo = d.pivot_table(index="semana_alvo", columns="quantil", values="valor").reset_index()
    largo.columns = ["semana_alvo"] + [f"q{c:g}" for c in largo.columns[1:]]
    return largo.sort_values("semana_alvo")


def ranking_risco(risco: pd.DataFrame, modelo: str, horizonte: int) -> pd.DataFrame:
    d = risco[(risco["modelo"] == modelo) & (risco["horizonte"] == horizonte)]
    cols = ["nome", "geocode", "semana_alvo", "mediana", "li_90", "ls_90", "limiar_casos", "prob_alerta"]
    return d[[c for c in cols if c in d.columns]].sort_values("prob_alerta", ascending=False).reset_index(drop=True)


def opcoes_temporada(backtest_prev: pd.DataFrame) -> dict[str, int]:
    return {rotulo_temporada(int(t)): int(t) for t in sorted(backtest_prev["temporada_teste"].unique())}


def resumo_legivel(resumo: pd.DataFrame) -> pd.DataFrame:
    cols = {
        "modelo": "Modelo",
        "horizonte": "Horizonte (sem.)",
        "wis_log": "WIS (log)",
        "wis_log_relativo": "WIS relativo à climatologia",
        "wis": "WIS (casos)",
        "erro_abs_mediana": "Erro abs. da mediana",
        "cobre_50": "Cobertura 50%",
        "cobre_90": "Cobertura 90%",
        "brier_alerta": "Brier do alerta",
        "n": "N previsões",
    }
    return resumo[[c for c in cols if c in resumo.columns]].rename(columns=cols)
