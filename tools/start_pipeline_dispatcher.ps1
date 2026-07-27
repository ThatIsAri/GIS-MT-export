[CmdletBinding()]
param(
    [string]$ProjectRoot = "",
    [string]$DkclPath = "C:\Users\kudryavcev\Desktop\dkcl64.exe",
    [int]$PollSeconds = 1,
    [int]$SyncPollSeconds = 3
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (
    [string]::IsNullOrWhiteSpace(
        $ProjectRoot
    )
) {
    $ProjectRoot = Split-Path `
        -Parent `
        $PSScriptRoot
}

$ProjectRoot = `
    [System.IO.Path]::GetFullPath(
        $ProjectRoot
    )

$PythonPath = Join-Path `
    $ProjectRoot `
    ".venv\Scripts\python.exe"

$DispatcherPath = Join-Path `
    $ProjectRoot `
    "tools\pipeline_dispatcher.py"

$EnvFile = Join-Path `
    $ProjectRoot `
    ".env"

$LogDirectory = Join-Path `
    $ProjectRoot `
    "logs\pipeline_dispatcher"

foreach (
    $RequiredPath
    in @(
        $PythonPath,
        $DispatcherPath,
        $EnvFile,
        $DkclPath
    )
) {
    if (
        -not (
            Test-Path `
                -LiteralPath $RequiredPath
        )
    ) {
        throw (
            "Required file not found: " +
            $RequiredPath
        )
    }
}

New-Item `
    -ItemType Directory `
    -Path $LogDirectory `
    -Force |
Out-Null

$LogPath = Join-Path `
    $LogDirectory `
    (
        "dispatcher_{0}.log" `
            -f (
                Get-Date `
                    -Format "yyyyMMdd"
            )
    )

Set-Location `
    -LiteralPath $ProjectRoot

Write-Host "Pipeline dispatcher is starting."
Write-Host "Project: $ProjectRoot"
Write-Host "Log: $LogPath"

$Arguments = @(
    "-u",
    $DispatcherPath,
    "--env-file",
    $EnvFile,
    "--dkcl-path",
    $DkclPath,
    "--allow-pin-prompt",
    "--poll-seconds",
    [string]$PollSeconds,
    "--sync-poll-seconds",
    [string]$SyncPollSeconds
)

& $PythonPath @Arguments 2>&1 |
    Tee-Object `
        -FilePath $LogPath `
        -Append

$ExitCode = $LASTEXITCODE

if (
    $null -eq $ExitCode
) {
    $ExitCode = 1
}

exit $ExitCode