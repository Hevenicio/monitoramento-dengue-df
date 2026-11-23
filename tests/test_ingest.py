import pandas as pd
import pytest

from dengue_df.ingest.clima import agregar_semanal, baixar_clima
from dengue_df.ingest.infodengue import baixar_infodengue, padronizar_infodengue
from dengue_df.ingest.municipios import normalizar, resolver_municipios


class ClienteFalso:
    """Substitui o mosqlient: devolve colunas com os nomes reais da API."""

    def __init__(self):
        self.chamadas = []

    def get_infodengue(self, api_key, disease, start_date, end_date, geocode):
        self.chamadas.append(("info", geocode))
        semanas = pd.date_range("2024-01-07", periods=3, freq="7D")
        return pd.DataFrame({
            "data_iniSE": semanas.astype(str), "SE": [202402, 202403, 202404], "casos": [10, 12, 15],
            "casos_est": [10, 12, 18.5], "casos_est_min": [10, 12, 15], "casos_est_max": [10, 12, 25],
            "municipio_geocodigo": geocode, "pop": 1000, "Rt": [1.1, 1.2, 1.3], "nivel": [1, 2, 2],
        })

    def get_climate(self, api_key, start_date, end_date, geocode):
        self.chamadas.append(("clima", geocode, start_date, end_date))
        dias = pd.date_range("2024-01-07", "2024-01-20", freq="D")
        return pd.DataFrame({"date": dias.astype(str), "geocodigo": geocode, "epiweek": 0,
                             "temp_med": 25.0, "precip_tot": 2.0, "umid_med": 70.0})


def test_infodengue_padroniza_colunas():
    cli = ClienteFalso()
    df = baixar_infodengue([5300108, 5200258], "2024-01-01", "2024-02-01", "dengue", "x", cliente=cli)
    assert set(df["geocode"]) == {5300108, 5200258}
    assert {"inicio_semana", "casos", "casos_est", "pop"} <= set(df.columns)
    assert df["inicio_semana"].dt.dayofweek.eq(6).all()


def test_infodengue_erro_claro_sem_coluna():
    with pytest.raises(ValueError, match="municipio_geocodigo"):
        padronizar_infodengue(pd.DataFrame({"data_iniSE": ["2024-01-07"], "casos": [1]}))


def test_infodengue_remove_duplicatas():
    bruto = pd.DataFrame({"data_iniSE": ["2024-01-07", "2024-01-07"], "casos": [5, 7],
                          "municipio_geocodigo": [1, 1]})
    assert padronizar_infodengue(bruto)["casos"].tolist() == [7]


def test_clima_agrega_semanas_completas():
    cli = ClienteFalso()
    df = baixar_clima([5300108], "2024-01-01", "2024-01-31", "x", cliente=cli)
    assert len(df) == 2  # duas semanas de 7 dias
    assert df["precip_tot"].tolist() == [14.0, 14.0]  # chuva soma
    assert df["temp_med"].tolist() == [25.0, 25.0]    # temperatura é média


def test_clima_descarta_semana_parcial():
    dias = pd.date_range("2024-01-07", "2024-01-10", freq="D")
    df = agregar_semanal(pd.DataFrame({"date": dias, "geocodigo": 1, "precip_tot": 1.0}))
    assert df.empty


def test_resolver_municipios_usa_ibge_e_cache(tmp_path):
    respostas = {"GO": [{"id": 5200258, "nome": "Águas Lindas de Goiás"}, {"id": 5221858, "nome": "Valparaíso de Goiás"}]}
    chamadas = []

    def buscar(uf):
        chamadas.append(uf)
        return respostas[uf]

    cfg = [{"nome": "Brasília", "uf": "DF", "geocode": 5300108},
           {"nome": "aguas lindas de goias", "uf": "GO"}, {"nome": "Valparaíso de Goiás", "uf": "GO"}]
    r = resolver_municipios(cfg, tmp_path / "m.csv", buscar_uf=buscar)
    assert r["geocode"].tolist() == [5300108, 5200258, 5221858]
    resolver_municipios(cfg, tmp_path / "m.csv", buscar_uf=buscar)  # segunda vez usa o cache
    assert chamadas == ["GO"]


def test_resolver_municipios_sugere_nome(tmp_path):
    with pytest.raises(ValueError, match="Sugestões"):
        resolver_municipios([{"nome": "Valparaiso", "uf": "GO"}], tmp_path / "m.csv",
                            buscar_uf=lambda uf: [{"id": 1, "nome": "Valparaíso de Goiás"}])


def test_normalizar():
    assert normalizar("  Santo Antônio do-Descoberto ") == "santo antonio do descoberto"
