"""Download e padronização dos dados semanais do InfoDengue via API do Mosqlimate (mosqlient)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from dengue_df.ingest.api import coletar, domingo_mais_proximo, para_data

log = logging.getLogger(__name__)

# Colunas do InfoDengue usadas pelo projeto (nomes como retornados por mosqlient.get_infodengue).
OBRIGATORIAS = ["data_iniSE", "casos", "municipio_geocodigo"]
OPCIONAIS = ["casos_est", "casos_est_min", "casos_est_max", "casprov", "pop", "Rt", "nivel",
             "p_inc100k", "tempmed", "umidmed"]


def baixar_infodengue(
    geocodes: Iterable[int],
    inicio: str,
    fim: str,
    doenca: str,
    api_key: str,
    cliente: Any = None,
    pasta_cache: Path | None = None,
    falhas: list | None = None,
    **opcoes_api,
) -> pd.DataFrame:
    """Baixa a série semanal de cada município, ano a ano, com cache e novas tentativas.

    `cliente` permite injetar um substituto do mosqlient em testes. Se `falhas` for uma lista,
    os pedaços que falharam são acrescentados a ela e o resultado parcial é devolvido; se for
    None, qualquer falha levanta RuntimeError.
    """
    if cliente is None:
        import mosqlient as cliente  # importação tardia: só é necessário com acesso à API

    def buscar(g: int, a: str, b: str):
        return cliente.get_infodengue(api_key=api_key, disease=doenca, start_date=a, end_date=b, geocode=g)

    # Uma semana de sobreposição entre os pedaços evita perder a semana da virada do ano,
    # qualquer que seja o critério de data da API; as duplicatas saem na padronização.
    opcoes_api.setdefault("sobreposicao_dias", 7)
    partes, f = coletar(geocodes, inicio, fim, buscar, rotulo="InfoDengue",
                        pasta_cache=pasta_cache, **opcoes_api)
    if f and falhas is None:
        raise RuntimeError(_resumo_falhas(f))
    if falhas is not None:
        falhas.extend(f)
    if not partes:
        raise RuntimeError("A API do InfoDengue não retornou dados para nenhum município.")
    return padronizar_infodengue(pd.concat(partes, ignore_index=True))


def _resumo_falhas(falhas: list[dict]) -> str:
    linhas = [f"  - {x['fonte']} {x['geocode']} {x['inicio']}..{x['fim']}: {x['erro']}" for x in falhas[:10]]
    extra = f"\n  ... e mais {len(falhas) - 10}" if len(falhas) > 10 else ""
    return (f"{len(falhas)} pedaço(s) falharam:\n" + "\n".join(linhas) + extra +
            "\nOs pedaços já baixados ficaram em cache: rode o comando de novo para retomar.")


def padronizar_infodengue(bruto: pd.DataFrame) -> pd.DataFrame:
    """Converte o formato do InfoDengue no formato interno: uma linha por município e semana."""
    faltando = [c for c in OBRIGATORIAS if c not in bruto.columns]
    if faltando:
        raise ValueError(
            f"Colunas obrigatórias ausentes no InfoDengue: {faltando}. "
            f"Colunas recebidas: {sorted(bruto.columns)}"
        )
    semanas, ajustadas = domingo_mais_proximo(para_data(bruto["data_iniSE"]))
    if ajustadas:
        log.warning("InfoDengue: %d datas de início de semana não caíam no domingo e foram ajustadas", ajustadas)
    df = pd.DataFrame(
        {
            "geocode": pd.to_numeric(bruto["municipio_geocodigo"]).astype(int).to_numpy(),
            "inicio_semana": semanas.to_numpy(),
        }
    )
    for c in ["casos"] + OPCIONAIS:
        if c in bruto.columns:
            df[c] = pd.to_numeric(bruto[c], errors="coerce").to_numpy()
    if "pop" in df.columns:
        df.loc[df["pop"] <= 0, "pop"] = float("nan")

    # A mesma semana pode vir mais de uma vez (versões do modelo, sobreposição entre pedaços).
    # Fica a versão mais recente; sem essa coluna, a que chegou por último (ordenação estável).
    ordem = ["geocode", "inicio_semana"]
    if "versao_modelo" in bruto.columns:
        df["_versao"] = pd.to_datetime(bruto["versao_modelo"], errors="coerce").to_numpy()
        ordem.append("_versao")
    df = (
        df.sort_values(ordem, kind="stable", na_position="first")
        .drop_duplicates(["geocode", "inicio_semana"], keep="last")
        .drop(columns="_versao", errors="ignore")
        .reset_index(drop=True)
    )
    return df


def lacunas(df: pd.DataFrame) -> pd.DataFrame:
    """Semanas faltantes no meio da série de cada município (entre a primeira e a última)."""
    linhas = []
    for g, d in df.groupby("geocode"):
        esperado = pd.date_range(d["inicio_semana"].min(), d["inicio_semana"].max(), freq="7D")
        faltam = esperado.difference(pd.DatetimeIndex(d["inicio_semana"]))
        linhas.append({"geocode": int(g), "primeira": d["inicio_semana"].min(),
                       "ultima": d["inicio_semana"].max(), "semanas": len(d), "faltando": len(faltam)})
    return pd.DataFrame(linhas)
