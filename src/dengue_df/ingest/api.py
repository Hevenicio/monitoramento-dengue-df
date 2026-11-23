"""Chamadas robustas à API do Mosqlimate.

- Download em pedaços (município × ano), cada um gravado em cache bruto em data/raw/.
  Se a ingestão cair no meio, rodar de novo retoma de onde parou.
- Pedaços que terminam nas últimas `semanas_revisao` semanas são sempre baixados de novo,
  porque o InfoDengue revisa as semanas recentes à medida que chegam notificações atrasadas.
- Erros temporários (rede, HTTP 5xx, limite de requisições) ganham novas tentativas com espera
  crescente. Erros definitivos (chave inválida, assinatura da função mudou) interrompem tudo.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable, Iterable

import pandas as pd

log = logging.getLogger(__name__)

_SINAIS_DEFINITIVOS = ("401", "403", "unauthor", "forbidden", "invalid api", "api key", "api_key")


class ErroDefinitivo(RuntimeError):
    """Erro que não adianta repetir (ex.: chave da API inválida)."""


def _eh_definitivo(e: Exception) -> bool:
    if isinstance(e, (TypeError, ErroDefinitivo)):
        return True  # TypeError: argumentos não aceitos, a assinatura da função mudou
    msg = str(e).lower()
    return any(s in msg for s in _SINAIS_DEFINITIVOS)


def com_tentativas(
    fn: Callable[[], pd.DataFrame | None],
    descricao: str,
    tentativas: int = 4,
    espera: float = 2.0,
    dormir: Callable[[float], None] = time.sleep,
) -> pd.DataFrame | None:
    """Executa `fn` com até `tentativas` chamadas, esperando espera, 2·espera, 4·espera... entre elas."""
    ultimo: Exception | None = None
    for i in range(tentativas):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - a API pode levantar vários tipos de erro
            if _eh_definitivo(e):
                raise ErroDefinitivo(f"{descricao}: {type(e).__name__}: {e}") from e
            ultimo = e
            if i < tentativas - 1:
                t = espera * 2**i
                log.warning("%s: falhou (%s: %s). Nova tentativa em %.0f s (%d/%d)",
                            descricao, type(e).__name__, e, t, i + 2, tentativas)
                dormir(t)
    raise RuntimeError(
        f"{descricao}: falhou após {tentativas} tentativas ({type(ultimo).__name__}: {ultimo})"
    ) from ultimo


def pedacos_anuais(inicio: str, fim: str) -> list[tuple[str, str]]:
    """Divide [inicio, fim] em pedaços de no máximo um ano civil."""
    ini, f = pd.Timestamp(inicio), pd.Timestamp(fim)
    return [
        (max(ini, pd.Timestamp(f"{a}-01-01")).date().isoformat(),
         min(f, pd.Timestamp(f"{a}-12-31")).date().isoformat())
        for a in range(ini.year, f.year + 1)
    ]


# ---------------------------------------------------------------- cache bruto
def _arquivos(base: Path) -> tuple[Path, Path]:
    return Path(f"{base}.csv.gz"), Path(f"{base}.vazio")


def _ler_cache(base: Path) -> pd.DataFrame | None:
    csv, vazio = _arquivos(base)
    if vazio.exists():
        return pd.DataFrame()
    if csv.exists():
        try:
            return pd.read_csv(csv)
        except Exception as e:  # noqa: BLE001 - arquivo truncado por interrupção: baixa de novo
            log.warning("Cache ilegível (%s), baixando de novo: %s", e, csv)
    return None


def _gravar_cache(base: Path, df: pd.DataFrame | None) -> None:
    base.parent.mkdir(parents=True, exist_ok=True)
    csv, vazio = _arquivos(base)
    # Versões antigas do mesmo pedaço com outra data final (ex.: o ano corrente) saem do cache.
    geocode, inicio = base.name.split("_")[:2]
    for antigo in base.parent.glob(f"{geocode}_{inicio}_*"):
        antigo.unlink(missing_ok=True)
    if df is None or df.empty:
        vazio.touch()
        return
    # CSV em vez de Parquet: a resposta bruta pode ter colunas de tipos mistos.
    tmp = Path(f"{base}.tmp.gz")
    df.to_csv(tmp, index=False, compression="gzip")
    tmp.replace(csv)  # grava inteiro ou nada


def coletar(
    geocodes: Iterable[int],
    inicio: str,
    fim: str,
    buscar: Callable[[int, str, str], pd.DataFrame | None],
    *,
    rotulo: str,
    pasta_cache: Path | None = None,
    semanas_revisao: int = 12,
    sobreposicao_dias: int = 0,
    tentativas: int = 4,
    espera: float = 2.0,
    pausa: float = 0.0,
    refazer: bool = False,
    dormir: Callable[[float], None] = time.sleep,
) -> tuple[list[pd.DataFrame], list[dict]]:
    """Baixa (ou lê do cache) cada pedaço município × ano.

    `buscar(geocode, inicio, fim)` faz uma chamada à API. Devolve (pedaços com dados, falhas).
    Falhas temporárias que persistem são registradas e o download continua; erros definitivos
    interrompem tudo. `refazer=True` ignora o cache existente (mas grava o novo).
    """
    ini_total, fim_total = pd.Timestamp(inicio), pd.Timestamp(fim)
    recente_desde = fim_total - pd.Timedelta(weeks=semanas_revisao)
    folga = pd.Timedelta(days=sobreposicao_dias)
    partes: list[pd.DataFrame] = []
    falhas: list[dict] = []
    n_cache = n_api = 0

    for g in geocodes:
        g = int(g)
        for a, b in pedacos_anuais(inicio, fim):
            desc = f"{rotulo} {g} {a}..{b}"
            base = pasta_cache / f"{g}_{a}_{b}" if pasta_cache is not None else None
            if base is not None and not refazer and pd.Timestamp(b) < recente_desde:
                df = _ler_cache(base)
                if df is not None:
                    n_cache += 1
                    if len(df):
                        partes.append(df)
                    continue
            a_req = max(ini_total, pd.Timestamp(a) - folga).date().isoformat()
            b_req = min(fim_total, pd.Timestamp(b) + folga).date().isoformat()
            log.info("%s: baixando", desc)
            try:
                df = com_tentativas(lambda: buscar(g, a_req, b_req), desc, tentativas, espera, dormir)
            except ErroDefinitivo:
                raise
            except Exception as e:  # noqa: BLE001
                log.warning("%s: desistindo deste pedaço (%s)", desc, e)
                falhas.append({"fonte": rotulo, "geocode": g, "inicio": a, "fim": b, "erro": str(e)})
                continue
            n_api += 1
            if base is not None:
                _gravar_cache(base, df)
            if df is not None and len(df):
                partes.append(df)
            if pausa:
                dormir(pausa)

    log.info("%s: %d pedaços da API, %d do cache, %d falhas", rotulo, n_api, n_cache, len(falhas))
    return partes, falhas


# ---------------------------------------------------------------- datas
def para_data(serie: pd.Series) -> pd.Series:
    """Converte datas da API (texto ISO, com ou sem fuso, ou epoch em ms) em datas sem hora."""
    if pd.api.types.is_numeric_dtype(serie):
        d = pd.to_datetime(serie, unit="ms")
    else:
        d = pd.to_datetime(serie, utc=False, format="mixed")
    if getattr(d.dt, "tz", None) is not None:
        d = d.dt.tz_convert("America/Sao_Paulo").dt.tz_localize(None)
    return d.dt.normalize()


def domingo_mais_proximo(datas: pd.Series) -> tuple[pd.Series, int]:
    """Ajusta cada data ao domingo mais próximo. Devolve (datas ajustadas, quantas mudaram)."""
    desloc = (6 - datas.dt.dayofweek) % 7  # dias até o próximo domingo (0 se já é domingo)
    desloc = desloc.where(desloc <= 3, desloc - 7)
    return datas + pd.to_timedelta(desloc, unit="D"), int((desloc != 0).sum())
