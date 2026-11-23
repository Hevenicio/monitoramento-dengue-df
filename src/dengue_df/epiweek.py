"""Semanas epidemiológicas (padrão do Ministério da Saúde / MMWR).

A semana vai de domingo a sábado. A SE 1 de um ano é a semana que contém o dia 4 de janeiro
(equivalente a ser a primeira semana com pelo menos 4 dias no ano). O ano epidemiológico de uma
semana é o ano da sua quarta-feira.
"""

from __future__ import annotations

import pandas as pd


def inicio_semana(datas) -> pd.Series:
    """Domingo que inicia a semana epidemiológica de cada data (mesmo critério de data_iniSE)."""
    d = pd.to_datetime(pd.Series(datas)).dt.normalize()
    return d - pd.to_timedelta((d.dt.dayofweek + 1) % 7, unit="D")


def semana_epidemiologica(datas) -> pd.DataFrame:
    """Retorna DataFrame com ano_se e se (número da semana) para cada data."""
    ini = inicio_semana(datas)
    ano = (ini + pd.Timedelta(days=3)).dt.year
    jan4 = pd.to_datetime(ano.astype(str) + "-01-04")
    ini_se1 = inicio_semana(jan4)
    se = ((ini.values - ini_se1.values) / pd.Timedelta(days=7)).astype(int) + 1
    return pd.DataFrame({"ano_se": ano.values, "se": se}, index=ini.index)


def temporada(ano_se, se, inicio_se: int = 41):
    """Ano de início da temporada (ex.: SE 41/2023 a SE 40/2024 → 2023)."""
    ano_se = pd.Series(ano_se)
    se = pd.Series(se)
    return ano_se.where(se >= inicio_se, ano_se - 1).astype(int)


def rotulo_temporada(ano_inicio: int) -> str:
    return f"{ano_inicio}/{str(ano_inicio + 1)[-2:]}"
