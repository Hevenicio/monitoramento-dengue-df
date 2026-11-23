"""Orquestração: ingestão -> painel -> backtest -> previsão final -> tabelas para o painel."""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from dengue_df import storage
from dengue_df.config import Config, chave_api
from dengue_df.evaluation.backtest import backtest, corte_da_temporada, temporadas_completas
from dengue_df.evaluation.metrics import avaliar, resumo, tabela_cobertura
from dengue_df.features import montar_painel, montar_tabela
from dengue_df.models import criar_modelo
from dengue_df.risk import limiares, tabela_risco

log = logging.getLogger(__name__)


# ---------------------------------------------------------------- ingestão
def _resolver(cfg: Config, buscar_uf=None) -> pd.DataFrame:
    from dengue_df.ingest.municipios import resolver_municipios

    kw = {} if buscar_uf is None else {"buscar_uf": buscar_uf}
    return resolver_municipios(cfg.municipios, cfg.dir_ref / "municipios.csv", **kw)


def ingerir(cfg: Config, refazer: bool = False, cliente=None, buscar_uf=None) -> dict:
    """Baixa municípios (IBGE), InfoDengue e clima (Mosqlimate) e grava em data/processed.

    O download é feito em pedaços com cache em data/raw/: se for interrompido, rodar de novo
    retoma de onde parou. Falhas no InfoDengue interrompem a gravação (a série de casos precisa
    estar completa); falhas no clima viram aviso. Devolve um resumo da ingestão.
    """
    from dengue_df.ingest.clima import baixar_clima
    from dengue_df.ingest.infodengue import _resumo_falhas, baixar_infodengue, lacunas

    cfg.criar_diretorios()
    chave = chave_api()
    mun = _resolver(cfg, buscar_uf)
    log.info("Municípios: %s", ", ".join(mun["nome"]))
    opc = cfg.opcoes_api() | {"refazer": refazer}

    def cache(nome: str):
        return cfg.dir_raw / nome if cfg.usar_cache else None

    falhas_info: list[dict] = []
    info = baixar_infodengue(mun["geocode"], cfg.inicio, cfg.fim, cfg.doenca, chave, cliente=cliente,
                             pasta_cache=cache(f"infodengue_{cfg.doenca}"), falhas=falhas_info, **opc)
    if falhas_info:
        raise RuntimeError(
            _resumo_falhas(falhas_info)
            + "\nSe um município falhar sempre, tire-o de config/settings.yaml ou informe o geocode."
        )

    sem_dados = sorted(set(mun["geocode"]) - set(info["geocode"]))
    if sem_dados:
        log.warning("InfoDengue sem dados para: %s", mun[mun["geocode"].isin(sem_dados)]["nome"].tolist())
    lac = lacunas(info).merge(mun[["geocode", "nome"]], on="geocode", how="left")
    for _, r in lac[lac["faltando"] > 0].iterrows():
        log.warning("%s: %d semanas faltando entre %s e %s", r["nome"], r["faltando"],
                    r["primeira"].date(), r["ultima"].date())

    # Nada de uma ingestão anterior (ou da demonstração sintética) pode sobrar misturado.
    for nome in ("municipios", "infodengue", "clima"):
        storage.remover(cfg.dir_processed / nome)
    (cfg.dir_processed / "metadata.json").unlink(missing_ok=True)
    storage.gravar(mun, cfg.dir_processed / "municipios")
    storage.gravar(info, cfg.dir_processed / "infodengue")

    falhas_clima: list[dict] = []
    ultima_clima = None
    if cfg.usar_clima:
        from dengue_df.ingest.api import ErroDefinitivo

        try:
            clima = baixar_clima(mun["geocode"], cfg.inicio, cfg.fim, chave, cliente=cliente,
                                 pasta_cache=cache("clima"), falhas=falhas_clima, **opc)
        except ErroDefinitivo:
            raise
        except Exception as e:  # noqa: BLE001 - sem clima, os modelos rodam só com casos
            log.warning("Clima indisponível (%s). Os modelos vão rodar só com a série de casos.", e)
            clima = None
        if clima is not None:
            storage.gravar(clima, cfg.dir_processed / "clima")
            ultima_clima = str(clima["inicio_semana"].max().date())
        if falhas_clima:
            log.warning("Clima: %d pedaço(s) falharam; as semanas afetadas ficam sem clima. "
                        "Rode `ingerir` de novo para tentar completar.", len(falhas_clima))

    resumo_ingestao = dict(
        fonte="mosqlimate", doenca=cfg.doenca, inicio=cfg.inicio, fim=cfg.fim,
        municipios=len(mun), linhas_infodengue=len(info),
        ultima_semana_infodengue=str(info["inicio_semana"].max().date()),
        ultima_semana_clima=ultima_clima,
        municipios_sem_dados=[int(g) for g in sem_dados],
        semanas_faltando=int(lac["faltando"].sum()),
        falhas_clima=falhas_clima,
    )
    storage.gravar_metadados(cfg.dir_processed / "metadata.json", **resumo_ingestao)
    return resumo_ingestao


def verificar(cfg: Config, cliente=None, buscar_uf=None) -> bool:
    """Teste rápido antes da ingestão completa: chave, IBGE, InfoDengue e clima com poucos dados.

    Imprime o que a API devolveu (colunas, últimas semanas, atraso do clima) e devolve True se
    tudo estiver pronto para `ingerir`.
    """
    from dengue_df.ingest import clima as m_clima
    from dengue_df.ingest import infodengue as m_info
    from dengue_df.ingest.api import com_tentativas

    ok = True
    if cliente is None:
        try:
            import mosqlient as cliente
        except ImportError:
            print("[ERRO] mosqlient não está instalado. Rode: pip install -e \".[painel,dev]\"")
            return False
    print(f"mosqlient {getattr(cliente, '__version__', '(versão não informada)')}")

    try:
        chave = chave_api()
        print("[ok] chave da API encontrada")
    except RuntimeError as e:
        print(f"[ERRO] {e}")
        return False

    cfg.criar_diretorios()
    try:
        mun = _resolver(cfg, buscar_uf)
        print(f"[ok] IBGE: {len(mun)} municípios -> {', '.join(mun['nome'])}")
    except Exception as e:  # noqa: BLE001
        print(f"[ERRO] IBGE: {e}")
        return False
    g, nome = int(mun["geocode"].iloc[0]), mun["nome"].iloc[0]
    fim = pd.Timestamp(cfg.fim)

    def chamar(desc, fn):
        return com_tentativas(fn, desc, tentativas=2, espera=2.0)

    # InfoDengue: últimas 10 semanas do primeiro município.
    a, b = (fim - pd.Timedelta(weeks=10)).date().isoformat(), fim.date().isoformat()
    print(f"\nInfoDengue ({cfg.doenca}) - {nome} ({g}), {a} a {b}")
    try:
        bruto = chamar("InfoDengue", lambda: cliente.get_infodengue(
            api_key=chave, disease=cfg.doenca, start_date=a, end_date=b, geocode=g))
        if bruto is None or bruto.empty:
            ok = False
            print("[ERRO] nenhuma linha retornada para o período")
        else:
            print(f"[ok] {len(bruto)} linhas; colunas: {', '.join(map(str, bruto.columns))}")
            faltam = [c for c in m_info.OBRIGATORIAS if c not in bruto.columns]
            if faltam:
                ok = False
                print(f"[ERRO] colunas obrigatórias ausentes: {faltam}")
            else:
                p = m_info.padronizar_infodengue(bruto)
                cols = [c for c in ["inicio_semana", "casos", "casos_est", "casos_est_min",
                                    "casos_est_max", "pop", "nivel"] if c in p.columns]
                print(p[cols].tail(5).to_string(index=False))
                if "pop" not in p.columns or p["pop"].isna().all():
                    print("[aviso] sem população: o limiar de alerta usará casos em vez de incidência")
                if "casos_est" not in p.columns:
                    print("[aviso] sem casos_est: as últimas semanas não terão correção de atraso")
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"[ERRO] {e}")

    # Clima: últimos 45 dias; se vier vazio, procura um ano antes para medir o atraso da base.
    if cfg.usar_clima:
        a = (fim - pd.Timedelta(days=45)).date().isoformat()
        print(f"\nClima - {nome} ({g}), {a} a {b}")
        try:
            bruto = chamar("Clima", lambda: cliente.get_climate(
                api_key=chave, start_date=a, end_date=b, geocode=g))
            if bruto is None or bruto.empty:
                a2 = (fim - pd.Timedelta(days=400)).date().isoformat()
                print(f"[aviso] nada nos últimos 45 dias; tentando {a2} a {b}")
                bruto = chamar("Clima", lambda: cliente.get_climate(
                    api_key=chave, start_date=a2, end_date=b, geocode=g))
            if bruto is None or bruto.empty:
                ok = False
                print("[ERRO] nenhuma linha de clima retornada")
            else:
                print(f"[ok] {len(bruto)} dias; colunas: {', '.join(map(str, bruto.columns))}")
                faltam = [c for c in m_clima.OBRIGATORIAS if c not in bruto.columns]
                variaveis = [c for c in m_clima.AGREGACAO if c in bruto.columns]
                if faltam or not variaveis:
                    ok = False
                    print(f"[ERRO] colunas ausentes: {faltam or 'nenhuma variável climática conhecida'}")
                else:
                    from dengue_df.ingest.api import para_data

                    ultimo = para_data(bruto["date"]).max()
                    atraso = (fim.normalize() - ultimo).days
                    print(f"[ok] último dia disponível: {ultimo.date()} (atraso de {atraso} dias)")
                    if atraso > 21:
                        print("[aviso] o clima está bem atrasado em relação aos casos; as previsões "
                              "mais recentes usarão janelas climáticas incompletas")
        except Exception as e:  # noqa: BLE001
            ok = False
            print(f"[ERRO] {e}")

    print("\nTudo certo: pode rodar `python -m dengue_df ingerir -v`." if ok
          else "\nHá problemas acima. Copie esta saída e mande para análise.")
    return ok


def gerar_demo(cfg: Config, fim: str | None = None) -> None:
    """Grava DADOS SINTÉTICOS no mesmo formato da ingestão real (para testes e demonstração)."""
    from dengue_df.ingest import sintetico

    cfg.criar_diretorios()
    mun, info, clima = sintetico.gerar(
        cfg.municipios, inicio=cfg.inicio, fim=fim or cfg.fim, semanas_nowcast=cfg.semanas_nowcast
    )
    storage.gravar(mun, cfg.dir_processed / "municipios")
    storage.gravar(info, cfg.dir_processed / "infodengue")
    storage.gravar(clima, cfg.dir_processed / "clima")
    storage.gravar_metadados(
        cfg.dir_processed / "metadata.json", fonte="sintetico",
        aviso="Dados sintéticos gerados para teste. Não representam a dengue real.",
    )


def carregar_processados(cfg: Config) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame | None]:
    mun = storage.ler(cfg.dir_processed / "municipios")
    info = storage.ler(cfg.dir_processed / "infodengue", colunas_data=("inicio_semana",))
    clima = None
    if cfg.usar_clima and storage.existe(cfg.dir_processed / "clima"):
        clima = storage.ler(cfg.dir_processed / "clima", colunas_data=("inicio_semana",))
    return mun, info, clima


# ---------------------------------------------------------------- modelagem
def fabricas(cfg: Config, com_clima: bool) -> dict:
    comum = dict(horizontes=cfg.horizontes, quantis=cfg.quantis, janela_sazonal=cfg.janela_sazonal,
                 lags=cfg.lags, com_clima=com_clima)
    return {nome: (lambda n=nome: criar_modelo(n, **comum)) for nome in cfg.modelos}


def _risco_backtest(painel, prev_bt, cfg: Config) -> pd.DataFrame:
    partes = []
    for temp, d in prev_bt.groupby("temporada_teste"):
        lim = limiares(painel, cfg.percentil_limiar, corte=corte_da_temporada(painel, temp))
        r = tabela_risco(d, lim)
        r["temporada_teste"] = temp
        partes.append(r)
    r = pd.concat(partes, ignore_index=True)
    obs = painel[["geocode", "inicio_semana", "y"]].rename(columns={"inicio_semana": "semana_alvo", "y": "observado"})
    r = r.merge(obs, on=["geocode", "semana_alvo"], how="inner").dropna(subset=["observado"])
    r["excedeu"] = r["observado"] > r["limiar_casos"]
    return r


def confiabilidade(risco_bt: pd.DataFrame, n_faixas: int = 10) -> pd.DataFrame:
    """Probabilidade prevista x frequência observada de alerta (diagrama de confiabilidade)."""
    faixas = np.linspace(0, 1, n_faixas + 1)
    r = risco_bt.assign(faixa=pd.cut(risco_bt["prob_alerta"], faixas, include_lowest=True))
    t = (
        r.groupby(["modelo", "faixa"], observed=True)
        .agg(prob_media=("prob_alerta", "mean"), freq_observada=("excedeu", "mean"), n=("excedeu", "size"))
        .reset_index()
    )
    t["faixa"] = t["faixa"].astype(str)
    return t


def executar(cfg: Config) -> dict[str, pd.DataFrame]:
    """Roda backtest e previsão final e grava todas as tabelas em outputs/."""
    mun, info, clima = carregar_processados(cfg)
    if clima is not None and len(clima):
        fim_casos, fim_clima = info["inicio_semana"].max(), clima["inicio_semana"].max()
        if fim_clima < fim_casos:
            log.warning("O clima termina em %s e os casos em %s: as últimas %d origens usam "
                        "janelas climáticas incompletas.", fim_clima.date(), fim_casos.date(),
                        (fim_casos - fim_clima).days // 7)
    painel = montar_painel(info, clima, mun, cfg.alvo, cfg.semanas_nowcast, cfg.inicio_temporada_se)
    tabela = montar_tabela(painel, cfg.lags, cfg.horizontes)
    fab = fabricas(cfg, com_clima=clima is not None)

    completas = temporadas_completas(tabela)
    # A primeira temporada completa fica sempre no treino.
    teste = completas[1:][-cfg.temporadas_teste:]
    if not teste:
        raise RuntimeError("Histórico curto demais para backtest: aumente o período em dados.inicio.")
    log.info("Temporadas de teste: %s", teste)

    prev_bt = backtest(tabela, fab, teste)
    aval = avaliar(prev_bt, painel)
    aval = aval.merge(prev_bt[["modelo", "geocode", "origem", "horizonte", "temporada_teste"]].drop_duplicates(),
                      on=["modelo", "geocode", "origem", "horizonte"], how="left")
    risco_bt = _risco_backtest(painel, prev_bt, cfg)
    res = resumo(aval)
    brier = risco_bt.assign(b=(risco_bt["prob_alerta"] - risco_bt["excedeu"]) ** 2).groupby(
        ["modelo", "horizonte"])["b"].mean().rename("brier_alerta").reset_index()
    res = res.merge(brier, on=["modelo", "horizonte"], how="left")

    # Previsão final: treina com tudo e prevê a partir da última semana de cada município.
    corte_final = tabela["inicio_semana"].max() + pd.Timedelta(days=1)
    ultima = tabela[tabela["ly"].notna()].sort_values("inicio_semana").groupby("geocode").tail(1)
    finais = []
    for nome, fabrica in fab.items():
        p = fabrica().ajustar(tabela, corte_final).prever(ultima)
        p["modelo"] = nome
        finais.append(p)
    prev_final = pd.concat(finais, ignore_index=True)
    lim = limiares(painel, cfg.percentil_limiar)
    risco = tabela_risco(prev_final, lim).merge(mun[["geocode", "nome"]], on="geocode", how="left")

    saidas = {
        "painel": painel,
        "backtest_previsoes": prev_bt,
        "backtest_avaliacao": aval,
        "backtest_resumo": res,
        "cobertura": tabela_cobertura(aval),
        "backtest_risco": risco_bt,
        "confiabilidade": confiabilidade(risco_bt),
        "previsao": prev_final,
        "limiares": lim,
        "risco": risco,
    }
    cfg.dir_saidas.mkdir(parents=True, exist_ok=True)
    for nome, df in saidas.items():
        storage.gravar(df, cfg.dir_saidas / nome)
    meta = storage.ler_metadados(cfg.dir_processed / "metadata.json")
    storage.gravar_metadados(
        cfg.dir_saidas / "metadata.json",
        fonte=meta.get("fonte", "desconhecida"),
        aviso=meta.get("aviso"),
        temporadas_teste=teste,
        ultima_semana=str(tabela["inicio_semana"].max().date()),
        modelos=cfg.modelos,
        horizontes=cfg.horizontes,
        percentil_limiar=cfg.percentil_limiar,
    )
    return saidas
