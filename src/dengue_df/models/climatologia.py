"""Baseline climatológico: distribuição histórica dos casos na mesma época do ano.

Ignora o nível atual da epidemia. Serve como piso: um modelo útil precisa superá-lo.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from dengue_df.epiweek import semana_epidemiologica
from dengue_df.models.base import ModeloQuantilico, distancia_circular_se, para_longo


class Climatologia(ModeloQuantilico):
    nome = "climatologia"

    def __init__(self, horizontes, quantis, janela_sazonal: int = 3, **kwargs):
        super().__init__(horizontes, quantis)
        self.janela = janela_sazonal

    def ajustar(self, tabela: pd.DataFrame, corte: pd.Timestamp) -> "Climatologia":
        hist = tabela[(tabela["inicio_semana"] < corte) & tabela["ly"].notna()]
        self._hist = {g: (d["se"].to_numpy(), d["ly"].to_numpy()) for g, d in hist.groupby("geocode")}
        return self

    def _quantis_para(self, geocode: int, se_alvo: int) -> np.ndarray:
        se, ly = self._hist.get(geocode, (np.array([]), np.array([])))
        amostra = ly[distancia_circular_se(se, se_alvo) <= self.janela]
        if len(amostra) < 5:
            return np.full(len(self.quantis), np.nan)
        return np.quantile(amostra, self.quantis)

    def prever(self, origens: pd.DataFrame) -> pd.DataFrame:
        saidas = []
        for h in self.horizontes:
            se_alvo = semana_epidemiologica(origens["inicio_semana"] + pd.Timedelta(weeks=h))["se"].to_numpy()
            cache: dict[tuple[int, int], np.ndarray] = {}
            linhas = []
            for g, s in zip(origens["geocode"].to_numpy(), se_alvo):
                chave = (int(g), int(s))
                if chave not in cache:
                    cache[chave] = self._quantis_para(*chave)
                linhas.append(cache[chave])
            valores = np.vstack(linhas) if linhas else np.empty((0, len(self.quantis)))
            ok = ~np.isnan(valores).any(axis=1)
            saidas.append(para_longo(origens[ok], h, self.quantis, valores[ok]))
        return pd.concat(saidas, ignore_index=True)
