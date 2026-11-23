import pandas as pd
import pytest

from dengue_df.features import montar_painel, montar_tabela
from dengue_df.ingest import sintetico

MUNICIPIOS = [
    {"nome": "Brasília", "uf": "DF", "geocode": 5300108},
    {"nome": "Município A", "uf": "GO"},
    {"nome": "Município B", "uf": "GO"},
]
HORIZONTES = [1, 2]
QUANTIS = [0.025, 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.975]


@pytest.fixture(scope="session")
def dados_sinteticos():
    return sintetico.gerar(MUNICIPIOS, inicio="2016-01-01", fim="2025-10-31", semanas_nowcast=3)


@pytest.fixture(scope="session")
def painel(dados_sinteticos):
    mun, info, clima = dados_sinteticos
    return montar_painel(info, clima, mun, "casos", 3, 41)


@pytest.fixture(scope="session")
def tabela(painel):
    return montar_tabela(painel, lags=8, horizontes=HORIZONTES)


@pytest.fixture(scope="session")
def corte(tabela):
    return tabela.loc[tabela["temporada"] == 2023, "inicio_semana"].min()


@pytest.fixture
def origens(tabela):
    return tabela[(tabela["temporada"] == 2023) & tabela["ly"].notna()].copy()


def as_ts(s):
    return pd.Timestamp(s)
