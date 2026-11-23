"""Leitura e gravação de tabelas: Parquet quando pyarrow está instalado, CSV comprimido caso contrário."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd


def _tem_parquet() -> bool:
    try:
        import pyarrow  # noqa: F401

        return True
    except ImportError:
        return False


def gravar(df: pd.DataFrame, caminho_sem_extensao: str | Path) -> Path:
    base = Path(caminho_sem_extensao)
    base.parent.mkdir(parents=True, exist_ok=True)
    for antigo in (base.with_suffix(".parquet"), Path(f"{base}.csv.gz")):
        antigo.unlink(missing_ok=True)
    if _tem_parquet():
        destino = base.with_suffix(".parquet")
        df.to_parquet(destino, index=False)
    else:
        destino = Path(f"{base}.csv.gz")
        df.to_csv(destino, index=False, compression="gzip")
    return destino


def ler(caminho_sem_extensao: str | Path, colunas_data: tuple[str, ...] = ()) -> pd.DataFrame:
    base = Path(caminho_sem_extensao)
    pq, csv = base.with_suffix(".parquet"), Path(f"{base}.csv.gz")
    if pq.exists():
        df = pd.read_parquet(pq)
    elif csv.exists():
        df = pd.read_csv(csv)
    else:
        raise FileNotFoundError(f"Tabela não encontrada: {pq} nem {csv}")
    for c in colunas_data:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c])
    return df


def remover(caminho_sem_extensao: str | Path) -> None:
    base = Path(caminho_sem_extensao)
    base.with_suffix(".parquet").unlink(missing_ok=True)
    Path(f"{base}.csv.gz").unlink(missing_ok=True)


def existe(caminho_sem_extensao: str | Path) -> bool:
    base = Path(caminho_sem_extensao)
    return base.with_suffix(".parquet").exists() or Path(f"{base}.csv.gz").exists()


def gravar_metadados(caminho: str | Path, **campos) -> None:
    campos.setdefault("gerado_em", datetime.now().isoformat(timespec="seconds"))
    Path(caminho).parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(campos, f, ensure_ascii=False, indent=2, default=str)


def ler_metadados(caminho: str | Path) -> dict:
    caminho = Path(caminho)
    if not caminho.exists():
        return {}
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)
