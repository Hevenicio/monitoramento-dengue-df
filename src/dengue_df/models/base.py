"""Contrato comum dos modelos e utilidades de quantis."""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np
import pandas as pd

COLUNAS_SAIDA = ["geocode", "origem", "horizonte", "semana_alvo", "quantil", "valor"]


def distancia_circular_se(a, b, periodo: int = 52) -> np.ndarray:
    d = np.abs(np.asarray(a) - np.asarray(b)) % periodo
    return np.minimum(d, periodo - d)


def ordenar_quantis(matriz: np.ndarray) -> np.ndarray:
    """Rearranjo monotônico: garante q(0.025) <= ... <= q(0.975) em cada linha."""
    return np.sort(matriz, axis=1)


def para_longo(
    origens: pd.DataFrame, horizonte: int, quantis: list[float], valores_log: np.ndarray
) -> pd.DataFrame:
    """Converte matriz (n_origens x n_quantis) em log1p para o formato longo, na escala de casos."""
    valores = np.clip(np.expm1(ordenar_quantis(valores_log)), 0, None)
    n = len(origens)
    return pd.DataFrame(
        {
            "geocode": np.repeat(origens["geocode"].to_numpy(), len(quantis)),
            "origem": np.repeat(origens["inicio_semana"].to_numpy(), len(quantis)),
            "horizonte": horizonte,
            "semana_alvo": np.repeat(
                (origens["inicio_semana"] + pd.Timedelta(weeks=horizonte)).to_numpy(), len(quantis)
            ),
            "quantil": np.tile(quantis, n),
            "valor": valores.reshape(-1),
        }
    )


class ModeloQuantilico(ABC):
    nome: str = "base"

    def __init__(self, horizontes: list[int], quantis: list[float], **kwargs):
        self.horizontes = list(horizontes)
        self.quantis = list(quantis)

    @staticmethod
    def treino_para_h(tabela: pd.DataFrame, h: int, corte: pd.Timestamp) -> pd.DataFrame:
        """Linhas cujo alvo t+h é anterior ao corte (sem olhar o futuro do período de teste)."""
        m = (tabela[f"semana_alvo_h{h}"] < corte) & tabela[f"alvo_h{h}"].notna() & tabela["ly"].notna()
        return tabela[m]

    @abstractmethod
    def ajustar(self, tabela: pd.DataFrame, corte: pd.Timestamp) -> "ModeloQuantilico": ...

    @abstractmethod
    def prever(self, origens: pd.DataFrame) -> pd.DataFrame: ...
