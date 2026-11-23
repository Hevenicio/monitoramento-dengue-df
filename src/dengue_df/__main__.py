"""Linha de comando.

    python -m dengue_df verificar   # teste rápido da chave e da API (1 município, poucas semanas)
    python -m dengue_df ingerir     # baixa dados reais (precisa de MOSQLIMATE_API_KEY)
    python -m dengue_df executar    # backtest + previsão + tabelas do painel
    python -m dengue_df relatorio   # PNGs de prévia em outputs/
    python -m dengue_df exportar-powerbi  # tabelas do Power BI em outputs/powerbi/
    python -m dengue_df demo        # tudo acima com DADOS SINTÉTICOS (sem API)
"""

from __future__ import annotations

import argparse
import logging

from dengue_df import storage
from dengue_df.config import carregar_config


def _relatorio(cfg, saidas=None) -> None:
    from dengue_df.report import figura_cobertura, figura_previsao

    if saidas is None:
        nomes = ["painel", "previsao", "limiares", "cobertura"]
        saidas = {n: storage.ler(cfg.dir_saidas / n, colunas_data=("inicio_semana", "semana_alvo", "origem"))
                  for n in nomes}
    meta = storage.ler_metadados(cfg.dir_saidas / "metadata.json")
    aviso = "DADOS SINTÉTICOS — não representam a dengue real" if meta.get("fonte") == "sintetico" else None
    modelo = "gbm_quantilico" if "gbm_quantilico" in cfg.modelos else cfg.modelos[-1]
    geocode = int(saidas["painel"]["geocode"].iloc[0])
    p1 = figura_previsao(saidas, geocode, modelo, cfg.dir_saidas / "previa_previsao.png", aviso)
    p2 = figura_cobertura(saidas["cobertura"], cfg.dir_saidas / "previa_cobertura.png")
    print(f"Prévias gravadas em:\n  {p1}\n  {p2}")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="dengue_df", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("comando", choices=["verificar", "ingerir", "executar", "relatorio", "exportar-powerbi", "demo"])
    ap.add_argument("--config", default=None, help="caminho do settings.yaml")
    ap.add_argument("--refazer", action="store_true",
                    help="ingerir: ignora o cache em data/raw e baixa tudo de novo")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    # Mensagens de cada requisição HTTP poluem a saída; só os avisos delas interessam.
    for ruidoso in ("urllib3", "requests", "httpx", "httpcore"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)

    from dengue_df import pipeline

    cfg = carregar_config(args.config)
    if args.comando == "verificar":
        raise SystemExit(0 if pipeline.verificar(cfg) else 1)
    if args.comando == "ingerir":
        r = pipeline.ingerir(cfg, refazer=args.refazer)
        print(f"Dados gravados em {cfg.dir_processed}")
        print(f"  {r['municipios']} municípios, {r['linhas_infodengue']} semanas-município; "
              f"última semana de casos: {r['ultima_semana_infodengue']}; "
              f"de clima: {r['ultima_semana_clima'] or 'sem clima'}")
        if r["municipios_sem_dados"] or r["semanas_faltando"] or r["falhas_clima"]:
            print(f"  Avisos: sem dados={r['municipios_sem_dados']}, semanas faltando="
                  f"{r['semanas_faltando']}, pedaços de clima com falha={len(r['falhas_clima'])}")
    elif args.comando == "executar":
        saidas = pipeline.executar(cfg)
        print(f"Tabelas gravadas em {cfg.dir_saidas}\n")
        print(saidas["backtest_resumo"].round(3).to_string(index=False))
    elif args.comando == "relatorio":
        _relatorio(cfg)
    elif args.comando == "exportar-powerbi":
        import os

        from dengue_df.powerbi import exportar

        arquivos = exportar(cfg)
        pasta = next(iter(arquivos.values())).parent.resolve()
        print(f"{len(arquivos)} tabelas gravadas. No Power BI, use no parâmetro PastaDados:")
        print(f"  {pasta}{os.sep}")
    elif args.comando == "demo":
        pipeline.gerar_demo(cfg)
        saidas = pipeline.executar(cfg)
        _relatorio(cfg, saidas)
        print(saidas["backtest_resumo"].round(3).to_string(index=False))


if __name__ == "__main__":
    main()
