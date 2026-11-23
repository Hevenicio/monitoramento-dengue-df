"""Modelos de previsão probabilística (saída em quantis)."""

from dengue_df.models.climatologia import Climatologia
from dengue_df.models.crescimento import CrescimentoSazonal
from dengue_df.models.gbm import GBMQuantilico

REGISTRO = {
    "climatologia": Climatologia,
    "crescimento": CrescimentoSazonal,
    "gbm_quantilico": GBMQuantilico,
}


def criar_modelo(nome: str, **kwargs):
    if nome not in REGISTRO:
        raise ValueError(f"Modelo desconhecido: {nome}. Disponíveis: {sorted(REGISTRO)}")
    return REGISTRO[nome](**kwargs)
