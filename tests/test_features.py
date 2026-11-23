import numpy as np
import pandas as pd

from dengue_df.features import colunas_preditoras, montar_tabela


def test_painel_grade_semanal_completa(painel):
    for _, d in painel.groupby("geocode"):
        assert d["inicio_semana"].diff().dropna().eq(pd.Timedelta(weeks=1)).all()


def test_nowcast_nas_ultimas_semanas(painel):
    d = painel[painel["geocode"] == 5300108]
    assert d["nowcast"].tail(3).all() and not d["nowcast"].iloc[:-3].any()
    assert (d["y"].tail(3) == d["casos_est"].tail(3)).all()


def test_sem_vazamento_do_futuro(painel):
    """Mudar o futuro não pode mudar as preditoras de uma origem no passado."""
    t1 = montar_tabela(painel, 8, [1])
    alterado = painel.copy()
    origem = alterado["inicio_semana"].sort_values().unique()[300]
    alterado.loc[alterado["inicio_semana"] > origem, ["y", "temp_med", "precip_tot", "umid_med"]] *= 7
    t2 = montar_tabela(alterado, 8, [1])
    cols = [c for c in colunas_preditoras(8, True) if c != "municipio"]
    a = t1.loc[t1["inicio_semana"] <= origem, cols].to_numpy(dtype=float)
    b = t2.loc[t2["inicio_semana"] <= origem, cols].to_numpy(dtype=float)
    assert np.allclose(a, b, equal_nan=True)


def test_alvo_e_semana_seguinte(tabela):
    d = tabela[tabela["geocode"] == 5300108].reset_index(drop=True)
    assert np.isclose(d.loc[10, "alvo_h1"], d.loc[11, "ly"])
    assert d.loc[10, "semana_alvo_h1"] == d.loc[11, "inicio_semana"]
