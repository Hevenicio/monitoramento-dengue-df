"""Weighted Interval Score (WIS) e cobertura de intervalos de predição.

WIS segue Bracher et al. (2021), "Evaluating epidemic forecasts in an interval format":
WIS = (0.5*|y - mediana| + soma_k (alpha_k/2) * IS_alpha_k) / (K + 0.5),
IS_alpha = (u - l) + (2/alpha)(l - y)[y < l] + (2/alpha)(y - u)[y > u].
Calculamos na escala de casos e em log1p (comparável entre municípios de tamanhos diferentes).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

CHAVES = ["modelo", "geocode", "origem", "horizonte", "semana_alvo"]


def pares_intervalo(quantis: list[float]) -> list[tuple[float, float, float]]:
    """(alpha, quantil inferior, quantil superior) para cada intervalo central."""
    qs = sorted(quantis)
    pares = []
    for q in qs:
        if q < 0.5:
            sup = round(1 - q, 6)
            if any(abs(sup - x) < 1e-9 for x in qs):
                pares.append((round(2 * q, 6), q, sup))
    return pares


def wis(y: np.ndarray, matriz_q: np.ndarray, quantis: list[float]) -> np.ndarray:
    """WIS por linha. `matriz_q` tem uma coluna por quantil, na ordem de `quantis`."""
    y = np.asarray(y, dtype=float)
    idx = {round(q, 6): i for i, q in enumerate(quantis)}
    mediana = matriz_q[:, idx[0.5]]
    total = 0.5 * np.abs(y - mediana)
    pares = pares_intervalo(quantis)
    for alpha, ql, qu in pares:
        l, u = matriz_q[:, idx[round(ql, 6)]], matriz_q[:, idx[round(qu, 6)]]
        is_ = (u - l) + (2 / alpha) * np.clip(l - y, 0, None) + (2 / alpha) * np.clip(y - u, 0, None)
        total = total + (alpha / 2) * is_
    return total / (len(pares) + 0.5)


def para_largo(previsoes: pd.DataFrame) -> tuple[pd.DataFrame, list[float]]:
    """Formato longo (uma linha por quantil) -> largo (uma coluna por quantil)."""
    largo = previsoes.pivot_table(index=CHAVES, columns="quantil", values="valor").reset_index()
    quantis = sorted(c for c in largo.columns if isinstance(c, float))
    return largo, quantis


def avaliar(previsoes: pd.DataFrame, observados: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por previsão com WIS (casos e log), erro da mediana e indicadores de cobertura.

    `observados` precisa de geocode, inicio_semana e y.
    """
    largo, quantis = para_largo(previsoes)
    obs = observados[["geocode", "inicio_semana", "y"]].rename(
        columns={"inicio_semana": "semana_alvo", "y": "observado"}
    )
    largo = largo.merge(obs, on=["geocode", "semana_alvo"], how="inner").dropna(subset=["observado"])
    Q = largo[quantis].to_numpy()
    y = largo["observado"].to_numpy()
    out = largo[CHAVES + ["observado"]].copy()
    out["mediana"] = largo[0.5].to_numpy()
    out["wis"] = wis(y, Q, quantis)
    out["wis_log"] = wis(np.log1p(y), np.log1p(Q), quantis)
    out["erro_abs_mediana"] = np.abs(y - out["mediana"])
    for alpha, ql, qu in pares_intervalo(quantis):
        nivel = int(round((1 - alpha) * 100))
        out[f"cobre_{nivel}"] = (y >= largo[ql].to_numpy()) & (y <= largo[qu].to_numpy())
    return out


def resumo(avaliacao: pd.DataFrame) -> pd.DataFrame:
    """Médias por modelo e horizonte, com WIS relativo ao baseline climatológico."""
    cob = [c for c in avaliacao.columns if c.startswith("cobre_")]
    r = (
        avaliacao.groupby(["modelo", "horizonte"])[["wis", "wis_log", "erro_abs_mediana"] + cob]
        .mean()
        .reset_index()
    )
    r["n"] = avaliacao.groupby(["modelo", "horizonte"]).size().to_numpy()
    if "climatologia" in set(r["modelo"]):
        base = r[r["modelo"] == "climatologia"].set_index("horizonte")["wis_log"]
        r["wis_log_relativo"] = r["wis_log"] / r["horizonte"].map(base)
    return r


def tabela_cobertura(avaliacao: pd.DataFrame) -> pd.DataFrame:
    """Cobertura nominal x empírica por modelo (todos os horizontes juntos)."""
    cob = [c for c in avaliacao.columns if c.startswith("cobre_")]
    t = avaliacao.groupby("modelo")[cob].mean().reset_index().melt(
        id_vars="modelo", var_name="nivel", value_name="cobertura_empirica"
    )
    t["cobertura_nominal"] = t["nivel"].str.replace("cobre_", "").astype(int) / 100
    return t.sort_values(["modelo", "cobertura_nominal"]).reset_index(drop=True)
