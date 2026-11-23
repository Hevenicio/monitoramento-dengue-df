"""Painel de risco de dengue — DF e Entorno.

Rodar a partir da raiz do projeto:
    streamlit run app/painel.py
Antes, gere as tabelas com `python -m dengue_df demo` (sintético) ou `ingerir` + `executar` (real).
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

import graficos  # noqa: E402
from dengue_df import storage  # noqa: E402
from dengue_df.config import carregar_config  # noqa: E402
from dengue_df.epiweek import rotulo_temporada  # noqa: E402
from dengue_df.painel_dados import (  # noqa: E402
    faixas,
    opcoes_temporada,
    ranking_risco,
    resumo_legivel,
    serie_observada,
)

NOMES_MODELO = {
    "gbm_quantilico": "Gradient boosting quantílico",
    "crescimento": "Crescimento sazonal (baseline)",
    "climatologia": "Climatologia (baseline)",
}
TABELAS = ["painel", "previsao", "risco", "limiares", "backtest_previsoes", "backtest_resumo",
           "cobertura", "confiabilidade"]

st.set_page_config(page_title="Dengue DF e Entorno", layout="wide")


def mostrar_grafico(fig) -> None:
    try:
        st.plotly_chart(fig, width="stretch", theme="streamlit")
    except Exception:  # versões antigas do Streamlit
        st.plotly_chart(fig, use_container_width=True, theme="streamlit")


def mostrar_tabela(df: pd.DataFrame, **kw) -> None:
    try:
        st.dataframe(df, width="stretch", hide_index=True, **kw)
    except Exception:
        st.dataframe(df, use_container_width=True, hide_index=True, **kw)


def arredondar(df: pd.DataFrame, casas: int) -> pd.DataFrame:
    """Arredonda só as colunas numéricas e mostra datas sem horário."""
    df = df.copy()
    for c in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            df[c] = df[c].dt.date
        elif pd.api.types.is_float_dtype(df[c]):
            df[c] = df[c].round(casas)
    return df


@st.cache_data(show_spinner=False)
def carregar(dir_saidas: str, versao: float) -> tuple[dict[str, pd.DataFrame], dict]:
    """`versao` (data de modificação do metadata.json) entra na chave do cache: quando
    `executar` grava novas saídas, o painel recarrega em vez de mostrar dados antigos."""
    d = Path(dir_saidas)
    tabelas = {n: storage.ler(d / n, colunas_data=("inicio_semana", "semana_alvo", "origem"))
               for n in TABELAS}
    return tabelas, storage.ler_metadados(d / "metadata.json")


cfg = carregar_config()
if not storage.existe(cfg.dir_saidas / "risco"):
    st.title("Painel de risco de dengue — DF e Entorno")
    st.info("Ainda não há resultados. Rode `python -m dengue_df demo` (dados sintéticos) "
            "ou `python -m dengue_df ingerir` seguido de `python -m dengue_df executar`.")
    st.stop()

arquivo_meta = cfg.dir_saidas / "metadata.json"
T, meta = carregar(str(cfg.dir_saidas), arquivo_meta.stat().st_mtime if arquivo_meta.exists() else 0.0)
painel, previsao, risco, lim = T["painel"], T["previsao"], T["risco"], T["limiares"]

st.title("Painel de risco de dengue — DF e Entorno")
if meta.get("fonte") == "sintetico":
    st.warning("**Dados sintéticos.** Estes números foram gerados para testar o pipeline e não "
               "representam a dengue real em nenhum município.")
st.caption(f"Última semana com dados: {meta.get('ultima_semana', '?')} · Fonte: {meta.get('fonte', '?')} · "
           f"Limiar de alerta: percentil {int(meta.get('percentil_limiar', 0.9) * 100)} da incidência semanal histórica")

# ---------------------------------------------------------------- filtros (uma linha, acima dos gráficos)
modelos = [m for m in NOMES_MODELO if m in set(previsao["modelo"])]
nomes = painel.drop_duplicates("geocode").set_index("geocode")["nome"].to_dict()
c1, c2, c3 = st.columns([2, 2, 1])
modelo = c1.selectbox("Modelo", modelos, format_func=lambda m: NOMES_MODELO.get(m, m))
geocode = c2.selectbox("Município", list(nomes), format_func=lambda g: nomes.get(g, str(g)))
horizonte = c3.selectbox("Horizonte", sorted(previsao["horizonte"].unique()),
                         format_func=lambda h: f"{h} semana(s)")

limiar = lim.set_index("geocode")["limiar_casos"].get(geocode)
r_mun = risco[(risco["geocode"] == geocode) & (risco["modelo"] == modelo)].sort_values("horizonte")
r_h = r_mun[r_mun["horizonte"] == horizonte]
obs = serie_observada(painel, geocode, 104)

k1, k2, k3, k4 = st.columns(4)
k1.metric("Casos na última semana", f"{obs['y'].iloc[-1]:,.0f}".replace(",", "."),
          help="Nas semanas mais recentes o valor é a estimativa de nowcasting do InfoDengue.")
if len(r_h):
    k2.metric(f"Mediana prevista (+{horizonte} sem.)", f"{r_h['mediana'].iloc[0]:,.0f}".replace(",", "."))
    k3.metric("Intervalo de 90%", f"{r_h['li_90'].iloc[0]:,.0f} – {r_h['ls_90'].iloc[0]:,.0f}".replace(",", "."))
    k4.metric("Probabilidade de alerta", f"{r_h['prob_alerta'].iloc[0]:.0%}")

aba_prev, aba_terr, aba_bt, aba_sobre = st.tabs(["Previsão", "Território", "Desempenho (backtest)", "Sobre"])

with aba_prev:
    mostrar_grafico(graficos.fan_chart(obs, faixas(previsao, geocode, modelo), limiar))
    tab = r_mun[["horizonte", "semana_alvo", "mediana", "li_90", "ls_90", "prob_alerta"]].rename(columns={
        "horizonte": "Horizonte", "semana_alvo": "Semana", "mediana": "Mediana",
        "li_90": "IC 90% inf.", "ls_90": "IC 90% sup.", "prob_alerta": "Prob. de alerta"})
    mostrar_tabela(arredondar(tab, 0).assign(**{"Prob. de alerta": r_mun["prob_alerta"].map("{:.0%}".format).values}))

with aba_terr:
    rk = ranking_risco(risco, modelo, horizonte)
    st.subheader(f"Probabilidade de ultrapassar o limiar em {horizonte} semana(s)")
    mostrar_grafico(graficos.barras_risco(rk))
    mostrar_tabela(arredondar(rk.rename(columns={"nome": "Município", "semana_alvo": "Semana", "mediana": "Mediana",
                                                 "li_90": "IC 90% inf.", "ls_90": "IC 90% sup.",
                                                 "limiar_casos": "Limiar (casos)", "prob_alerta": "Prob. de alerta"}), 2))

with aba_bt:
    bt = T["backtest_previsoes"]
    temporadas = opcoes_temporada(bt)
    b1, b2 = st.columns(2)
    rot = b1.selectbox("Temporada de teste", list(temporadas)[::-1])
    h_bt = b2.selectbox("Horizonte do backtest", sorted(bt["horizonte"].unique()),
                        format_func=lambda h: f"{h} semana(s)", key="h_bt")
    temp = temporadas[rot]
    f_bt = faixas(bt, geocode, modelo, temporada_teste=temp, horizonte=h_bt)
    jan = painel[(painel["geocode"] == geocode) & (painel["temporada"] == temp)][["inicio_semana", "y", "nowcast"]]
    st.markdown(f"Previsões feitas **{h_bt} semana(s) antes**, temporada {rot}, sem usar dados do futuro.")
    if not f_bt.empty and len(jan):
        fig = graficos.fan_chart(jan.assign(nowcast=False), f_bt, limiar)
        mostrar_grafico(fig)
    g1, g2 = st.columns(2)
    with g1:
        st.markdown("**Cobertura dos intervalos**")
        mostrar_grafico(graficos.cobertura(T["cobertura"]))
    with g2:
        st.markdown("**Confiabilidade da probabilidade de alerta**")
        mostrar_grafico(graficos.confiabilidade(T["confiabilidade"]))
    st.markdown("**Resumo por modelo e horizonte** (menor WIS é melhor; WIS relativo < 1 supera a climatologia)")
    mostrar_tabela(resumo_legivel(T["backtest_resumo"]).round(3))

with aba_sobre:
    st.markdown(f"""
- **Dados:** InfoDengue via API do Mosqlimate (casos semanais por município e estimativa de nowcasting)
  e clima diário do Mosqlimate agregado por semana epidemiológica.
- **Modelos:** climatologia (distribuição histórica da mesma época), crescimento sazonal (nível atual ×
  crescimento típico da época) e gradient boosting quantílico com lags de casos, sazonalidade e clima.
- **Avaliação:** backtest por origem móvel nas temporadas {', '.join(rotulo_temporada(t) for t in meta.get('temporadas_teste', []))},
  com Weighted Interval Score (WIS), cobertura dos intervalos e Brier da probabilidade de alerta.
- **Limiar de alerta:** percentil {int(meta.get('percentil_limiar', 0.9) * 100)} da incidência semanal histórica de cada município.
- **Cuidados:** as últimas semanas usam nowcasting e mudam com novas notificações; o painel cobre só casos
  notificados ao SUS.
""")
