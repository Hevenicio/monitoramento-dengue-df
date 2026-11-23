"""Gradient boosting quantílico (scikit-learn), modelo global para todos os municípios.

Um modelo por horizonte e por quantil. O alvo é o crescimento em log
(log1p(y[t+h]) - log1p(y[t])), mais estável entre municípios de tamanhos diferentes.
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from dengue_df.features import colunas_preditoras
from dengue_df.models.base import ModeloQuantilico, para_longo


class GBMQuantilico(ModeloQuantilico):
    nome = "gbm_quantilico"

    def __init__(self, horizontes, quantis, lags: int = 8, com_clima: bool = True,
                 max_iter: int = 300, learning_rate: float = 0.05, semente: int = 0, **kwargs):
        super().__init__(horizontes, quantis)
        self.lags = lags
        self.com_clima = com_clima
        self.params = dict(max_iter=max_iter, learning_rate=learning_rate, max_leaf_nodes=15,
                           min_samples_leaf=30, l2_regularization=1.0, random_state=semente)

    def _colunas(self, tabela: pd.DataFrame, corte: pd.Timestamp) -> list[str]:
        cols = [c for c in colunas_preditoras(self.lags, self.com_clima) if c in tabela.columns]
        # Colunas inteiramente vazias no treino (ex.: incidência quando a API não traz população)
        # quebram o HistGradientBoosting e não carregam informação: ficam de fora.
        passado = tabela[tabela["inicio_semana"] < corte]
        return [c for c in cols if c == "municipio" or passado[c].notna().any()]

    def ajustar(self, tabela: pd.DataFrame, corte: pd.Timestamp) -> "GBMQuantilico":
        self.colunas_ = self._colunas(tabela, corte)
        self.categorias_ = tabela["municipio"].cat.categories
        self.modelos_ = {}
        for h in self.horizontes:
            tr = self.treino_para_h(tabela, h, corte)
            X, y = self._X(tr), (tr[f"alvo_h{h}"] - tr["ly"]).to_numpy()
            for q in self.quantis:
                m = HistGradientBoostingRegressor(
                    loss="quantile", quantile=q, categorical_features=["municipio"], **self.params
                )
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    m.fit(X, y)
                self.modelos_[(h, q)] = m
        return self

    def _X(self, df: pd.DataFrame) -> pd.DataFrame:
        X = df[self.colunas_].copy()
        X["municipio"] = pd.Categorical(df["geocode"], categories=self.categorias_)
        return X

    def prever(self, origens: pd.DataFrame) -> pd.DataFrame:
        origens = origens[origens["ly"].notna()]
        if origens.empty:
            return pd.DataFrame(columns=["geocode", "origem", "horizonte", "semana_alvo", "quantil", "valor"])
        X = self._X(origens)
        saidas = []
        for h in self.horizontes:
            r = np.column_stack([self.modelos_[(h, q)].predict(X) for q in self.quantis])
            saidas.append(para_longo(origens, h, self.quantis, origens["ly"].to_numpy()[:, None] + r))
        return pd.concat(saidas, ignore_index=True)
