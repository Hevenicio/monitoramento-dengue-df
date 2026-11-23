"""Baseline de crescimento sazonal: nível atual x taxa de crescimento típica da época do ano.

Para cada horizonte h, usa a distribuição empírica de log1p(y[t+h]) - log1p(y[t]) observada
em semanas próximas da mesma SE nas temporadas de treino (todos os municípios juntos).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from dengue_df.models.base import ModeloQuantilico, distancia_circular_se, para_longo


class CrescimentoSazonal(ModeloQuantilico):
    nome = "crescimento"

    def __init__(self, horizontes, quantis, janela_sazonal: int = 3, **kwargs):
        super().__init__(horizontes, quantis)
        self.janela = janela_sazonal

    def ajustar(self, tabela: pd.DataFrame, corte: pd.Timestamp) -> "CrescimentoSazonal":
        self._amostras = {}
        for h in self.horizontes:
            tr = self.treino_para_h(tabela, h, corte)
            self._amostras[h] = (tr["se"].to_numpy(), (tr[f"alvo_h{h}"] - tr["ly"]).to_numpy())
        return self

    def prever(self, origens: pd.DataFrame) -> pd.DataFrame:
        origens = origens[origens["ly"].notna()]
        saidas = []
        for h in self.horizontes:
            se_tr, r = self._amostras[h]
            q_por_se = {}
            for s in np.unique(origens["se"]):
                amostra = r[distancia_circular_se(se_tr, s) <= self.janela]
                q_por_se[s] = np.quantile(amostra, self.quantis) if len(amostra) >= 10 else None
            linhas, ok = [], []
            for s, ly in zip(origens["se"].to_numpy(), origens["ly"].to_numpy()):
                q = q_por_se[s]
                ok.append(q is not None)
                if q is not None:
                    linhas.append(ly + q)
            ok = np.array(ok, dtype=bool)
            valores = np.vstack(linhas) if linhas else np.empty((0, len(self.quantis)))
            saidas.append(para_longo(origens[ok], h, self.quantis, valores))
        return pd.concat(saidas, ignore_index=True)
