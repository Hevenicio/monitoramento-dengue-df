"""Limiar de alerta por município e probabilidade de ultrapassá-lo.

O limiar é um percentil (padrão 90%) da incidência semanal histórica de cada município,
na linha do critério de incidência alta do InfoDengue. A probabilidade vem da distribuição
preditiva em quantis, interpolada linearmente (aproximação: abaixo do menor quantil a
probabilidade acumulada cai linearmente até 0 em zero casos; acima do maior quantil, a
probabilidade de ultrapassar é tratada como menor que 1 - quantil máximo).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def limiares(painel: pd.DataFrame, percentil: float = 0.9, corte: pd.Timestamp | None = None) -> pd.DataFrame:
    """Limiar por município. Com população: percentil da incidência × população mais recente.
    Sem população (coluna ausente ou vazia para o município): percentil dos próprios casos.
    A coluna `base_limiar` diz qual critério foi usado."""
    hist = painel if corte is None else painel[painel["inicio_semana"] < corte]
    hist = hist.dropna(subset=["y"])
    lim = hist.groupby("geocode")["y"].quantile(percentil).rename("limiar_por_casos").reset_index()

    if "pop" in painel.columns:
        pop = painel.sort_values("inicio_semana").groupby("geocode")["pop"].last()
        lim["pop"] = lim["geocode"].map(pop)
    else:
        lim["pop"] = np.nan
    if "incidencia" in hist.columns:
        inc = hist.dropna(subset=["incidencia"]).groupby("geocode")["incidencia"].quantile(percentil)
        lim["limiar_incidencia"] = lim["geocode"].map(inc)
    else:
        lim["limiar_incidencia"] = np.nan

    lim["limiar_casos"] = lim["limiar_incidencia"] * lim["pop"] / 1e5
    sem_pop = lim["limiar_casos"].isna()
    lim.loc[sem_pop, "limiar_casos"] = lim.loc[sem_pop, "limiar_por_casos"]
    lim["base_limiar"] = np.where(sem_pop, "casos", "incidencia")
    return lim.drop(columns="limiar_por_casos")[
        ["geocode", "limiar_incidencia", "pop", "limiar_casos", "base_limiar"]
    ]


def prob_exceder(valores: np.ndarray, quantis: np.ndarray, limiar: float) -> float:
    """P(Y > limiar) a partir de um conjunto de quantis (valores crescentes)."""
    v = np.maximum.accumulate(np.asarray(valores, dtype=float))
    q = np.asarray(quantis, dtype=float)
    if v[0] > 0:
        v, q = np.r_[0.0, v], np.r_[0.0, q]
    cdf = np.interp(limiar, v, q, left=0.0, right=q[-1])
    if limiar >= v[-1]:
        cdf = max(q[-1], 1.0 - (1.0 - q[-1]) * (v[-1] / limiar if limiar > 0 else 1.0))
    return float(np.clip(1.0 - cdf, 0.0, 1.0))


def tabela_risco(previsoes: pd.DataFrame, lim: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por modelo, município e horizonte com mediana, IC 90% e probabilidade de alerta."""
    linhas = []
    chaves = ["modelo", "geocode", "origem", "horizonte", "semana_alvo"]
    lim_idx = lim.set_index("geocode")
    for chave, d in previsoes.sort_values("quantil").groupby(chaves):
        geocode = chave[1]
        if geocode not in lim_idx.index:
            continue
        limiar = float(lim_idx.loc[geocode, "limiar_casos"])
        q, v = d["quantil"].to_numpy(), d["valor"].to_numpy()
        linhas.append(
            dict(zip(chaves, chave))
            | {
                "mediana": float(np.interp(0.5, q, v)),
                "li_90": float(np.interp(0.05, q, v)),
                "ls_90": float(np.interp(0.95, q, v)),
                "limiar_casos": limiar,
                "prob_alerta": prob_exceder(v, q, limiar),
            }
        )
    return pd.DataFrame(linhas)
