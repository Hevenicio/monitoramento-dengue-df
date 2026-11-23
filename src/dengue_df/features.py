"""Montagem do painel semanal e das variáveis preditoras.

Regra de ouro contra vazamento: a linha de origem t só usa informação de semanas <= t.
Os alvos (alvo_h{h}) são o log1p dos casos na semana t + h.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from dengue_df.epiweek import semana_epidemiologica, temporada

CLIMA_VARS = ["temp_med", "precip_tot", "umid_med"]


def montar_painel(
    infodengue: pd.DataFrame,
    clima: pd.DataFrame | None = None,
    municipios: pd.DataFrame | None = None,
    alvo: str = "casos",
    semanas_nowcast: int = 3,
    inicio_temporada_se: int = 41,
) -> pd.DataFrame:
    """Uma linha por município e semana, com grade semanal completa e alvo `y`."""
    if alvo not in infodengue.columns:
        raise ValueError(f"Coluna alvo '{alvo}' não existe no InfoDengue.")
    partes = []
    for g, d in infodengue.groupby("geocode"):
        grade = pd.date_range(d["inicio_semana"].min(), d["inicio_semana"].max(), freq="7D")
        d = d.set_index("inicio_semana").reindex(grade).rename_axis("inicio_semana").reset_index()
        d["geocode"] = g
        partes.append(d)
    p = pd.concat(partes, ignore_index=True)

    p["y"] = p[alvo].astype(float)
    p["nowcast"] = False
    if semanas_nowcast > 0 and "casos_est" in p.columns:
        ultimas = p.groupby("geocode")["inicio_semana"].transform(
            lambda s: s >= s.max() - pd.Timedelta(weeks=semanas_nowcast - 1)
        )
        usar = ultimas & p["casos_est"].notna()
        p.loc[usar, "y"] = p.loc[usar, "casos_est"].astype(float)
        p.loc[usar, "nowcast"] = True

    if "pop" in p.columns:
        p["pop"] = p.groupby("geocode")["pop"].transform(lambda s: s.ffill().bfill())
        p["incidencia"] = p["y"] / p["pop"] * 1e5

    se = semana_epidemiologica(p["inicio_semana"])
    p["ano_se"], p["se"] = se["ano_se"].values, se["se"].values
    p["temporada"] = temporada(p["ano_se"], p["se"], inicio_temporada_se).values

    if clima is not None and len(clima):
        cols = ["geocode", "inicio_semana"] + [c for c in CLIMA_VARS if c in clima.columns]
        p = p.merge(clima[cols], on=["geocode", "inicio_semana"], how="left")
    if municipios is not None:
        p = p.merge(municipios[["geocode", "nome"]], on="geocode", how="left")
    return p.sort_values(["geocode", "inicio_semana"]).reset_index(drop=True)


def colunas_preditoras(lags: int, com_clima: bool) -> list[str]:
    cols = [f"ly_lag{k}" for k in range(lags)]
    cols += ["ly_media4", "ly_media8", "ly_tendencia4", "inc_log", "se_sin", "se_cos", "municipio"]
    if com_clima:
        for v in CLIMA_VARS:
            cols += [f"{v}_j0_3", f"{v}_j4_7", f"{v}_j8_11"]
    return cols


def montar_tabela(painel: pd.DataFrame, lags: int, horizontes: list[int]) -> pd.DataFrame:
    """Acrescenta preditoras (passado) e alvos (futuro) a cada linha de origem."""
    t = painel.copy()
    g = t.groupby("geocode", sort=False)
    t["ly"] = np.log1p(t["y"])
    ly = g["ly"]
    for k in range(lags):
        t[f"ly_lag{k}"] = ly.shift(k)
    t["ly_media4"] = ly.transform(lambda s: s.rolling(4, min_periods=4).mean())
    t["ly_media8"] = ly.transform(lambda s: s.rolling(8, min_periods=8).mean())
    t["ly_tendencia4"] = t["ly"] - ly.shift(4)
    if "incidencia" in t.columns:
        t["inc_log"] = np.log1p(t["incidencia"])
    else:
        t["inc_log"] = np.nan
    ang = 2 * np.pi * t["se"] / 52.18
    t["se_sin"], t["se_cos"] = np.sin(ang), np.cos(ang)
    t["municipio"] = t["geocode"].astype("category")

    for v in CLIMA_VARS:
        if v not in t.columns:
            continue
        agg = "sum" if v == "precip_tot" else "mean"
        janela = g[v].transform(lambda s, a=agg: s.rolling(4, min_periods=3).agg(a))
        t[f"{v}_j0_3"] = janela
        t[f"{v}_j4_7"] = janela.groupby(t["geocode"]).shift(4)
        t[f"{v}_j8_11"] = janela.groupby(t["geocode"]).shift(8)

    for h in horizontes:
        t[f"alvo_h{h}"] = ly.shift(-h)
        t[f"semana_alvo_h{h}"] = t["inicio_semana"] + pd.Timedelta(weeks=h)
    return t
