"""Exportação para o Power BI: integridade do modelo estrela e coerência com o kit (M e DAX)."""

import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from dengue_df import pipeline, storage
from dengue_df.config import CONFIG_PADRAO, RAIZ, carregar_config
from dengue_df.powerbi import exportar

KIT = RAIZ / "powerbi"
TABELAS = ["dim_municipio", "dim_semana", "dim_modelo", "fato_observado", "fato_previsao", "fato_backtest",
           "fato_resumo", "fato_cobertura", "fato_confiabilidade", "info_execucao"]


@pytest.fixture(scope="module")
def cfg(tmp_path_factory):
    raiz = tmp_path_factory.mktemp("pbi")
    c = yaml.safe_load(CONFIG_PADRAO.read_text(encoding="utf-8"))
    c["dados"]["inicio"] = "2017-01-01"
    c["territorio"]["municipios"] = c["territorio"]["municipios"][:3]
    c["modelo"]["horizontes"] = [1, 2]
    c["backtest"]["temporadas_teste"] = 1
    (raiz / "config").mkdir()
    caminho = raiz / "config" / "settings.yaml"
    caminho.write_text(yaml.safe_dump(c, allow_unicode=True), encoding="utf-8")
    cfg = carregar_config(caminho)
    pipeline.gerar_demo(cfg, fim="2025-10-31")
    pipeline.executar(cfg)
    return cfg


@pytest.fixture(scope="module")
def t(cfg):
    arquivos = exportar(cfg)
    assert sorted(arquivos) == sorted(TABELAS)
    ler = (lambda p: pd.read_parquet(p)) if arquivos["dim_semana"].suffix == ".parquet" else pd.read_csv
    return {n: ler(p) for n, p in arquivos.items()} | {"_arquivos": arquivos}


def _datas(s):
    return pd.to_datetime(s)


def test_chaves_unicas_nas_dimensoes(t):
    assert t["dim_municipio"]["geocode"].is_unique
    assert t["dim_semana"]["inicio_semana"].is_unique
    assert t["dim_modelo"]["modelo"].is_unique
    assert t["dim_semana"]["rotulo_se"].is_unique  # usada em "classificar por coluna"


def test_integridade_referencial(t):
    geos, mods = set(t["dim_municipio"]["geocode"]), set(t["dim_modelo"]["modelo"])
    semanas = set(_datas(t["dim_semana"]["inicio_semana"]))
    for nome, col_data in [("fato_observado", "inicio_semana"), ("fato_previsao", "semana_alvo"),
                           ("fato_backtest", "semana_alvo")]:
        f = t[nome]
        assert set(f["geocode"]) <= geos, nome
        assert set(_datas(f[col_data])) <= semanas, nome
    for nome in ["fato_previsao", "fato_backtest", "fato_resumo", "fato_cobertura", "fato_confiabilidade"]:
        assert set(t[nome]["modelo"]) <= mods, nome


def test_intervalos_aninhados(t):
    for nome in ["fato_previsao", "fato_backtest"]:
        f = t[nome]
        ordem = ["li_95", "li_90", "li_80", "li_50", "mediana", "ls_50", "ls_80", "ls_90", "ls_95"]
        assert (np.diff(f[ordem].to_numpy(), axis=1) >= -1e-9).all(), nome


def test_ancora_e_ultimo_observado(t, cfg):
    p, o = t["fato_previsao"], t["fato_observado"]
    anc = p[p["horizonte"] == 0]
    assert len(anc) == len(t["dim_modelo"]) * len(t["dim_municipio"])
    assert anc["prob_alerta"].isna().all() and (anc["tipo"] == "Último observado").all()
    ult = o.assign(d=_datas(o["inicio_semana"])).sort_values("d").groupby("geocode").tail(1)
    m = anc.merge(ult, on="geocode")
    assert np.allclose(m["mediana"], m["casos_usados"]) and np.allclose(m["ls_95"], m["casos_usados"])
    assert p.loc[p["horizonte"] >= 1, "prob_alerta"].between(0, 1).all()


def test_linhas_do_grafico_emendam(t):
    o = t["fato_observado"]
    for _, d in o.groupby("geocode"):
        d = d.sort_values("inicio_semana")
        assert d["casos_consolidados"].notna().sum() + d["casos_nowcast"].notna().sum() == len(d)
        # a linha do nowcast começa exatamente na última semana consolidada
        primeira = d["linha_nowcast"].first_valid_index()
        assert primeira == d["casos_consolidados"].last_valid_index()


def test_medias_reproduzem_resumo(t):
    """As medidas AVERAGE do DAX, por modelo e horizonte, têm de bater com o resumo do Python."""
    b, r = t["fato_backtest"], t["fato_resumo"]
    m = b.groupby(["modelo", "horizonte"]).agg(wis=("wis", "mean"), cobre_90=("cobre_90", "mean"),
                                               brier=("brier", "mean"), n=("wis", "count")).reset_index()
    x = m.merge(r, on=["modelo", "horizonte"], suffixes=("_pbi", ""))
    assert np.allclose(x["wis_pbi"], x["wis"]) and np.allclose(x["cobre_90_pbi"], x["cobre_90"])
    assert np.allclose(x["brier"], x["brier_alerta"]) and (x["n_pbi"] == x["n"]).all()
    # WIS relativo: mesma conta da medida DAX (modelo / climatologia no mesmo horizonte)
    wl = b.groupby(["modelo", "horizonte"])["wis_log"].mean().unstack(0)
    rel = (wl.div(wl["climatologia"], axis=0)).stack().rename("rel").reset_index()
    y = rel.merge(r, on=["modelo", "horizonte"])
    assert np.allclose(y["rel"], y["wis_log_relativo"])


def test_datas_sem_hora_e_info(t):
    for nome, col in [("dim_semana", "inicio_semana"), ("fato_previsao", "semana_alvo"),
                      ("info_execucao", "ultima_semana")]:
        assert t[nome][col].astype(str).str.len().eq(10).all(), nome
    info = t["info_execucao"].iloc[0]
    assert info["fonte"] == "sintetico" and info["rotulo_ultima_semana"].startswith("SE ")
    assert len(str(info["gerado_em"])) > 10  # data e hora


def test_parquet_com_tipo_data(t):
    pq = pytest.importorskip("pyarrow.parquet")
    import pyarrow as pa

    schema = pq.read_schema(t["_arquivos"]["dim_semana"])
    assert schema.field("inicio_semana").type == pa.date32()


def test_semana_da_temporada(t):
    s = t["dim_semana"]
    assert (s.loc[s["se"] == 41, "semana_temporada"] == 1).all()
    assert s["semana_temporada"].between(1, 53).all()


def test_funciona_com_saidas_antigas_sem_backtest_risco(cfg, t):
    storage.remover(cfg.dir_saidas / "backtest_risco")
    pasta = cfg.dir_saidas / "powerbi_antigo"
    arquivos = exportar(cfg, pasta)
    ler = (lambda p: pd.read_parquet(p)) if arquivos["fato_backtest"].suffix == ".parquet" else pd.read_csv
    novo = ler(arquivos["fato_backtest"])
    assert np.isclose(novo["brier"].mean(), t["fato_backtest"]["brier"].mean())


# ---------------------------------------------------------------- kit: M e DAX
def _colunas(t):
    return {n: set(df.columns) for n, df in t.items() if not n.startswith("_")}


def test_consultas_m_cobrem_todas_as_tabelas():
    texto = (KIT / "consultas.pq").read_text(encoding="utf-8")
    assert set(re.findall(r'LerTabela\("(\w+)"\)', texto)) == set(TABELAS)


def _colunas_calculadas(dax):
    """Colunas criadas no próprio kit, nas seções `// ==== colunas calculadas (tabela)`."""
    calculadas, tabela = {}, None
    for linha in dax.splitlines():
        secao = re.match(r"//\s*=+\s*(.*)", linha)
        if secao:
            alvo = re.match(r"colunas calculadas \((\w+)\)", secao.group(1).strip())
            tabela = alvo.group(1) if alvo else None
            continue
        nome = re.match(r"^(\w+) =\s*$", linha)
        if tabela and nome:
            calculadas.setdefault(tabela, set()).add(nome.group(1))
    return calculadas


def test_dax_referencia_colunas_que_existem(t):
    dax = (KIT / "medidas.dax").read_text(encoding="utf-8")
    codigo = "\n".join(linha.split("//")[0] for linha in dax.splitlines())
    cols = _colunas(t)
    for tabela, nomes in _colunas_calculadas(dax).items():
        cols.setdefault(tabela, set()).update(nomes)
    refs = re.findall(r"\b(dim_\w+|fato_\w+|info_execucao)\[([^\]]+)\]", codigo)
    assert refs
    faltando = [(tab, col) for tab, col in refs if col not in cols.get(tab, set())]
    assert not faltando, faltando


def test_dax_referencia_medidas_definidas():
    dax = (KIT / "medidas.dax").read_text(encoding="utf-8")
    codigo = "\n".join(linha.split("//")[0] for linha in dax.splitlines())
    definidas = set(re.findall(r"^([^\s/][^=\n]*?) =\s*$", codigo, flags=re.M))
    # colunas de tabelas virtuais (ADDCOLUMNS / SELECTCOLUMNS), declaradas como "@nome"
    virtuais = set(re.findall(r'"(@\w+)"', codigo))
    usadas = set(re.findall(r"(?<![\w\]])\[([^\]]+)\]", codigo)) - virtuais
    assert not (usadas - definidas), usadas - definidas
    assert not [n for n in definidas if re.search(r"[\[\]:]", n)]  # nomes seguros no Power BI


def test_tema_valido():
    import json

    tema = json.loads((KIT / "tema_dengue_df.json").read_text(encoding="utf-8"))
    assert len(tema["dataColors"]) == 8 and tema["dataColors"][0] == "#2A78D6"
