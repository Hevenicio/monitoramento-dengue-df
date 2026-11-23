"""Ingestão real ponta a ponta contra um substituto da API (formato bruto do Mosqlimate)."""

import pandas as pd
import pytest
import yaml

from dengue_df import pipeline, storage
from dengue_df.config import CONFIG_PADRAO, carregar_config
from dengue_df.ingest.api import ErroDefinitivo
from tests.fakes import MosqlimateFalso

MUN = [{"nome": "Brasília", "uf": "DF", "geocode": 5300108},
       {"nome": "Águas Lindas de Goiás", "uf": "GO", "geocode": 5200258},
       {"nome": "Valparaíso de Goiás", "uf": "GO", "geocode": 5221858}]


def ano(inicio_pedido: str) -> int:
    """Ano do pedaço (o InfoDengue é pedido com 7 dias de sobreposição antes do 1.º de janeiro)."""
    return (pd.Timestamp(inicio_pedido) + pd.Timedelta(days=7)).year


def nao_chamar_ibge(uf):
    raise AssertionError("todos os municípios têm geocode; o IBGE não deveria ser consultado")


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("MOSQLIMATE_API_KEY", "chave-de-teste")
    c = yaml.safe_load(CONFIG_PADRAO.read_text(encoding="utf-8"))
    c["dados"].update(inicio="2017-01-01", fim="2025-10-31")
    c["territorio"]["municipios"] = MUN
    c["modelo"]["horizontes"] = [1, 2]
    c["backtest"]["temporadas_teste"] = 1
    c["api"] = {"cache": True, "semanas_revisao": 12, "tentativas": 2, "espera_segundos": 0, "pausa_segundos": 0}
    (tmp_path / "config").mkdir()
    caminho = tmp_path / "config" / "settings.yaml"
    caminho.write_text(yaml.safe_dump(c, allow_unicode=True), encoding="utf-8")
    return carregar_config(caminho)


def test_ingerir_executar_e_retomar_do_cache(cfg):
    pipeline.gerar_demo(cfg, fim="2025-10-31")  # sobra de uma demonstração anterior
    api = MosqlimateFalso(MUN)
    r = pipeline.ingerir(cfg, cliente=api, buscar_uf=nao_chamar_ibge)
    assert r["municipios"] == 3 and r["semanas_faltando"] == 0 and not r["falhas_clima"]
    assert storage.ler_metadados(cfg.dir_processed / "metadata.json")["fonte"] == "mosqlimate"
    info = storage.ler(cfg.dir_processed / "infodengue", colunas_data=("inicio_semana",))
    assert info.duplicated(["geocode", "inicio_semana"]).sum() == 0  # sobreposição entre pedaços removida
    assert info["inicio_semana"].dt.dayofweek.eq(6).all()

    s = pipeline.executar(cfg)
    assert storage.ler_metadados(cfg.dir_saidas / "metadata.json")["fonte"] == "mosqlimate"
    assert s["risco"]["prob_alerta"].between(0, 1).all()
    assert (s["limiares"]["base_limiar"] == "incidencia").all()

    api2 = MosqlimateFalso(MUN)
    pipeline.ingerir(cfg, cliente=api2, buscar_uf=nao_chamar_ibge)
    # 2.ª rodada: só o ano recente de cada município (InfoDengue + clima) volta à API.
    assert len(api2.chamadas) == 6 and {ano(c[2]) for c in api2.chamadas} == {2025}


def test_falha_no_infodengue_nao_grava_e_retoma(cfg):
    def falhar(tipo, geocode, a, b):
        if tipo == "info" and geocode == 5200258 and ano(a) == 2019:
            raise ConnectionError("503 Service Unavailable")

    with pytest.raises(RuntimeError, match="rode o comando de novo"):
        pipeline.ingerir(cfg, cliente=MosqlimateFalso(MUN, falhar=falhar), buscar_uf=nao_chamar_ibge)
    assert not storage.existe(cfg.dir_processed / "infodengue")

    api = MosqlimateFalso(MUN)
    pipeline.ingerir(cfg, cliente=api, buscar_uf=nao_chamar_ibge)
    info_chamadas = sorted((g, ano(a)) for t, g, a, b in api.chamadas if t == "info")
    assert info_chamadas == [(5200258, 2019), (5200258, 2025), (5221858, 2025), (5300108, 2025)]


def test_sem_clima_segue_sem_sobra_da_demo(cfg):
    pipeline.gerar_demo(cfg, fim="2025-10-31")
    assert storage.existe(cfg.dir_processed / "clima")

    def falhar(tipo, *a):
        if tipo == "clima":
            raise ConnectionError("timeout")

    r = pipeline.ingerir(cfg, cliente=MosqlimateFalso(MUN, falhar=falhar), buscar_uf=nao_chamar_ibge)
    assert r["ultima_semana_clima"] is None and r["falhas_clima"]
    assert not storage.existe(cfg.dir_processed / "clima")


def test_chave_invalida_para_na_primeira_chamada(cfg):
    def falhar(*a):
        raise Exception("401 Client Error: Unauthorized")

    api = MosqlimateFalso(MUN, falhar=falhar)
    with pytest.raises(ErroDefinitivo):
        pipeline.ingerir(cfg, cliente=api, buscar_uf=nao_chamar_ibge)
    assert len(api.chamadas) == 1


def test_sem_populacao_limiar_por_casos(cfg):
    pipeline.ingerir(cfg, cliente=MosqlimateFalso(MUN, sem=("pop",)), buscar_uf=nao_chamar_ibge)
    s = pipeline.executar(cfg)
    assert (s["limiares"]["base_limiar"] == "casos").all()
    assert s["risco"]["prob_alerta"].between(0, 1).all()


def test_verificar_ok(cfg, capsys):
    assert pipeline.verificar(cfg, cliente=MosqlimateFalso(MUN), buscar_uf=nao_chamar_ibge)
    saida = capsys.readouterr().out
    assert "[ERRO]" not in saida and "Tudo certo" in saida and "atraso de" in saida


def test_verificar_aponta_coluna_ausente(cfg, capsys):
    api = MosqlimateFalso(MUN)
    api.info = api.info.drop(columns="municipio_geocodigo").assign(geocodigo=api.info["municipio_geocodigo"])
    api._filtrar = lambda df, col_geo, *r: MosqlimateFalso._filtrar(
        df, "geocodigo" if col_geo == "municipio_geocodigo" else col_geo, *r)
    assert not pipeline.verificar(cfg, cliente=api, buscar_uf=nao_chamar_ibge)
    assert "municipio_geocodigo" in capsys.readouterr().out
