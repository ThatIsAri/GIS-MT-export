$ErrorActionPreference = "Stop"

$utf8NoBom = New-Object `
    System.Text.UTF8Encoding(
        $false
    )

[Console]::InputEncoding = $utf8NoBom
[Console]::OutputEncoding = $utf8NoBom

$global:OutputEncoding = $utf8NoBom

$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

& "$env:SystemRoot\System32\chcp.com" `
    65001 |
Out-Null

$targetScript = Join-Path `
    $PSScriptRoot `
    "run_daily_sync.ps1"

if (-not (Test-Path -LiteralPath $targetScript)) {
    throw (
        "Не найден основной сценарий: " +
        $targetScript
    )
}

& $targetScript @args

$exitCode = $LASTEXITCODE

if ($null -eq $exitCode) {
    $exitCode = 0
}

exit [int]$exitCode