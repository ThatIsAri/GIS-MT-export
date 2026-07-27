[CmdletBinding()]
param(
    [string]$TaskName = "CZ Async Certificate Agent",

    [string]$ProjectRoot = "",

    [string]$DkclPath = "C:\Users\kudryavcev\Desktop\dkcl64.exe",

    [string]$AgentHost = "0.0.0.0",

    [int]$AgentPort = 18771
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"


function Quote-TaskArgument {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Value
    )

    return '"' + $Value.Replace('"', '\"') + '"'
}


if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
}


$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot)

$PythonwPath = Join-Path `
    $ProjectRoot `
    ".venv\Scripts\pythonw.exe"

$PythonPath = Join-Path `
    $ProjectRoot `
    ".venv\Scripts\python.exe"

$AgentPath = Join-Path `
    $ProjectRoot `
    "tools\certificate_agent.py"

$EnvFile = Join-Path `
    $ProjectRoot `
    ".env"


if (-not (Test-Path -LiteralPath $PythonwPath)) {
    $PythonwPath = $PythonPath
}


$RequiredFiles = @(
    $PythonwPath,
    $AgentPath,
    $EnvFile,
    $DkclPath
)


foreach ($RequiredFile in $RequiredFiles) {
    if (-not (Test-Path -LiteralPath $RequiredFile)) {
        throw "Required file not found: $RequiredFile"
    }
}


if (($AgentPort -lt 1) -or ($AgentPort -gt 65535)) {
    throw "AgentPort must be between 1 and 65535."
}


$CurrentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name


$ArgumentParts = @(
    (Quote-TaskArgument $AgentPath),
    "--project-root",
    (Quote-TaskArgument $ProjectRoot),
    "--env-file",
    (Quote-TaskArgument $EnvFile),
    "--host",
    (Quote-TaskArgument $AgentHost),
    "--port",
    [string]$AgentPort,
    "--dkcl-path",
    (Quote-TaskArgument $DkclPath)
)


$Arguments = $ArgumentParts -join " "


$ActionParameters = @{
    Execute = $PythonwPath
    Argument = $Arguments
    WorkingDirectory = $ProjectRoot
}

$Action = New-ScheduledTaskAction @ActionParameters


$TriggerParameters = @{
    AtLogOn = $true
    User = $CurrentUser
}

$Trigger = New-ScheduledTaskTrigger @TriggerParameters


$PrincipalParameters = @{
    UserId = $CurrentUser
    LogonType = "Interactive"
    RunLevel = "Limited"
}

$Principal = New-ScheduledTaskPrincipal @PrincipalParameters


$SettingsParameters = @{
    AllowStartIfOnBatteries = $true
    DontStopIfGoingOnBatteries = $true
    StartWhenAvailable = $true
    RestartCount = 999
    RestartInterval = New-TimeSpan -Minutes 1
    ExecutionTimeLimit = [TimeSpan]::Zero
    MultipleInstances = "IgnoreNew"
}

$Settings = New-ScheduledTaskSettingsSet @SettingsParameters


$TaskParameters = @{
    Action = $Action
    Trigger = $Trigger
    Principal = $Principal
    Settings = $Settings
}

$Task = New-ScheduledTask @TaskParameters


$ExistingTask = Get-ScheduledTask `
    -TaskName $TaskName `
    -ErrorAction SilentlyContinue


if ($null -ne $ExistingTask) {
    Stop-ScheduledTask `
        -TaskName $TaskName `
        -ErrorAction SilentlyContinue

    Start-Sleep -Seconds 1

    Unregister-ScheduledTask `
        -TaskName $TaskName `
        -Confirm:$false
}


Register-ScheduledTask `
    -TaskName $TaskName `
    -InputObject $Task `
    -Force |
Out-Null


Start-ScheduledTask `
    -TaskName $TaskName


Start-Sleep -Seconds 3


$TaskState = Get-ScheduledTask `
    -TaskName $TaskName

$TaskInfo = Get-ScheduledTaskInfo `
    -TaskName $TaskName


$AgentProcess = Get-CimInstance Win32_Process |
Where-Object {
    ($_.Name -match "^pythonw?\.exe$") -and
    ($_.CommandLine -like "*certificate_agent.py*")
} |
Select-Object -First 1


$ProcessIdValue = $null

if ($null -ne $AgentProcess) {
    $ProcessIdValue = $AgentProcess.ProcessId
}


$HealthStatus = "NOT_CHECKED"
$HealthMessage = ""


try {
    $HealthUri = "http://127.0.0.1:{0}/health" -f $AgentPort

    $HealthResponse = Invoke-RestMethod `
        -Method Get `
        -Uri $HealthUri `
        -TimeoutSec 5

    $HealthStatus = [string]$HealthResponse.status

    $HealthMessage = "service={0}; version={1}; busy={2}" -f `
        $HealthResponse.service, `
        $HealthResponse.version, `
        $HealthResponse.busy
}
catch {
    $HealthStatus = "ERROR"
    $HealthMessage = $_.Exception.Message
}


[PSCustomObject]@{
    TaskName = $TaskState.TaskName
    TaskState = $TaskState.State
    LastRunTime = $TaskInfo.LastRunTime
    LastTaskResult = $TaskInfo.LastTaskResult
    User = $CurrentUser
    Python = $PythonwPath
    Agent = $AgentPath
    ListenAddress = "http://{0}:{1}" -f $AgentHost, $AgentPort
    ProcessId = $ProcessIdValue
    HealthStatus = $HealthStatus
    HealthMessage = $HealthMessage
}