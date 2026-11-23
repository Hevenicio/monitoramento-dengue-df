"""Backtest por origem móvel, temporada a temporada.

Para cada temporada de teste S: os modelos são treinados só com alvos anteriores à SE 41 de S
e fazem previsões a partir de cada semana de S, usando apenas dados disponíveis até a origem.
"""

from __future__ import annotations

import logging
from typing import Callable

import pandas as pd

log = logging.getLogger(__name__)


def temporadas_completas(tabela: pd.DataFrame, minimo_semanas: int = 52) -> list[int]:
    contagem = tabela.drop_duplicates(["temporada", "inicio_semana"]).groupby("temporada").size()
    return sorted(int(t) for t, n in contagem.items() if n >= minimo_semanas)


def corte_da_temporada(tabela: pd.DataFrame, temporada: int) -> pd.Timestamp:
    return tabela.loc[tabela["temporada"] == temporada, "inicio_semana"].min()


def backtest(
    tabela: pd.DataFrame,
    fabricas: dict[str, Callable[[], object]],
    temporadas_teste: list[int],
) -> pd.DataFrame:
    """Retorna previsões em formato longo com a coluna `modelo` e a temporada de teste."""
    saidas = []
    for temp in temporadas_teste:
        corte = corte_da_temporada(tabela, temp)
        origens = tabela[(tabela["temporada"] == temp) & tabela["ly"].notna()]
        for nome, fabrica in fabricas.items():
            log.info("Backtest: temporada %s, modelo %s (corte %s)", temp, nome, corte.date())
            modelo = fabrica().ajustar(tabela, corte)
            prev = modelo.prever(origens)
            prev["modelo"] = nome
            prev["temporada_teste"] = temp
            saidas.append(prev)
    return pd.concat(saidas, ignore_index=True)
