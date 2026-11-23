"""Download robusto: novas tentativas, cache por pedaço, retomada e conversão de datas."""

import pandas as pd
import pytest

from dengue_df.ingest.api import (
    ErroDefinitivo, coletar, com_tentativas, domingo_mais_proximo, para_data, pedacos_anuais,
)
from dengue_df.ingest.infodengue import lacunas, padronizar_infodengue
from dengue_df.risk import limiares


class Relogio:
    def __init__(self):
        self.esperas = []

    def __call__(self, t):
        self.esperas.append(t)


def test_tentativas_ate_dar_certo():
    r, n = Relogio(), {"i": 0}

    def fn():
        n["i"] += 1
        if n["i"] < 3:
            raise ConnectionError("timeout")
        return pd.DataFrame({"x": [1]})

    assert len(com_tentativas(fn, "t", tentativas=4, espera=2, dormir=r)) == 1
    assert r.esperas == [2, 4]


def test_tentativas_esgotadas():
    with pytest.raises(RuntimeError, match="3 tentativas"):
        com_tentativas(lambda: (_ for _ in ()).throw(ConnectionError("x")), "t",
                       tentativas=3, espera=0, dormir=Relogio())


@pytest.mark.parametrize("erro", [Exception("401 Unauthorized"), TypeError("unexpected keyword")])
def test_erro_definitivo_nao_repete(erro):
    r, n = Relogio(), {"i": 0}

    def fn():
        n["i"] += 1
        raise erro

    with pytest.raises(ErroDefinitivo):
        com_tentativas(fn, "t", tentativas=4, espera=1, dormir=r)
    assert n["i"] == 1 and r.esperas == []


def test_pedacos_anuais():
    assert pedacos_anuais("2022-03-05", "2024-02-10") == [
        ("2022-03-05", "2022-12-31"), ("2023-01-01", "2023-12-31"), ("2024-01-01", "2024-02-10")]


class Api:
    """buscar(geocode, a, b) que conta chamadas e pode falhar em pedaços escolhidos."""

    def __init__(self, falhar=(), vazio=()):
        self.chamadas, self.falhar, self.vazio = [], set(falhar), set(vazio)

    def __call__(self, g, a, b):
        self.chamadas.append((g, a[:4]))
        if (g, a[:4]) in self.falhar:
            raise ConnectionError("502 Bad Gateway")
        if (g, a[:4]) in self.vazio:
            return pd.DataFrame()
        return pd.DataFrame({"g": [g], "a": [a], "b": [b]})


def _coletar(api, pasta, fim="2022-06-30", **kw):
    return coletar([1, 2], "2020-01-01", fim, api, rotulo="t", pasta_cache=pasta,
                   semanas_revisao=12, tentativas=2, espera=0, dormir=Relogio(), **kw)


def test_cache_reaproveita_anos_fechados(tmp_path):
    api = Api()
    partes, falhas = _coletar(api, tmp_path)
    assert len(partes) == 6 and not falhas and len(api.chamadas) == 6
    api2 = Api()
    partes2, _ = _coletar(api2, tmp_path)
    assert len(partes2) == 6
    assert sorted(api2.chamadas) == [(1, "2022"), (2, "2022")]  # só o ano recente é revisto


def test_retoma_depois_de_falha(tmp_path):
    api = Api(falhar={(2, "2021")})
    _, falhas = _coletar(api, tmp_path)
    assert [(f["geocode"], f["inicio"]) for f in falhas] == [(2, "2021-01-01")]
    api2 = Api()
    _, falhas2 = _coletar(api2, tmp_path)
    assert not falhas2 and sorted(api2.chamadas) == [(1, "2022"), (2, "2021"), (2, "2022")]


def test_resposta_vazia_fica_em_cache(tmp_path):
    _coletar(Api(vazio={(1, "2020")}), tmp_path)
    api2 = Api()
    partes, _ = _coletar(api2, tmp_path)
    assert (1, "2020") not in api2.chamadas and len(partes) == 5


def test_refazer_ignora_cache_e_limpa_versoes_antigas(tmp_path):
    _coletar(Api(), tmp_path, fim="2022-06-30")
    _coletar(Api(), tmp_path, fim="2022-09-30")
    assert len(list(tmp_path.glob("1_2022-01-01_*"))) == 1
    api = Api()
    _coletar(api, tmp_path, fim="2022-09-30", refazer=True)
    assert len(api.chamadas) == 6


def test_erro_definitivo_interrompe_coleta(tmp_path):
    def buscar(g, a, b):
        raise Exception("HTTP 401: invalid api key")

    with pytest.raises(ErroDefinitivo):
        _coletar(buscar, tmp_path)


def test_para_data_formatos():
    ms = pd.Series([pd.Timestamp("2024-01-07").value // 10**6])
    assert para_data(ms).iloc[0] == pd.Timestamp("2024-01-07")
    assert para_data(pd.Series(["2024-01-07T03:00:00Z"])).iloc[0] == pd.Timestamp("2024-01-07")
    assert para_data(pd.Series(["2024-01-07", "2024-01-14"])).tolist() == [
        pd.Timestamp("2024-01-07"), pd.Timestamp("2024-01-14")]


def test_domingo_mais_proximo():
    d = pd.Series(pd.to_datetime(["2024-01-06", "2024-01-07", "2024-01-08"]))  # sáb, dom, seg
    ajustado, n = domingo_mais_proximo(d)
    assert ajustado.tolist() == [pd.Timestamp("2024-01-07")] * 3 and n == 2


def test_padronizar_fica_com_versao_mais_recente():
    bruto = pd.DataFrame({"data_iniSE": ["2024-01-07"] * 2, "casos": [9, 5], "municipio_geocodigo": [1, 1],
                          "versao_modelo": ["2024-02-01", "2024-01-15"]})
    assert padronizar_infodengue(bruto)["casos"].tolist() == [9]


def test_lacunas():
    df = pd.DataFrame({"geocode": 1, "inicio_semana": pd.to_datetime(["2024-01-07", "2024-01-14", "2024-02-04"])})
    assert lacunas(df)["faltando"].tolist() == [2]


def test_limiar_sem_populacao_usa_casos(painel):
    sem_pop = painel.drop(columns=["pop", "incidencia"])
    lim = limiares(sem_pop, 0.9)
    assert (lim["base_limiar"] == "casos").all()
    esperado = sem_pop.dropna(subset=["y"]).groupby("geocode")["y"].quantile(0.9)
    assert lim.set_index("geocode")["limiar_casos"].round(6).equals(esperado.round(6))
    com_pop = limiares(painel, 0.9)
    assert (com_pop["base_limiar"] == "incidencia").all()
