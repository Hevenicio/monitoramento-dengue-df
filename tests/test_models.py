import numpy as np
import pytest

from dengue_df.models import criar_modelo
from tests.conftest import HORIZONTES, QUANTIS


@pytest.mark.parametrize("nome", ["climatologia", "crescimento", "gbm_quantilico"])
def test_modelos_produzem_quantis_validos(nome, tabela, corte, origens):
    m = criar_modelo(nome, horizontes=HORIZONTES, quantis=QUANTIS, janela_sazonal=3, lags=8,
                     com_clima=True, max_iter=50)
    prev = m.ajustar(tabela, corte).prever(origens)
    assert set(prev["horizonte"]) == set(HORIZONTES)
    assert (prev["valor"] >= 0).all()
    for _, d in prev.groupby(["geocode", "origem", "horizonte"]):
        assert len(d) == len(QUANTIS)
        assert np.all(np.diff(d.sort_values("quantil")["valor"].to_numpy()) >= -1e-9)


def test_treino_respeita_corte(tabela, corte):
    h = max(HORIZONTES)
    tr = criar_modelo("climatologia", horizontes=[h], quantis=QUANTIS).treino_para_h(tabela, h, corte)
    assert len(tr) and (tr[f"semana_alvo_h{h}"] < corte).all()


def test_modelo_desconhecido():
    with pytest.raises(ValueError):
        criar_modelo("prophet", horizontes=[1], quantis=QUANTIS)
