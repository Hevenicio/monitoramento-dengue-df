import pandas as pd

from dengue_df.epiweek import inicio_semana, rotulo_temporada, semana_epidemiologica, temporada


def test_semanas_conhecidas():
    casos = {
        "2024-01-01": (2024, 1),   # SE 1/2024 começa no domingo 31/12/2023
        "2023-01-01": (2023, 1),
        "2022-01-01": (2021, 52),  # sábado ainda pertence à SE 52 de 2021
        "2021-01-03": (2021, 1),
        "2020-12-31": (2020, 53),  # 2020 teve 53 semanas epidemiológicas
    }
    r = semana_epidemiologica(list(casos))
    assert list(zip(r["ano_se"], r["se"])) == list(casos.values())


def test_inicio_semana_e_domingo():
    d = inicio_semana(pd.date_range("2025-01-01", periods=20, freq="D"))
    assert (d.dt.dayofweek == 6).all()


def test_temporada():
    assert list(temporada([2023, 2024, 2024], [41, 40, 41])) == [2023, 2023, 2024]
    assert rotulo_temporada(2023) == "2023/24"
