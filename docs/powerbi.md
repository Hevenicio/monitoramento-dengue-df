# Painel de dengue no Power BI

O Python continua sendo o motor (ingestão, modelos, backtest). O Power BI é a camada de
visualização: lê as tabelas que `exportar-powerbi` grava em `outputs/powerbi/`.

```
API Mosqlimate ──► ingerir ──► executar ──► exportar-powerbi ──► outputs/powerbi/*.parquet ──► Power BI
```

## Atalho: o painel pronto

`powerbi/painel_dengue.pbip` é o painel já montado, no formato de projeto do Power BI (modelo e
páginas salvos como texto, bom para versionar no Git):

- `painel_dengue.SemanticModel/`: modelo (11 tabelas, 11 relacionamentos, 71 medidas, 3 colunas
  calculadas, ordenações, formatos), com as consultas lendo os Parquet de `outputs/powerbi/`.
- `painel_dengue.Report/`: 4 páginas (visão geral, previsão por município com faixas de 50% e
  90%, desempenho e calibração do backtest, metodologia) e o tema do projeto.

Para usar:

1. `python -m dengue_df exportar-powerbi` (opcional: o repositório já traz as tabelas da última
   rodada em `outputs/powerbi/`).
2. Abra `powerbi/painel_dengue.pbip` no Power BI Desktop e clique em **Atualizar**.
3. O parâmetro `PastaDados` vem apontando para `C:\monitoramento-dengue-df\outputs\powerbi\`. Se
   o projeto estiver em outra pasta ou outra máquina, corrija o caminho em **Transformar dados
   > Gerenciar parâmetros > PastaDados** (o caminho termina em `\`).

### Padrões visuais do painel pronto

- **Grade**: página 1280 × 720, margens de 16 px e 12 px entre blocos. Cabeçalho branco com título
  e subtítulo à esquerda e, à direita, as abas de navegação e a fonte e semana dos dados; faixa de
  controles e indicadores logo abaixo; conteúdo no resto. Os segmentadores ficam sempre na mesma
  faixa, à esquerda.
- **Navegação**: quatro botões em forma de aba (Visão geral, Previsão, Desempenho, Metodologia),
  com a aba da página atual preenchida de azul. No Power BI Desktop o botão pede Ctrl+clique; no
  modo de leitura e no serviço, clique simples.
- **Faixas de risco**: a probabilidade de alerta aparece em quatro faixas com cor e nome (baixo
  < 10%, moderado 10–25%, alto 25–50%, muito alto ≥ 50%), na matriz da Visão geral e na tabela da
  Previsão, sempre com a legenda ou o nome da faixa ao lado (cor nunca sozinha).
- **Cartões**: fundo da página `#F2F3F5`, visuais em cartões brancos com borda `#E3E4E8`, cantos
  de 10 px, sem sombra. Títulos em Segoe UI Semibold 11; rótulos e eixos em 9, cinza `#5B5F66`.
- **Cor com papel fixo**: observado `#3F444B`, previsão `#2A78D6`, limiar `#D03B3B`; modelos GBM
  `#2A78D6`, Crescimento sazonal `#EB6834`, Climatologia `#1BAF7A` (as mesmas do Streamlit).
- **Gráficos**: legenda em cima, linhas de grade pontilhadas e claras, sem eixo duplo. Incerteza
  como faixas (90% clara, 50% mais escura), não como barras de erro.
- `tema_dengue_df.json` aplica a maior parte disso a qualquer visual novo.

O resto deste guia explica como o modelo foi montado, para quem quiser refazer do zero ou mudar algo.

Arquivos do kit (pasta `powerbi/`):

| Arquivo | Para quê |
|---|---|
| `painel_dengue.pbip` | O painel pronto (abre no Power BI Desktop) |
| `consultas.pq` | Consultas do Power Query (M) que leem os Parquet |
| `medidas.dax` | As 71 medidas DAX e as 3 colunas calculadas, com o formato de cada uma |
| `tema_dengue_df.json` | Tema com a paleta do projeto |

Tempo para montar do zero: cerca de 1 hora.

---

## 1. Gerar as tabelas

```bash
python -m dengue_df executar -v          # se ainda não rodou com os dados atuais
python -m dengue_df exportar-powerbi
```

O comando imprime o caminho da pasta: copie-o, ele vai no parâmetro `PastaDados`.

| Tabela | Grão | Colunas principais |
|---|---|---|
| `dim_municipio` | município | `geocode`, `municipio`, `uf`, `regiao`, `populacao`, `limiar_casos`, `base_limiar`, `ordem`, `local_mapa` |
| `dim_semana` | semana epidemiológica | `inicio_semana`, `rotulo_se` (SE 44/2026), `temporada`, `rotulo_temporada` (2025/26), `semana_temporada`, `semanas_desde_ultima`, `periodo` (Observado/Previsão) |
| `dim_modelo` | modelo | `modelo`, `modelo_nome`, `ordem`, `descricao` |
| `fato_observado` | município × semana | `casos_usados`, `casos_consolidados`, `casos_nowcast`, `linha_nowcast`, `nowcast`, `incidencia`, clima |
| `fato_previsao` | modelo × município × horizonte | `semana_alvo`, `horizonte` (0 a 4), `mediana`, `li_50`…`ls_95`, `limiar_casos`, `prob_alerta`, `tipo` |
| `fato_backtest` | modelo × município × origem × horizonte | `semana_alvo`, `mediana`, intervalos, `observado`, `wis`, `wis_log`, `cobre_50`…`cobre_95` (0/1), `prob_alerta`, `excedeu`, `brier`, `rotulo_temporada_teste` |
| `fato_resumo` | modelo × horizonte | a tabela que `executar` imprime |
| `fato_cobertura` | modelo × horizonte × nível | `rotulo_nivel`, `cobertura_nominal`, `cobertura_observada` |
| `fato_confiabilidade` | modelo × faixa de probabilidade | `prob_media`, `freq_observada`, `n` |
| `info_execucao` | 1 linha | `fonte`, `ultima_semana`, `rotulo_ultima_semana`, `temporadas_teste`, `gerado_em` |

`fato_previsao` tem, para cada modelo e município, uma linha de **horizonte 0** (`tipo` =
"Último observado") com o último valor observado nos campos de mediana e limites. Ela faz a
linha e a faixa da previsão saírem do fim da série observada no gráfico. Nos visuais de risco,
filtre `horizonte >= 1` (as medidas de probabilidade já ignoram essa linha).

## 2. Carregar no Power BI Desktop

Siga `powerbi/consultas.pq`:

1. **Transformar dados > Gerenciar Parâmetros > Novo**: `PastaDados`, tipo Texto, valor = o
   caminho impresso, terminando em `\`.
2. **Nova Fonte > Consulta Nula > Editor Avançado**: cole a função e renomeie para `LerTabela`.
3. Uma consulta nula por tabela, com a fórmula `= LerTabela("dim_municipio")` e assim por diante,
   cada uma com o nome da tabela.
4. Desmarque **Habilitar carga** em `LerTabela`. **Fechar e Aplicar**.

Os tipos vêm do Parquet (datas como Data, contagens como número): nada de configurar
localidade nem separador decimal.

## 3. Modelo

**Relacionamentos** (Exibição de modelo; todos um-para-muitos, filtro em direção única):

| De (lado 1) | Para (lado muitos) |
|---|---|
| `dim_municipio[geocode]` | `fato_observado[geocode]`, `fato_previsao[geocode]`, `fato_backtest[geocode]` |
| `dim_semana[inicio_semana]` | `fato_observado[inicio_semana]`, `fato_previsao[semana_alvo]`, `fato_backtest[semana_alvo]` |
| `dim_modelo[modelo]` | `fato_previsao[modelo]`, `fato_backtest[modelo]`, `fato_resumo[modelo]`, `fato_cobertura[modelo]`, `fato_confiabilidade[modelo]` |

O Power BI pode criar sozinho alguns relacionamentos ao carregar; confira se são esses e apague
os que sobrarem (por exemplo, `origem` não se relaciona com nada). `info_execucao` fica solta.

**Classificar por coluna** (selecione a coluna > Ferramentas de coluna > Classificar por coluna):

- `dim_municipio[municipio]` por `ordem` (DF primeiro, depois o Entorno em ordem alfabética)
- `dim_modelo[modelo_nome]` por `ordem` (GBM, Crescimento, Climatologia): isso também fixa a cor
  de cada modelo nas legendas, já que o tema distribui as cores pela ordem
- `dim_semana[rotulo_se]` por `inicio_semana`; `dim_semana[rotulo_temporada]` por `temporada`
- `fato_cobertura[rotulo_nivel]` por `nivel`

**Medidas**: crie a tabela `_Medidas` e as medidas de `powerbi/medidas.dax`, com os formatos
indicados. Oculte `_Uma previsão` e a coluna `x` de `_Medidas`.

**Ocultar** nas tabelas fato as chaves (`geocode`, `modelo`, `semana_alvo`, `inicio_semana`): os
visuais devem usar as colunas das dimensões. Isso evita o erro mais comum, que é filtrar pela
coluna da tabela fato e ver medidas em branco ou repetidas.

**Tema**: Exibição > Temas > Procurar temas > `powerbi/tema_dengue_df.json`.

## 4. Páginas

Cores usadas abaixo: observado `#3F444B` (cinza-grafite), previsão `#2A78D6` (azul),
limiar `#D03B3B` (vermelho, sempre com rótulo). Em todas as páginas, um segmentador de
`dim_modelo[modelo_nome]` em seleção única, começando em "GBM quantílico" (Exibição >
Sincronizar segmentações, para valer nas páginas 1 e 2).

### Página 1 – Visão geral

- **Cartão** `Texto dados até` e **cartão** `Texto aviso de dados` (no topo, discretos).
- **Cartões**, nesta ordem e todos com 250 px de largura e número em Segoe UI Semibold 20:
  `Texto maior risco (valor)` (por exemplo 5%), `Casos na última semana` e `Casos previstos na
  região (próxima semana)` (região inteira) e `Texto variação prevista (4 semanas)` ("Variação
  prevista em 4 semanas", por exemplo ▲ 25%). O rótulo do primeiro muda com os dados ("Maior
  risco: Cocalzinho de Goiás"), e o rótulo de um cartão é sempre fixo: o cartão fica com o nome
  de exibição em branco (um espaço não separável, para reservar a linha) e um segundo cartão,
  sem fundo, com `Texto maior risco (rótulo)` em 9 pt `#5B5F66`, fica por cima dessa linha
  (y = topo do cartão + 54, altura 18). Assim o número e o rótulo ficam na mesma altura dos
  vizinhos.
  A medida `Municípios com alerta provável` continua no modelo, mas saiu do painel: fora da
  temporada ela fica quase sempre em 0.
- **Matriz** de risco: Linhas `dim_municipio[municipio]`; Colunas `dim_semana[rotulo_se]`;
  Valores `Probabilidade de alerta`. Filtro do visual: `dim_semana[periodo]` = Previsão.
  Formatação condicional > Cor da tela de fundo > Formatar estilo **Valor do campo** > medida
  `Cor do risco (célula)`. Embaixo da matriz, quatro caixas de texto com o fundo de cada faixa
  servem de legenda (Baixo < 10%, Moderado 10–25%, Alto 25–50%, Muito alto ≥ 50%).
- **Gráfico de linhas** "Casos na região": Eixo X `dim_semana[inicio_semana]` (Contínuo); Eixo Y
  `Linha observado consolidado`, `Linha nowcast` e `Previsão total (soma das medianas)`; filtro
  `semanas_desde_ultima` ≥ -52. Sem faixa de incerteza: quantis não se somam. Ocupa a faixa de
  baixo da página inteira, com altura suficiente para a curva respirar.
- **Gráfico de barras** "Mais perto do limiar de alerta · casos da última semana em % do limiar":
  Eixo Y `dim_municipio[municipio]`, Eixo X `% do limiar (8 maiores)`, classificado do maior para
  o menor, rótulos de dados em %. No painel pronto as barras têm uma cor só, o verde do tema.
  Para destacar quem está chegando perto do limiar, use Formatação condicional > Valor do campo >
  `Cor da proximidade (barra)`, que já está no modelo: cinza `#8A8F98` enquanto o município está
  longe, laranja a partir de 75% e vermelho no limiar ou acima. Complementa a matriz (que mostra a
  probabilidade prevista) com a situação atual: quem já está mais perto do limiar. A medida deixa
  em branco tudo abaixo do 8º lugar, então o gráfico mostra só 8 barras sem rolagem.
- Opcional: **mapa** com `dim_municipio[local_mapa]` em Local e a mesma medida no tamanho ou na
  cor. Depende de os mapas estarem liberados no seu ambiente; a matriz já cumpre o papel.

**Abas de navegação** (todas as páginas): Inserir > Botões > Em branco; em Ação, Tipo
"Navegação de página" e o destino. Texto em Segoe UI Semibold 10; a aba da página atual com fundo
`#2A78D6` e texto branco, as demais sem fundo e texto `#5B5F66`. As quatro abas têm a mesma
largura (112 px, a partir de x = 798), para a barra ficar alinhada e não "pular" de uma página
para outra.

**Botão "↺ Limpar filtros"** (páginas 1 a 3, logo abaixo da primeira aba, à esquerda da linha
"Fonte"): botão em branco, fundo branco, borda `#C9D3E0` com raio 12, texto Segoe UI Semibold 9
`#1C5CAB`. Ação: **Indicador** > "Padrão - Visão geral", "Padrão - Previsão" ou "Padrão -
Desempenho". Cada indicador foi capturado com a página no estado padrão (GBM quantílico,
Brasília, horizonte 1, temporada 2025/26, nada selecionado) e guarda só **Dados**: desfaz
segmentações e seleções cruzadas sem mexer na visibilidade dos visuais. No Desktop, o botão
funciona com Ctrl + clique.
Atenção: o Power BI Desktop atual grava `preserveNewVisualVisibility` nos indicadores, mas o
esquema 2.1.0 não aceita essa propriedade, e o projeto não abre ("Seu relatório tem problemas…").
Se recriar ou atualizar um indicador pelo painel, apague essa linha do `.bookmark.json` e deixe
`"options": {"targetVisualNames": [], "suppressDisplay": true}`.

### Página 2 – Previsão por município

- **Segmentador** `dim_municipio[municipio]` (lista suspensa, seleção única) + segmentador de
  modelo sincronizado.
- **Cartões** (cinco, todos com 160 px e número em 20 pt): `Casos na última semana`
  ("Última semana"), `Previsão próxima semana` (azul), `Texto IC 90% próxima semana` (a partir
  de mil casos vira "4,5 – 8,9 mil" para caber), `Texto prob. de alerta (valor)` com a cor da
  fonte por **Valor do campo** = `Cor do risco (texto)`, e `Limiar de alerta (casos)`
  (vermelho). O cartão de probabilidade usa o mesmo truque do rótulo da página 1, com
  `Texto prob. de alerta (rótulo)` ("Risco +1 semana: baixo").
- **Gráfico de linhas** (o gráfico principal):
  - Eixo X: `dim_semana[inicio_semana]` (tipo Contínuo).
  - Eixo Y: `Linha observado consolidado`, `Linha nowcast`, `Previsão mediana`,
    `Limiar no gráfico` (nome de exibição "Limiar de alerta") e, por último,
    `Previsão mediana (faixa 50%)` (série auxiliar da faixa de 50%, sem nome de exibição).
  - Filtro do visual: `dim_semana[semanas_desde_ultima]` é maior ou igual a -26 (últimos 6 meses
    + 4 semanas de previsão), para a previsão ocupar uma parte legível do eixo.
  - O limiar só é desenhado quando cabe na escala (até 2 vezes o maior valor da janela). Quando
    fica acima disso, um cartão pequeno sem fundo no canto superior direito do gráfico mostra
    `Aviso de limiar fora da escala` em vermelho 9 pt, por exemplo "Limiar de alerta (1.532
    casos) acima da escala". O valor do limiar continua no cartão "Limiar (casos/semana)".
  - Painel **Análise** (lupa) > **Barras de erro** > série `Previsão mediana` > Limite superior
    `Previsão IC 90% superior`, Limite inferior `Previsão IC 90% inferior`, Relação com a
    medida: **Absoluta**. Ligue **Faixa de erro** (área sombreada) com transparência perto de 75% e
    desligue a barra de erro em si. Em versões antigas do Power BI Desktop as barras de erro
    ficam em Arquivo > Opções > Recursos de visualização.
  - Formatação das linhas: observado consolidado `#1F2328` cheia 2 px; nowcast `#8A8F98`
    tracejada; mediana `#1C5CAB` 3 px; limiar `#D03B3B` tracejada. Cada série tem cor e traço
    próprios, para a legenda separar bem os itens.
  - Cor das faixas fixada nas barras de erro (Corresponder à cor da série desligado): 90% em
    `#1C5CAB` e 50% em `#2A78D6`, com a transparência padrão.
  - Título do eixo Y: "Casos por semana". Legenda em cima, só com as linhas (Observado, Nowcast,
    Previsão, Limiar). As faixas são explicadas no subtítulo fixo: "Faixas azuis: intervalo de 50%
    (mais escura) e de 90% (mais clara)". Uma faixa na legenda do Power BI vira um traço igual ao
    de uma linha, e um traço azul claro ao lado do azul da mediana confundia.
  - IC 50%: `Previsão mediana (faixa 50%)` (uma cópia da mediana) leva barras de erro com os
    limites de 50% e faixa mais escura. Para não aparecer na legenda: linha 100% transparente,
    cor `#FFFFFF` (some no fundo branco), nome de exibição só com um espaço não separável e a
    série no fim do eixo Y. O gráfico de backtest (página 3) segue o mesmo esquema.
- **Tabela** com as 4 semanas: `dim_semana[rotulo_se]` (filtro `periodo` = Previsão),
  `Previsão mediana`, `Previsão IC 90% inferior`, `Previsão IC 90% superior`,
  `Probabilidade de alerta`.

### Página 3 – Desempenho do modelo (backtest)

- **Cartão** com `info_execucao[temporadas_teste]` ("Temporadas de teste: …").
- **Matriz**: Linhas `dim_modelo[modelo_nome]`; Colunas `fato_backtest[horizonte]`; Valores
  `Backtest WIS relativo à climatologia`, `Backtest cobertura IC 90%`, `Backtest Brier do alerta`.
  Esta página não usa o segmentador de modelo (mostra todos lado a lado).
- **Gráfico de linhas** "Cobertura dos intervalos": Eixo X `fato_cobertura[cobertura_nominal]`
  (Contínuo); Eixo Y `Cobertura GBM quantílico`, `Cobertura Crescimento sazonal`,
  `Cobertura Climatologia` e `Cobertura nominal` (a diagonal "Ideal", tracejada e cinza). Linha
  abaixo da diagonal = intervalo estreito demais.
- **Gráfico de linhas** "Alerta: probabilidade prevista x frequência observada" (diagrama de
  confiabilidade): Eixo X `fato_confiabilidade[faixa_centro]` (Contínuo); Eixo Y as três medidas
  `Alerta observado …` e `Calibração perfeita (alerta)` como diagonal.
- Interações (Formatar > Editar interações): os quatro segmentadores não filtram a matriz nem os
  dois gráficos de calibração, só o gráfico previsto × observado.
- **Gráfico de linhas** previsto × observado: Eixo X `dim_semana[inicio_semana]`; Eixo Y
  `Backtest observado` (`#1F2328`, cheia 2 px, "Observado"), `Backtest mediana prevista`
  (`#1C5CAB`, tracejada 2 px, "Prevista (mediana)") e `Backtest mediana (faixa 50%)` ("Intervalos
  de 50% e 90%", linha transparente), com barras de erro de 90% e 50% em faixa, como na página 2.
  Observado escuro e cheio contra previsto azul e tracejado: dá para separar as duas linhas mesmo
  em cima da faixa azul. Segmentadores de seleção única:
  `dim_municipio[municipio]`, `dim_modelo[modelo_nome]` (não sincronizado),
  `fato_backtest[horizonte]` e `fato_backtest[rotulo_temporada_teste]`.

### Página 4 – Metodologia

Caixas de texto curtas, por exemplo:

- **Dados**: casos semanais do InfoDengue e clima diário (Mosqlimate); nas últimas 3 semanas o
  valor é a estimativa de nowcasting do InfoDengue, porque as notificações ainda estão chegando.
- **Modelos**: climatologia (referência sazonal), crescimento sazonal e gradient boosting
  quantílico global com lags de casos, sazonalidade e clima.
- **Avaliação**: backtest por origem móvel nas últimas temporadas completas, treinando só com o
  passado. WIS (Weighted Interval Score): quanto menor, melhor; o relativo compara com a
  climatologia. Cobertura: fração das semanas em que o observado caiu dentro do intervalo.
- **Alerta**: limiar = percentil 90 da incidência semanal histórica do município;
  a probabilidade sai da distribuição prevista.

## 5. Conferência

As médias da página 3 têm de bater com a tabela que `executar` imprime. Na rodada real de
3/11/2026, por exemplo, o GBM no horizonte 1 tinha WIS relativo 0,326, cobertura do IC 90% de
86,5% e Brier 0,019. Se a matriz mostrar outros números, quase sempre é um visual usando a coluna
`modelo` da tabela fato em vez de `dim_modelo[modelo_nome]`.

## 6. Atualização

**Manual**: rode `ingerir`, `executar` e `exportar-powerbi` e clique em **Atualizar** no Power BI
Desktop.

**Semanal, automática**: `scripts/atualizar_semanal.ps1` roda os três comandos e grava um log em
`outputs/atualizacao.log`. Agende-o no Agendador de Tarefas do Windows (Ação: `powershell.exe`,
Argumentos: `-ExecutionPolicy Bypass -File "C:\monitoramento-dengue-df\scripts\atualizar_semanal.ps1"`).

**Publicado no Power BI Service**, duas saídas:

- Manter os arquivos locais e instalar o gateway de dados local no modo pessoal na mesma máquina
  que roda o script; a atualização agendada do relatório passa por ele.
- Gravar `outputs/powerbi/` numa pasta do OneDrive ou SharePoint da empresa e trocar
  `File.Contents` na função `LerTabela` por uma leitura do SharePoint (Obter dados > Pasta do
  SharePoint). Arquivos na nuvem dispensam gateway.

Rodar o Python dentro do Power BI (fonte "Script Python") também funciona, mas a atualização
agendada exigiria o gateway pessoal e um ambiente Python na máquina dele; deixar o Power BI só
lendo arquivos é mais simples e mais estável.

## 7. Cuidados de leitura

- **Quantis não se somam.** As medidas de previsão ficam em branco quando o visual junta mais de um
  município ou modelo. Para o total da região use `Previsão total (soma das medianas)`, que é uma
  aproximação sem intervalo.
- **Intervalos do GBM estão estreitos.** No backtest real, o IC 90% do GBM cobriu de 82,9% a 86,5%
  das semanas, conforme o horizonte (o nominal seria 90%). A página 3 mostra isso; a calibração dos intervalos é o próximo
  passo do projeto.
