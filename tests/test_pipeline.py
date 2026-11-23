"""Pipeline completo com dados sintéticos, num diretório temporário."""

import yaml

from dengue_df import pipeline, storage
from dengue_df.config import CONFIG_PADRAO, carregar_config
from dengue_df.painel_dados import faixas, ranking_risco


def test_demo_ponta_a_ponta(tmp_path):
    c = yaml.safe_load(CONFIG_PADRAO.read_text(encoding="utf-8"))
    c["dados"]["inicio"] = "2017-01-01"
    c["territorio"]["municipios"] = c["territorio"]["municipios"][:3]
    c["modelo"]["horizontes"] = [1, 2]
    c["backtest"]["temporadas_teste"] = 1
    (tmp_path / "config").mkdir()
    caminho = tmp_path / "config" / "settings.yaml"
    caminho.write_text(yaml.safe_dump(c, allow_unicode=True), encoding="utf-8")

    cfg = carregar_config(caminho)
    assert cfg.dir_saidas == tmp_path / "outputs"
    pipeline.gerar_demo(cfg, fim="2025-10-31")
    s = pipeline.executar(cfg)

    assert storage.ler_metadados(cfg.dir_saidas / "metadata.json")["fonte"] == "sintetico"
    r = s["backtest_resumo"]
    assert set(r["modelo"]) == set(cfg.modelos) and r["wis"].notna().all()
    assert (r.loc[r["modelo"] == "climatologia", "wis_log_relativo"] == 1).all()
    assert s["risco"]["prob_alerta"].between(0, 1).all()
    geocode = int(s["painel"]["geocode"].iloc[0])
    assert not faixas(s["previsao"], geocode, "gbm_quantilico").empty
    assert len(ranking_risco(s["risco"], "gbm_quantilico", 1)) == 3
    for nome in ["painel", "previsao", "risco", "backtest_previsoes", "cobertura", "confiabilidade"]:
        assert storage.existe(cfg.dir_saidas / nome)
