"""Gerador de DADOS SINTÉTICOS para testes e demonstração do pipeline.

Os números produzidos aqui não representam a dengue real no DF nem em nenhum município.
Servem só para rodar o pipeline e o painel sem acesso à API. O painel exibe um aviso
sempre que a fonte é sintética.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from dengue_df.epiweek import inicio_semana, semana_epidemiologica, temporada

GEOCODE_FICTICIO_BASE = 9_900_000  # códigos fora da faixa do IBGE, para não confundir com reais


def gerar(
    municipios: list[dict],
    inicio: str = "2012-01-01",
    fim: str = "2026-10-31",
    semanas_nowcast: int = 3,
    semente: int = 42,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Retorna (municipios, infodengue_padronizado, clima_semanal), todos sintéticos."""
    rng = np.random.default_rng(semente)
    semanas = pd.date_range(inicio_semana([inicio]).iloc[0], inicio_semana([fim]).iloc[0], freq="7D")
    se = semana_epidemiologica(semanas)
    temp = temporada(se["ano_se"], se["se"]).to_numpy()
    se_num = se["se"].to_numpy()

    # Clima regional comum (com ruído local depois): chuva concentrada de outubro a abril.
    fase = 2 * np.pi * (se_num - 3) / 52
    chuva_base = 70 * np.clip(0.5 + 0.5 * np.cos(fase), 0, None) ** 1.5
    chuva_reg = chuva_base * rng.lognormal(0, 0.5, len(semanas))
    temp_reg = 22 + 2.5 * np.cos(2 * np.pi * (se_num - 42) / 52) + rng.normal(0, 0.7, len(semanas))

    # Amplitude de cada temporada cresce com a chuva acumulada no início da estação (SE 41 a 5).
    temporadas = np.unique(temp)
    inicio_estacao = (se_num >= 41) | (se_num <= 5)
    chuva_temp = pd.Series(chuva_reg * inicio_estacao).groupby(temp).sum()
    z = (chuva_temp - chuva_temp.mean()) / chuva_temp.std()
    log_amp = 4.0 + 0.8 * z.reindex(temporadas).fillna(0).to_numpy() + rng.normal(0, 0.6, len(temporadas))
    amp = dict(zip(temporadas, np.exp(log_amp)))
    atraso_pico = dict(zip(temporadas, rng.normal(0, 2, len(temporadas))))

    mun_linhas, info_linhas, clima_linhas = [], [], []
    for i, m in enumerate(municipios):
        geocode = int(m.get("geocode") or GEOCODE_FICTICIO_BASE + i)
        pop = 2_900_000 if m.get("uf") == "DF" else int(rng.integers(40_000, 220_000))
        mult = rng.lognormal(0, 0.4)
        defasagem = rng.normal(0, 1.5)
        mun_linhas.append({"geocode": geocode, "nome": m["nome"], "uf": m["uf"]})

        semanas_desde_41 = (se_num - 41) % 52
        pico = 22 + np.array([atraso_pico[t] for t in temp]) + defasagem
        forma = np.exp(-0.5 * ((semanas_desde_41 - pico) / 5.0) ** 2)
        inc = 2 + mult * np.array([amp[t] for t in temp]) * forma  # por 100 mil hab.
        media = inc * pop / 1e5
        reais = rng.negative_binomial(10, 10 / (10 + media))

        casos = reais.astype(float).copy()
        casos_est = reais.astype(float).copy()
        if semanas_nowcast > 0:
            completude = np.linspace(0.45, 0.9, semanas_nowcast)
            casos[-semanas_nowcast:] = np.round(reais[-semanas_nowcast:] * completude)
            casos_est[-semanas_nowcast:] = np.round(reais[-semanas_nowcast:] * rng.normal(1, 0.08, semanas_nowcast))
        info_linhas.append(
            pd.DataFrame(
                {
                    "geocode": geocode,
                    "inicio_semana": semanas,
                    "casos": casos,
                    "casos_est": casos_est,
                    "casos_est_min": np.floor(casos_est * 0.85),
                    "casos_est_max": np.ceil(casos_est * 1.15),
                    "pop": pop,
                }
            )
        )
        clima_linhas.append(
            pd.DataFrame(
                {
                    "geocode": geocode,
                    "inicio_semana": semanas,
                    "temp_med": temp_reg + rng.normal(0, 0.4, len(semanas)),
                    "precip_tot": np.clip(chuva_reg * rng.lognormal(0, 0.2, len(semanas)), 0, None),
                    "umid_med": np.clip(40 + 0.45 * chuva_reg + rng.normal(0, 4, len(semanas)), 15, 98),
                }
            )
        )

    return (
        pd.DataFrame(mun_linhas),
        pd.concat(info_linhas, ignore_index=True),
        pd.concat(clima_linhas, ignore_index=True),
    )
