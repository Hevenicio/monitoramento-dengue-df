// Consultas do Power Query (linguagem M) para o painel dengue-df.
// Passo a passo completo em docs/powerbi.md.
//
// 1) Página Inicial > Transformar dados > Gerenciar Parâmetros > Novo
//      Nome: PastaDados    Tipo: Texto    Valor atual: o caminho impresso por
//      `python -m dengue_df exportar-powerbi`, terminando com \  (ex.: C:\projetos\dengue-df\outputs\powerbi\)
//
// 2) Nova Fonte > Consulta Nula > Editor Avançado: cole a função abaixo e renomeie a consulta
//    para LerTabela.

(nome as text) as table =>
    Parquet.Document(File.Contents(PastaDados & nome & ".parquet"))

// 3) Para cada tabela: Nova Fonte > Consulta Nula, cole a linha na barra de fórmulas e renomeie
//    a consulta com o mesmo nome da tabela (é o nome que as medidas DAX usam).
//
//      dim_municipio        = LerTabela("dim_municipio")
//      dim_semana           = LerTabela("dim_semana")
//      dim_modelo           = LerTabela("dim_modelo")
//      fato_observado       = LerTabela("fato_observado")
//      fato_previsao        = LerTabela("fato_previsao")
//      fato_backtest        = LerTabela("fato_backtest")
//      fato_resumo          = LerTabela("fato_resumo")
//      fato_cobertura       = LerTabela("fato_cobertura")
//      fato_confiabilidade  = LerTabela("fato_confiabilidade")
//      info_execucao        = LerTabela("info_execucao")
//
// 4) Clique com o botão direito em LerTabela e desmarque "Habilitar carga" (ela é só uma função).
//    Fechar e Aplicar.
//
// Os tipos (data, número inteiro, decimal, verdadeiro/falso) vêm do próprio Parquet: não é
// preciso alterar tipos nem configurar localidade.
