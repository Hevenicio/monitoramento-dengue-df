"""Resolve nomes de municípios em códigos IBGE de 7 dígitos (com cache local)."""

from __future__ import annotations

import difflib
import unicodedata
from pathlib import Path
from typing import Any, Callable

import pandas as pd

URL_IBGE = "https://servicodados.ibge.gov.br/api/v1/localidades/estados/{uf}/municipios"


def normalizar(nome: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    return " ".join(sem_acento.lower().replace("-", " ").split())


def _buscar_uf_ibge(uf: str) -> list[dict[str, Any]]:
    import requests

    resp = requests.get(URL_IBGE.format(uf=uf), timeout=30)
    resp.raise_for_status()
    return resp.json()


def resolver_municipios(
    municipios: list[dict[str, Any]],
    cache: str | Path,
    buscar_uf: Callable[[str], list[dict[str, Any]]] = _buscar_uf_ibge,
) -> pd.DataFrame:
    """Retorna DataFrame com geocode, nome e uf para cada município da configuração.

    Entradas com `geocode` explícito são usadas como estão. As demais são procuradas pelo nome
    na lista de municípios da UF (API do IBGE), com cache em `cache`.
    """
    cache = Path(cache)
    ref = pd.read_csv(cache) if cache.exists() else pd.DataFrame(columns=["geocode", "nome", "uf"])

    ufs_faltando = {
        m["uf"] for m in municipios if not m.get("geocode") and m["uf"] not in set(ref["uf"])
    }
    for uf in sorted(ufs_faltando):
        lista = buscar_uf(uf)
        novos = pd.DataFrame(
            {"geocode": [int(x["id"]) for x in lista], "nome": [x["nome"] for x in lista], "uf": uf}
        )
        ref = pd.concat([ref, novos], ignore_index=True)
    if ufs_faltando:
        cache.parent.mkdir(parents=True, exist_ok=True)
        ref.to_csv(cache, index=False)

    ref = ref.assign(_chave=ref["nome"].map(normalizar))
    linhas = []
    for m in municipios:
        if m.get("geocode"):
            linhas.append({"geocode": int(m["geocode"]), "nome": m["nome"], "uf": m["uf"]})
            continue
        candidatos = ref[ref["uf"] == m["uf"]]
        achado = candidatos[candidatos["_chave"] == normalizar(m["nome"])]
        if achado.empty:
            sugestoes = difflib.get_close_matches(
                normalizar(m["nome"]), candidatos["_chave"].tolist(), n=3
            )
            raise ValueError(
                f"Município '{m['nome']}' ({m['uf']}) não encontrado no IBGE. "
                f"Sugestões: {sugestoes or 'nenhuma'}. Corrija o nome ou informe o geocode."
            )
        r = achado.iloc[0]
        linhas.append({"geocode": int(r["geocode"]), "nome": r["nome"], "uf": m["uf"]})
    return pd.DataFrame(linhas).drop_duplicates("geocode").reset_index(drop=True)
