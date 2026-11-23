# Atualiza dados, modelos e tabelas do Power BI do projeto dengue-df.
# Agende no Agendador de Tarefas do Windows (semanal). Veja docs/powerbi.md, seção 6.
#
#   powershell.exe -ExecutionPolicy Bypass -File "C:\monitoramento-dengue-df\scripts\atualizar_semanal.ps1"

$ErrorActionPreference = "Continue"   # o Python escreve avisos no stderr; o código de saída decide
$env:PYTHONIOENCODING = "utf-8"
$raiz = Split-Path -Parent $PSScriptRoot

$python = Join-Path $raiz ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

$saidas = Join-Path $raiz "outputs"
New-Item -ItemType Directory -Force -Path $saidas | Out-Null
$log = Join-Path $saidas "atualizacao.log"
$saida = Join-Path $saidas "ultimo_comando.out.txt"
$erros = Join-Path $saidas "ultimo_comando.err.txt"

foreach ($comando in @("ingerir", "executar", "exportar-powerbi")) {
    Add-Content -Path $log -Encoding UTF8 -Value "$(Get-Date -Format s)  dengue_df $comando"
    $p = Start-Process -FilePath $python -ArgumentList "-m", "dengue_df", $comando `
        -WorkingDirectory $raiz -NoNewWindow -Wait -PassThru `
        -RedirectStandardOutput $saida -RedirectStandardError $erros
    Get-Content -Path $saida, $erros -Encoding UTF8 | Add-Content -Path $log -Encoding UTF8
    if ($p.ExitCode -ne 0) {
        Add-Content -Path $log -Encoding UTF8 -Value "$(Get-Date -Format s)  FALHOU: dengue_df $comando (código $($p.ExitCode))"
        exit $p.ExitCode
    }
}
Add-Content -Path $log -Encoding UTF8 -Value "$(Get-Date -Format s)  concluído"
