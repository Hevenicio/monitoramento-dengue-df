"""Exportação das saídas para o Power BI, em modelo estrela.

Lê as tabelas que `executar` grava em outputs/ e escreve em outputs/powerbi/:

  dim_municipio        1 linha por município (nome, UF, população, limiar de alerta)
  dim_semana           1 linha por semana epidemiológica (rótulos, temporada, distância da última)
  dim_modelo           1 linha por modelo (nome de exibição e ordem para as legendas)
  fato_observado       casos por município e semana (consolidados e em nowcast) + clima
  fato_previsao        previsão atual em formato largo (mediana e limites dos intervalos)
  fato_backtest        previsões do backtest com o observado, WIS, cobertura e Brier
  fato_resumo          médias do backtest por modelo e horizonte
  fato_cobertura       cobertura nominal x observada por modelo, horizonte e nível
  fato_confiabilidade  probabilidade prevista x frequência observada de alerta
  info_execucao        1 linha: fonte, última semana, temporadas de teste, data de geração

Datas saem como data (sem hora). Formato Parquet quando há pyarrow; CSV caso contrário.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from dengue_df import storage
from dengue_df.config import Config
from dengue_df.epiweek import rotulo_temporada
from dengue_df.evaluation.metrics import CHAVES, pares_intervalo
from dengue_df.ingest.municipios import normalizar

log = logging.getLogger(__name__)

MODELOS = {
    "gbm_quantilico": ("GBM quantílico", 1,
                       "Gradient boosting com perda quantílica: lags de casos, sazonalidade e clima."),
    "crescimento": ("Crescimento sazonal", 2,
                    "Nível atual × crescimento histórico em h semanas nessa época do ano."),
    "climatologia": ("Climatologia", 3,
                     "Quantis históricos da mesma época do ano; ignora o nível atual."),
}
DATAS = ("inicio_semana", "semana_alvo", "origem")


# ---------------------------------------------------------------- utilidades
def _ler(cfg: Config, nome: str) -> pd.DataFrame:
    return storage.ler(cfg.dir_saidas / nome, colunas_data=DATAS)


def niveis(quantis: list[float]) -> dict[int, tuple[float, float]]:
    """{50: (0.25, 0.75), 80: (0.1, 0.9), ...} a partir dos quantis disponíveis."""
    return {int(round((1 - a) * 100)): (ql, qu) for a, ql, qu in pares_intervalo(quantis)}


def largo_intervalos(previsoes: pd.DataFrame, chaves: list[str]) -> pd.DataFrame:
    """Formato longo (1 linha por quantil) -> mediana, li_N e ls_N por intervalo central."""
    largo = previsoes.pivot_table(index=chaves, columns="quantil", values="valor").reset_index()
    quantis = sorted(c for c in largo.columns if isinstance(c, float))
    out = largo[chaves].copy()
    out["mediana"] = largo[0.5]
    for n, (ql, qu) in sorted(niveis(quantis).items()):
        out[f"li_{n}"] = largo[ql]
        out[f"ls_{n}"] = largo[qu]
    return out


def _para_data(df: pd.DataFrame) -> pd.DataFrame:
    """Colunas datetime -> date (Parquet date32 = tipo Data no Power BI)."""
    df = df.copy()
    for c in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[c]) and (df[c].dropna() == df[c].dropna().dt.normalize()).all():
            df[c] = df[c].dt.date  # datas puras; colunas com hora (gerado_em) ficam como estão
    return df


def _gravar(df: pd.DataFrame, pasta: Path, nome: str, parquet: bool) -> Path:
    df = _para_data(df).reset_index(drop=True)
    if parquet:
        destino = pasta / f"{nome}.parquet"
        df.to_parquet(destino, index=False)
    else:
        destino = pasta / f"{nome}.csv"
        df.to_csv(destino, index=False, encoding="utf-8")
    return destino


# ---------------------------------------------------------------- tabelas
def dim_municipio(cfg: Config, painel: pd.DataFrame, lim: pd.DataFrame) -> pd.DataFrame:
    if storage.existe(cfg.dir_processed / "municipios"):
        mun = storage.ler(cfg.dir_processed / "municipios")[["geocode", "nome", "uf"]]
    else:
        mun = painel[["geocode", "nome"]].drop_duplicates("geocode").assign(uf="")
    mun = mun[mun["geocode"].isin(painel["geocode"].unique())].copy()
    d = mun.rename(columns={"nome": "municipio"})
    d["regiao"] = np.where(d["uf"] == "DF", "Distrito Federal", "Entorno (" + d["uf"].astype(str) + ")")
    d["local_mapa"] = d["municipio"] + ", " + d["uf"].astype(str) + ", Brasil"
    d = d.merge(lim.rename(columns={"pop": "populacao"}), on="geocode", how="left")
    d = d.sort_values(["regiao", "municipio"], key=lambda s: s.map(normalizar) if s.name == "municipio" else s)
    d["ordem"] = np.arange(1, len(d) + 1)
    return d[["geocode", "municipio", "uf", "regiao", "local_mapa", "populacao", "limiar_casos",
              "limiar_incidencia", "base_limiar", "ordem"]]


def dim_semana(painel: pd.DataFrame, previsao: pd.DataFrame, inicio_se: int) -> tuple[pd.DataFrame, pd.Timestamp]:
    from dengue_df.epiweek import inicio_semana, semana_epidemiologica, temporada

    ultima = painel.loc[painel["y"].notna(), "inicio_semana"].max()
    fim = max(ultima, previsao["semana_alvo"].max()) if len(previsao) else ultima
    semanas = pd.date_range(painel["inicio_semana"].min(), fim, freq="7D")
    se = semana_epidemiologica(semanas)
    d = pd.DataFrame({"inicio_semana": semanas, "fim_semana": semanas + pd.Timedelta(days=6)})
    d["ano_se"], d["se"] = se["ano_se"].to_numpy(), se["se"].to_numpy()
    d["rotulo_se"] = "SE " + d["se"].astype(str).str.zfill(2) + "/" + d["ano_se"].astype(str)
    d["temporada"] = temporada(d["ano_se"], d["se"], inicio_se).to_numpy()
    d["rotulo_temporada"] = d["temporada"].map(rotulo_temporada)
    # Semana dentro da temporada: 1 = SE de início (padrão SE 41) do ano em que a temporada começa.
    ini_se1 = inicio_semana(d["temporada"].astype(str) + "-01-04")
    ini_temp = ini_se1 + pd.to_timedelta((inicio_se - 1) * 7, unit="D")
    d["semana_temporada"] = ((d["inicio_semana"] - ini_temp.to_numpy()).dt.days // 7 + 1).astype(int)
    d["semanas_desde_ultima"] = ((d["inicio_semana"] - ultima).dt.days // 7).astype(int)
    d["periodo"] = np.where(d["semanas_desde_ultima"] > 0, "Previsão", "Observado")
    d["mes"] = d["inicio_semana"].dt.month
    d["ano"] = d["inicio_semana"].dt.year
    return d, ultima


def dim_modelo(modelos: list[str]) -> pd.DataFrame:
    linhas = []
    for i, m in enumerate(modelos):
        nome, ordem, desc = MODELOS.get(m, (m, 10 + i, ""))
        linhas.append({"modelo": m, "modelo_nome": nome, "ordem": ordem, "descricao": desc})
    return pd.DataFrame(linhas).sort_values("ordem")


def fato_observado(painel: pd.DataFrame) -> pd.DataFrame:
    d = painel[painel["y"].notna()].copy()
    out = d[["geocode", "inicio_semana"]].copy()
    out["casos_notificados"] = d["casos"] if "casos" in d.columns else np.nan
    out["casos_est"] = d["casos_est"] if "casos_est" in d.columns else np.nan
    out["casos_usados"] = d["y"]
    out["nowcast"] = d["nowcast"].astype(bool)
    out["casos_consolidados"] = d["y"].where(~out["nowcast"])
    out["casos_nowcast"] = d["y"].where(out["nowcast"])
    # Só para o gráfico: a linha tracejada do nowcast começa na última semana consolidada,
    # para emendar com a linha cheia (não some esta coluna com casos_consolidados).
    seguinte_nowcast = out.groupby("geocode")["nowcast"].shift(-1, fill_value=False).astype(bool)
    out["linha_nowcast"] = d["y"].where(out["nowcast"] | seguinte_nowcast)
    out["incidencia"] = d["incidencia"] if "incidencia" in d.columns else np.nan
    for c in ("temp_med", "precip_tot", "umid_med"):
        if c in d.columns:
            out[c] = d[c]
    return out


def fato_previsao(previsao: pd.DataFrame, risco: pd.DataFrame, painel: pd.DataFrame) -> pd.DataFrame:
    """Previsão atual + uma linha 'âncora' (horizonte 0) com o último valor observado,
    para a linha e a faixa da previsão partirem do fim da série observada no gráfico."""
    p = largo_intervalos(previsao, CHAVES)
    p = p.merge(risco[CHAVES + ["limiar_casos", "prob_alerta"]], on=CHAVES, how="left")
    p["mediana_acima_limiar"] = p["mediana"] > p["limiar_casos"]
    p["tipo"] = "Previsão"

    obs = painel[["geocode", "inicio_semana", "y"]].dropna()
    ancoras = []
    for (modelo, geocode, origem), d in p.groupby(["modelo", "geocode", "origem"]):
        y = obs.loc[(obs["geocode"] == geocode) & (obs["inicio_semana"] == origem), "y"]
        if y.empty:
            continue
        a = {c: float(y.iloc[0]) for c in p.columns if c == "mediana" or c[:3] in ("li_", "ls_")}
        a |= {"modelo": modelo, "geocode": geocode, "origem": origem, "horizonte": 0,
              "semana_alvo": origem, "limiar_casos": d["limiar_casos"].iloc[0], "prob_alerta": np.nan,
              "mediana_acima_limiar": False, "tipo": "Último observado"}
        ancoras.append(a)
    p = pd.concat([pd.DataFrame(ancoras), p], ignore_index=True) if ancoras else p
    return p.sort_values(["modelo", "geocode", "semana_alvo"]).reset_index(drop=True)


def fato_backtest(prev_bt: pd.DataFrame, aval: pd.DataFrame, risco_bt: pd.DataFrame) -> pd.DataFrame:
    chaves = CHAVES + ["temporada_teste"]
    b = largo_intervalos(prev_bt, chaves)
    cols_aval = ["observado", "wis", "wis_log", "erro_abs_mediana"] + [c for c in aval.columns if c.startswith("cobre_")]
    b = b.merge(aval[CHAVES + cols_aval], on=CHAVES, how="inner")
    b = b.merge(risco_bt[CHAVES + ["limiar_casos", "prob_alerta", "excedeu"]], on=CHAVES, how="left")
    for c in [c for c in b.columns if c.startswith("cobre_")] + ["excedeu"]:
        b[c] = b[c].astype(float)  # 0/1: a média vira proporção no Power BI
    b["brier"] = (b["prob_alerta"] - b["excedeu"]) ** 2
    b["rotulo_temporada_teste"] = b["temporada_teste"].astype(int).map(rotulo_temporada)
    return b


def fato_cobertura(aval: pd.DataFrame) -> pd.DataFrame:
    cob = [c for c in aval.columns if c.startswith("cobre_")]
    t = aval.groupby(["modelo", "horizonte"])[cob].mean().reset_index().melt(
        id_vars=["modelo", "horizonte"], var_name="nivel", value_name="cobertura_observada")
    t["nivel"] = t["nivel"].str.replace("cobre_", "").astype(int)
    t["cobertura_nominal"] = t["nivel"] / 100
    t["rotulo_nivel"] = "IC " + t["nivel"].astype(str) + "%"
    return t.sort_values(["modelo", "horizonte", "nivel"])


# ---------------------------------------------------------------- orquestração
def exportar(cfg: Config, pasta: Path | None = None) -> dict[str, Path]:
    """Gera as tabelas do Power BI a partir de outputs/ (rode `executar` antes)."""
    from dengue_df.pipeline import _risco_backtest

    if not storage.existe(cfg.dir_saidas / "previsao"):
        raise FileNotFoundError(f"Não achei as saídas em {cfg.dir_saidas}. Rode `executar` antes.")
    pasta = pasta or cfg.dir_saidas / "powerbi"
    pasta.mkdir(parents=True, exist_ok=True)
    parquet = storage._tem_parquet()
    if not parquet:
        log.warning("pyarrow não instalado: exportando CSV. As consultas do kit esperam Parquet.")

    painel = _ler(cfg, "painel")
    previsao, risco, lim = _ler(cfg, "previsao"), _ler(cfg, "risco"), _ler(cfg, "limiares")
    prev_bt, aval = _ler(cfg, "backtest_previsoes"), _ler(cfg, "backtest_avaliacao")
    if storage.existe(cfg.dir_saidas / "backtest_risco"):
        risco_bt = _ler(cfg, "backtest_risco")
    else:  # saídas de uma versão anterior: calcula aqui
        log.info("Calculando o risco do backtest (saídas geradas antes da v0.3)")
        risco_bt = _risco_backtest(painel, prev_bt, cfg)
    meta = storage.ler_metadados(cfg.dir_saidas / "metadata.json")

    semanas, ultima = dim_semana(painel, previsao, cfg.inicio_temporada_se)
    modelos = sorted(set(previsao["modelo"]) | set(prev_bt["modelo"]), key=lambda m: MODELOS.get(m, ("", 99))[1])
    resumo = _ler(cfg, "backtest_resumo")
    tabelas = {
        "dim_municipio": dim_municipio(cfg, painel, lim),
        "dim_semana": semanas,
        "dim_modelo": dim_modelo(modelos),
        "fato_observado": fato_observado(painel),
        "fato_previsao": fato_previsao(previsao, risco, painel),
        "fato_backtest": fato_backtest(prev_bt, aval, risco_bt),
        "fato_resumo": resumo,
        "fato_cobertura": fato_cobertura(aval),
        "fato_confiabilidade": _ler(cfg, "confiabilidade"),
        "info_execucao": pd.DataFrame([{
            "fonte": meta.get("fonte", "desconhecida"),
            "aviso": meta.get("aviso") or "",
            "ultima_semana": ultima,
            "rotulo_ultima_semana": semanas.loc[semanas["inicio_semana"] == ultima, "rotulo_se"].iloc[0],
            "temporadas_teste": ", ".join(rotulo_temporada(int(t)) for t in meta.get("temporadas_teste", [])),
            "percentil_limiar": meta.get("percentil_limiar", cfg.percentil_limiar),
            "gerado_em": pd.Timestamp(meta.get("gerado_em", pd.Timestamp.now())),
        }]),
    }
    for antigo in list(pasta.glob("*.parquet")) + list(pasta.glob("*.csv")):
        antigo.unlink()
    return {nome: _gravar(df, pasta, nome, parquet) for nome, df in tabelas.items()}
