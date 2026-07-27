[CmdletBinding()]
param(
    [string]$TaskName = "CZ Async Pipeline Dispatcher",
    [string]$ProjectRoot = "",
    [string]$DkclPath = "C:\Users\kudryavcev\Desktop\dkcl64.exe"
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

$LauncherPath = Join-Path `
    $ProjectRoot `
    "tools\start_pipeline_dispatcher.ps1"

if (
    -not (
        Test-Path `
            -LiteralPath $LauncherPath
    )
) {
    throw (
        "Launcher not found: " +
        $LauncherPath
    )
}

if (
    -not (
        Test-Path `
            -LiteralPath $DkclPath
    )
) {
    throw (
        "dkcl64.exe not found: " +
        $DkclPath
    )
}

$CurrentUser = `
    [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

$Arguments = @(
    "-NoLogo",
    "-NoProfile",
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    (
        '"{0}"' `
            -f $LauncherPath
    ),
    "-ProjectRoot",
    (
        '"{0}"' `
            -f $ProjectRoot
    ),
    "-DkclPath",
    (
        '"{0}"' `
            -f $DkclPath
    ),
    "-PollSeconds",
    "1",
    "-SyncPollSeconds",
    "3"
) -join " "

$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument $Arguments `
    -WorkingDirectory $ProjectRoot

$Trigger = New-ScheduledTaskTrigger `
    -AtLogOn `
    -User $CurrentUser

$Principal = New-ScheduledTaskPrincipal `
    -UserId $CurrentUser `
    -LogonType Interactive `
    -RunLevel Limited

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 999 `
    -RestartInterval (
        New-TimeSpan `
            -Minutes 1
    ) `
    -ExecutionTimeLimit (
        [TimeSpan]::Zero
    ) `
    -MultipleInstances IgnoreNew

$Task = New-ScheduledTask `
    -Action $Action `
    -Trigger $Trigger `
    -Principal $Principal `
    -Settings $Settings

Register-ScheduledTask `
    -TaskName $TaskName `
    -InputObject $Task `
    -Force |
Out-Null

Start-ScheduledTask `
    -TaskName $TaskName

Start-Sleep `
    -Seconds 2

Get-ScheduledTask `
    -TaskName $TaskName |
Select-Object `
    TaskName,
    State