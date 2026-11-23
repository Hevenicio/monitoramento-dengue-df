"""Download dos dados climáticos diários do Mosqlimate e agregação por semana epidemiológica."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from dengue_df.epiweek import inicio_semana
from dengue_df.ingest.api import coletar, para_data

log = logging.getLogger(__name__)

# Colunas como retornadas por mosqlient.get_climate.
OBRIGATORIAS = ["date", "geocodigo"]
AGREGACAO = {
    "temp_med": "mean",
    "temp_min": "mean",
    "temp_max": "mean",
    "precip_tot": "sum",
    "umid_med": "mean",
    "umid_min": "mean",
}


def baixar_clima(
    geocodes: Iterable[int],
    inicio: str,
    fim: str,
    api_key: str,
    cliente: Any = None,
    pasta_cache: Path | None = None,
    falhas: list | None = None,
    **opcoes_api,
) -> pd.DataFrame:
    """Baixa o clima diário ano a ano (com cache e novas tentativas) e agrega por semana.

    Se `falhas` for uma lista, pedaços que falharam são registrados nela e o resto segue
    (o clima é opcional para os modelos); se for None, qualquer falha levanta RuntimeError.
    """
    if cliente is None:
        import mosqlient as cliente

    def buscar(g: int, a: str, b: str):
        return cliente.get_climate(api_key=api_key, start_date=a, end_date=b, geocode=g)

    partes, f = coletar(geocodes, inicio, fim, buscar, rotulo="Clima", pasta_cache=pasta_cache, **opcoes_api)
    if f and falhas is None:
        raise RuntimeError(f"{len(f)} pedaço(s) de clima falharam: {f[:3]}")
    if falhas is not None:
        falhas.extend(f)
    if not partes:
        raise RuntimeError("A API de clima não retornou dados.")
    return agregar_semanal(pd.concat(partes, ignore_index=True))


def agregar_semanal(diario: pd.DataFrame) -> pd.DataFrame:
    faltando = [c for c in OBRIGATORIAS if c not in diario.columns]
    if faltando:
        raise ValueError(
            f"Colunas obrigatórias ausentes no clima: {faltando}. Recebidas: {sorted(diario.columns)}"
        )
    agg = {c: f for c, f in AGREGACAO.items() if c in diario.columns}
    if not agg:
        raise ValueError(f"Nenhuma variável climática conhecida em {sorted(diario.columns)}")
    df = diario.copy()
    for c in agg:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["geocode"] = pd.to_numeric(df["geocodigo"]).astype(int)
    df["dia"] = para_data(df["date"])
    df = df.drop_duplicates(["geocode", "dia"], keep="last")
    df["inicio_semana"] = inicio_semana(df["dia"]).values
    semanal = df.groupby(["geocode", "inicio_semana"], as_index=False).agg(agg)
    # Semanas com menos de 7 dias (bordas do período, pedaços que falharam) somariam chuva
    # parcial: ficam de fora.
    n = df.groupby(["geocode", "inicio_semana"]).size().rename("dias").reset_index()
    semanal = semanal.merge(n, on=["geocode", "inicio_semana"])
    return semanal[semanal["dias"] >= 7].drop(columns="dias").reset_index(drop=True)
