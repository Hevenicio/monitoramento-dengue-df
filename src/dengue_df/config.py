"""Leitura da configuração (config/settings.yaml) e da chave da API."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml

RAIZ = Path(__file__).resolve().parents[2]
CONFIG_PADRAO = RAIZ / "config" / "settings.yaml"


@dataclass
class Config:
    doenca: str
    inicio: str
    fim: str
    alvo: str
    semanas_nowcast: int
    municipios: list[dict[str, Any]]
    usar_clima: bool
    horizontes: list[int]
    quantis: list[float]
    lags: int
    janela_sazonal: int
    modelos: list[str]
    inicio_temporada_se: int
    temporadas_teste: int
    percentil_limiar: float
    dir_dados: Path
    dir_saidas: Path
    bruto: dict[str, Any] = field(default_factory=dict, repr=False)
    usar_cache: bool = True
    semanas_revisao: int = 12
    api_tentativas: int = 4
    api_espera: float = 2.0
    api_pausa: float = 0.2

    def opcoes_api(self) -> dict[str, Any]:
        return dict(semanas_revisao=self.semanas_revisao, tentativas=self.api_tentativas,
                    espera=self.api_espera, pausa=self.api_pausa)

    @property
    def dir_raw(self) -> Path:
        return self.dir_dados / "raw"

    @property
    def dir_processed(self) -> Path:
        return self.dir_dados / "processed"

    @property
    def dir_ref(self) -> Path:
        return self.dir_dados / "ref"

    def criar_diretorios(self) -> None:
        for d in (self.dir_raw, self.dir_processed, self.dir_ref, self.dir_saidas):
            d.mkdir(parents=True, exist_ok=True)


def _validar_quantis(quantis: list[float]) -> list[float]:
    q = sorted(float(x) for x in quantis)
    if 0.5 not in q:
        raise ValueError("A lista de quantis precisa incluir a mediana (0.5).")
    for x in q:
        if x < 0.5 and round(1 - x, 6) not in [round(v, 6) for v in q]:
            raise ValueError(
                f"Quantil {x} sem o par simétrico {1 - x:.3f}; os intervalos precisam ser simétricos."
            )
    return q


def carregar_config(caminho: str | Path | None = None) -> Config:
    caminho = Path(caminho) if caminho else CONFIG_PADRAO
    with open(caminho, encoding="utf-8") as f:
        c = yaml.safe_load(f)

    base = caminho.resolve().parents[1] if caminho.parent.name == "config" else RAIZ
    dados, terr, mod = c["dados"], c["territorio"], c["modelo"]
    api = c.get("api", {}) or {}
    return Config(
        doenca=dados.get("doenca", "dengue"),
        inicio=str(dados.get("inicio", "2012-01-01")),
        fim=str(dados.get("fim") or date.today().isoformat()),
        alvo=dados.get("alvo", "casos"),
        semanas_nowcast=int(dados.get("semanas_nowcast", 3)),
        municipios=list(terr["municipios"]),
        usar_clima=bool(c.get("clima", {}).get("usar", True)),
        horizontes=[int(h) for h in mod["horizontes"]],
        quantis=_validar_quantis(mod["quantis"]),
        lags=int(mod.get("lags", 8)),
        janela_sazonal=int(mod.get("janela_sazonal", 3)),
        modelos=list(mod.get("modelos", ["climatologia", "crescimento", "gbm_quantilico"])),
        inicio_temporada_se=int(c.get("temporada", {}).get("inicio_se", 41)),
        temporadas_teste=int(c.get("backtest", {}).get("temporadas_teste", 3)),
        percentil_limiar=float(c.get("risco", {}).get("percentil_limiar", 0.9)),
        dir_dados=base / c.get("caminhos", {}).get("dados", "data"),
        dir_saidas=base / c.get("caminhos", {}).get("saidas", "outputs"),
        bruto=c,
        usar_cache=bool(api.get("cache", True)),
        semanas_revisao=int(api.get("semanas_revisao", 12)),
        api_tentativas=int(api.get("tentativas", 4)),
        api_espera=float(api.get("espera_segundos", 2.0)),
        api_pausa=float(api.get("pausa_segundos", 0.2)),
    )


def chave_api() -> str:
    """Lê MOSQLIMATE_API_KEY do ambiente ou do arquivo .env na raiz do projeto."""
    try:
        from dotenv import load_dotenv

        load_dotenv(RAIZ / ".env")
    except ImportError:  # python-dotenv é opcional
        pass
    chave = os.getenv("MOSQLIMATE_API_KEY", "").strip()
    if not chave or chave == "coloque-sua-chave-aqui":
        raise RuntimeError(
            "Defina MOSQLIMATE_API_KEY no ambiente ou no arquivo .env "
            "(copie .env.example para .env e cole sua chave)."
        )
    return chave
