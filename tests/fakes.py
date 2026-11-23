"""Substituto do mosqlient para testes: serve dados sintéticos no formato bruto da API."""

from __future__ import annotations

import numpy as np
import pandas as pd

from dengue_df.ingest import sintetico


class MosqlimateFalso:
    """Imita mosqlient.get_infodengue / get_climate, filtrando pelo período pedido.

    `falhar(tipo, geocode, inicio, fim)` pode levantar uma exceção para simular erros da API.
    """

    __version__ = "falso"

    def __init__(self, municipios, inicio="2017-01-01", fim="2025-10-31", falhar=None, sem=()):
        _, info, clima = sintetico.gerar(municipios, inicio=inicio, fim=fim, semanas_nowcast=3)
        self.info = pd.DataFrame({
            "data_iniSE": info["inicio_semana"].dt.strftime("%Y-%m-%d"),
            "SE": info["inicio_semana"].dt.strftime("%Y%U").astype(int),
            "casos": info["casos"], "casos_est": info["casos_est"],
            "casos_est_min": info["casos_est_min"], "casos_est_max": info["casos_est_max"],
            "municipio_geocodigo": info["geocode"], "pop": info["pop"].astype(float),
            "Rt": 1.0, "nivel": 1, "versao_modelo": "2025-11-01",
        }).drop(columns=list(sem))
        # Clima semanal sintético -> diário (chuva dividida pelos 7 dias).
        dias = clima.loc[clima.index.repeat(7)].copy()
        dias["date"] = dias["inicio_semana"] + pd.to_timedelta(np.tile(np.arange(7), len(clima)), unit="D")
        self.clima = pd.DataFrame({
            "date": dias["date"].dt.strftime("%Y-%m-%d"), "geocodigo": dias["geocode"], "epiweek": 0,
            "temp_min": dias["temp_med"] - 5, "temp_med": dias["temp_med"], "temp_max": dias["temp_med"] + 6,
            "precip_tot": dias["precip_tot"] / 7, "umid_med": dias["umid_med"],
        }).reset_index(drop=True)
        self.falhar = falhar or (lambda *a: None)
        self.chamadas: list[tuple] = []

    @staticmethod
    def _filtrar(df, col_geo, col_data, geocode, a, b):
        d = pd.to_datetime(df[col_data])
        return df[(df[col_geo] == geocode) & (d >= a) & (d <= b)].reset_index(drop=True)

    def get_infodengue(self, api_key, disease, start_date, end_date, geocode):
        self.chamadas.append(("info", geocode, start_date, end_date))
        self.falhar("info", geocode, start_date, end_date)
        return self._filtrar(self.info, "municipio_geocodigo", "data_iniSE", geocode, start_date, end_date)

    def get_climate(self, api_key, start_date, end_date, geocode):
        self.chamadas.append(("clima", geocode, start_date, end_date))
        self.falhar("clima", geocode, start_date, end_date)
        return self._filtrar(self.clima, "geocodigo", "date", geocode, start_date, end_date)
