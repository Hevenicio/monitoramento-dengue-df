import numpy as np
import pandas as pd

from dengue_df.evaluation.metrics import avaliar, pares_intervalo, wis
from dengue_df.risk import prob_exceder
from tests.conftest import QUANTIS


def test_pares_intervalo():
    niveis = sorted(round(1 - a, 2) for a, _, _ in pares_intervalo(QUANTIS))
    assert niveis == [0.5, 0.8, 0.9, 0.95]


def test_wis_previsao_pontual_perfeita_e_zero():
    Q = np.full((1, len(QUANTIS)), 10.0)
    assert wis(np.array([10.0]), Q, QUANTIS)[0] == 0


def test_wis_previsao_pontual_e_erro_absoluto():
    # Todos os quantis iguais a m: WIS = |y - m| (Bracher et al. 2021).
    Q = np.full((1, len(QUANTIS)), 10.0)
    assert np.isclose(wis(np.array([14.0]), Q, QUANTIS)[0], 4.0)


def test_wis_penaliza_intervalo_que_nao_cobre():
    largo = np.array([[1, 2, 3, 5, 10, 15, 17, 18, 19]], dtype=float)
    assert wis(np.array([10.0]), largo, QUANTIS)[0] < wis(np.array([40.0]), largo, QUANTIS)[0]


def test_avaliar_cobertura():
    prev = pd.DataFrame({
        "modelo": "m", "geocode": 1, "origem": pd.Timestamp("2024-01-07"), "horizonte": 1,
        "semana_alvo": pd.Timestamp("2024-01-14"), "quantil": QUANTIS,
        "valor": [1, 2, 3, 5, 10, 15, 17, 18, 19],
    })
    obs = pd.DataFrame({"geocode": [1], "inicio_semana": [pd.Timestamp("2024-01-14")], "y": [16.0]})
    a = avaliar(prev, obs).iloc[0]
    assert not a["cobre_50"] and a["cobre_80"] and a["cobre_90"] and a["cobre_95"]


def test_prob_exceder_monotona_e_limitada():
    v = np.array([1, 2, 3, 5, 10, 15, 17, 18, 19], dtype=float)
    q = np.array(QUANTIS)
    probs = [prob_exceder(v, q, lim) for lim in [0, 1, 5, 10, 18, 19, 50, 1000]]
    assert all(0 <= p <= 1 for p in probs)
    assert all(a >= b for a, b in zip(probs, probs[1:]))
    assert np.isclose(prob_exceder(v, q, 10), 0.5)
