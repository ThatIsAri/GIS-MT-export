[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [ValidateSet(
        "Any",
        "CurrentUser",
        "LocalMachine"
    )]
    [string]$StoreLocation = "Any",

    [Parameter(Mandatory = $false)]
    [ValidateRange(5, 300)]
    [int]$TimeoutSeconds = 60,

    [Parameter(Mandatory = $false)]
    [string]$EnvFile,

    [Parameter(Mandatory = $false)]
    [string]$DateFromUtc,

    [Parameter(Mandatory = $false)]
    [string]$DateToUtc,

    [Parameter(Mandatory = $false)]
    [string]$LogDirectory,

    [Parameter(Mandatory = $false)]
    [ValidateRange(0, 86400)]
    [int]$RetryDelaySeconds = 0,

    [Parameter(Mandatory = $false)]
    [switch]$AllowPinPrompt,

    [Parameter(Mandatory = $false)]
    [switch]$SkipEdo,

    [Parameter(Mandatory = $false)]
    [switch]$ForceEdo,

    [Parameter(Mandatory = $false)]
    [switch]$EdoFailFast,

    [Parameter(Mandatory = $false)]
    [switch]$ContinueOnError,

    [Parameter(Mandatory = $false)]
    [switch]$StopOnEntityError
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$utf8NoBom = New-Object `
    System.Text.UTF8Encoding `
    -ArgumentList $false

[Console]::InputEncoding = $utf8NoBom
[Console]::OutputEncoding = $utf8NoBom
$OutputEncoding = $utf8NoBom

$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

try {
    chcp 65001 | Out-Null
}
catch {
}

$script:LogPath = $null


function Write-RunLog {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$Message
    )

    if ([string]::IsNullOrEmpty($Message)) {
        Write-Host ""

        if (
            -not [string]::IsNullOrWhiteSpace(
                $script:LogPath
            )
        ) {
            Add-Content `
                -LiteralPath $script:LogPath `
                -Value "" `
                -Encoding UTF8
        }

        return
    }

    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$timestamp] $Message"

    Write-Host $line

    if (
        -not [string]::IsNullOrWhiteSpace(
            $script:LogPath
        )
    ) {
        Add-Content `
            -LiteralPath $script:LogPath `
            -Value $line `
            -Encoding UTF8
    }
}


function Resolve-ProjectPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [string]$ProjectRoot
    )

    if (
        [System.IO.Path]::IsPathRooted(
            $Path
        )
    ) {
        return [System.IO.Path]::GetFullPath(
            $Path
        )
    }

    $combinedPath = Join-Path `
        $ProjectRoot `
        $Path

    return [System.IO.Path]::GetFullPath(
        $combinedPath
    )
}


function Invoke-DockerCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,

        [Parameter(Mandatory = $true)]
        [string]$CommandName,

        [Parameter(Mandatory = $false)]
        [switch]$WriteOutputToLog
    )

    $previousPreference = $ErrorActionPreference

    $outputLines = New-Object `
        "System.Collections.Generic.List[string]"

    try {
        $ErrorActionPreference = "Continue"

        & docker @Arguments 2>&1 |
        ForEach-Object {
            $line = [string]$_

            [void]$outputLines.Add(
                $line
            )

            if ($WriteOutputToLog.IsPresent) {
                Write-RunLog `
                    -Message $line
            }
        }

        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }

    if ($null -eq $exitCode) {
        $exitCode = 1
    }

    return [pscustomobject]@{
        CommandName = $CommandName
        ExitCode = [int]$exitCode
        Output = [string[]]$outputLines.ToArray()
    }
}


function Invoke-MySqlQuery {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Query,

        [Parameter(Mandatory = $true)]
        [string]$ResolvedEnvFile
    )

    $containerCommand = (
        'export MYSQL_PWD="$MYSQL_PASSWORD"; ' +
        'exec mysql ' +
        '--batch ' +
        '--raw ' +
        '--skip-column-names ' +
        '--default-character-set=utf8mb4 ' +
        '--user="$MYSQL_USER" ' +
        '"$MYSQL_DATABASE"'
    )

    $dockerArguments = @(
        "compose"
        "--ansi"
        "never"
        "--env-file"
        $ResolvedEnvFile
        "exec"
        "-T"
        "mysql"
        "sh"
        "-c"
        $containerCommand
    )

    $previousPreference = $ErrorActionPreference

    $outputLines = New-Object `
        "System.Collections.Generic.List[string]"

    try {
        $ErrorActionPreference = "Continue"

        $Query |
        & docker @dockerArguments 2>&1 |
        ForEach-Object {
            [void]$outputLines.Add(
                [string]$_
            )
        }

        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }

    if ($null -eq $exitCode) {
        $exitCode = 1
    }

    return [pscustomobject]@{
        CommandName = "Legal entity discovery"
        ExitCode = [int]$exitCode
        Output = [string[]]$outputLines.ToArray()
    }
}


function Get-LegalEntities {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ResolvedEnvFile
    )

    $mysqlQuery = @'
SELECT
    entity.id,
    entity.inn,
    REPLACE(
        REPLACE(
            REPLACE(
                entity.short_name,
                CHAR(9),
                ' '
            ),
            CHAR(10),
            ' '
        ),
        CHAR(13),
        ' '
    ) AS short_name
FROM legal_entity AS entity
INNER JOIN legal_entity_integration_config AS config
    ON config.legal_entity_id = entity.id
WHERE entity.status = 'ACTIVE'
  AND config.true_api_enabled = 1
ORDER BY entity.id;
'@

    $queryResult = Invoke-MySqlQuery `
        -Query $mysqlQuery `
        -ResolvedEnvFile $ResolvedEnvFile

    if ($queryResult.ExitCode -ne 0) {
        foreach ($line in $queryResult.Output) {
            Write-RunLog `
                -Message ([string]$line)
        }

        throw (
            "Legal entity discovery failed with exit code " +
            $queryResult.ExitCode +
            "."
        )
    }

    $entities = New-Object `
        "System.Collections.Generic.List[object]"

    foreach ($line in $queryResult.Output) {
        $preparedLine = [string]$line

        if (
            [string]::IsNullOrWhiteSpace(
                $preparedLine
            )
        ) {
            continue
        }

        $parts = $preparedLine -split "`t", 3

        if ($parts.Count -ne 3) {
            Write-RunLog (
                "Ignored non-data MySQL output: " +
                $preparedLine
            )

            continue
        }

        $entityId = 0

        $entityIdParsed = [int]::TryParse(
            [string]$parts[0],
            [ref]$entityId
        )

        $inn = ([string]$parts[1]).Trim()
        $shortName = ([string]$parts[2]).Trim()

        if (-not $entityIdParsed) {
            Write-RunLog (
                "Ignored row with invalid entity ID: " +
                $preparedLine
            )

            continue
        }

        if (
            $inn -notmatch '^\d{10}(\d{2})?$'
        ) {
            Write-RunLog (
                "Ignored row with invalid INN: " +
                $preparedLine
            )

            continue
        }

        [void]$entities.Add(
            [pscustomobject]@{
                EntityId = $entityId
                Inn = $inn
                ShortName = $shortName
            }
        )
    }

    return $entities.ToArray()
}


$projectRoot = Split-Path `
    -Parent `
    $PSScriptRoot

Set-Location `
    -LiteralPath $projectRoot

$composeFile = Join-Path `
    $projectRoot `
    "compose.yaml"

$singleEntityScript = Join-Path `
    $PSScriptRoot `
    "run_daily_sync.ps1"

if (
    -not (
        Test-Path `
            -LiteralPath $composeFile
    )
) {
    throw (
        "Docker Compose file was not found: " +
        $composeFile
    )
}

if (
    -not (
        Test-Path `
            -LiteralPath $singleEntityScript
    )
) {
    throw (
        "Single-organization synchronization script " +
        "was not found: " +
        $singleEntityScript
    )
}

$null = Get-Command `
    docker `
    -ErrorAction Stop

if (
    [string]::IsNullOrWhiteSpace(
        $EnvFile
    )
) {
    $EnvFile = Join-Path `
        $projectRoot `
        ".env"
}
else {
    $EnvFile = Resolve-ProjectPath `
        -Path $EnvFile `
        -ProjectRoot $projectRoot
}

if (
    -not (
        Test-Path `
            -LiteralPath $EnvFile
    )
) {
    throw (
        "Environment file was not found: " +
        $EnvFile
    )
}

if (
    [string]::IsNullOrWhiteSpace(
        $LogDirectory
    )
) {
    $LogDirectory = Join-Path `
        $projectRoot `
        "logs\all_legal_entities_sync"
}
else {
    $LogDirectory = Resolve-ProjectPath `
        -Path $LogDirectory `
        -ProjectRoot $projectRoot
}

New-Item `
    -ItemType Directory `
    -Path $LogDirectory `
    -Force |
Out-Null

$entityLogDirectory = Join-Path `
    $LogDirectory `
    "entities"

New-Item `
    -ItemType Directory `
    -Path $entityLogDirectory `
    -Force |
Out-Null

$runTimestamp = Get-Date `
    -Format "yyyyMMdd_HHmmss"

$script:LogPath = Join-Path `
    $LogDirectory `
    (
        "all_entities_" +
        $runTimestamp +
        ".log"
    )

$startedAt = Get-Date

$results = New-Object `
    "System.Collections.Generic.List[object]"

Write-RunLog (
    "Automatic synchronization started. " +
    "The organization list will be read " +
    "before any job starts."
)

Write-RunLog (
    "Starting MySQL and RabbitMQ."
)

$startupArguments = @(
    "compose"
    "--ansi"
    "never"
    "--env-file"
    $EnvFile
    "up"
    "-d"
    "--wait"
    "mysql"
    "rabbitmq"
)

$servicesResult = Invoke-DockerCommand `
    -Arguments $startupArguments `
    -CommandName "Docker services startup" `
    -WriteOutputToLog

if (
    $servicesResult.ExitCode -ne 0
) {
    throw (
        "Docker services startup failed with exit code " +
        $servicesResult.ExitCode +
        "."
    )
}

Write-RunLog (
    "Searching for ACTIVE organizations " +
    "with True API enabled."
)

$entities = @(
    Get-LegalEntities `
        -ResolvedEnvFile $EnvFile
)

Write-RunLog (
    "Organizations found: " +
    $entities.Count +
    "."
)

if ($entities.Count -eq 0) {
    Write-RunLog (
        "No organizations are eligible " +
        "for synchronization."
    )

    $finishedAt = Get-Date

    $emptySummary = [ordered]@{
        status = "NOTHING_TO_DO"
        discovered_count = 0
        processed_count = 0
        success_count = 0
        failed_count = 0
        started_at = $startedAt.ToString("o")
        finished_at = $finishedAt.ToString("o")
        duration_seconds = [math]::Round(
            (
                $finishedAt -
                $startedAt
            ).TotalSeconds,
            3
        )
        entities = @()
        log_path = $script:LogPath
    }

    Write-Host (
        $emptySummary |
        ConvertTo-Json `
            -Compress `
            -Depth 8
    )

    exit 0
}

Write-RunLog (
    "The complete organization list was prepared. " +
    "No synchronization job has been started yet."
)

foreach ($entity in $entities) {
    Write-RunLog (
        "Found organization: EntityId=" +
        $entity.EntityId +
        "; INN=" +
        $entity.Inn +
        "; Name=" +
        $entity.ShortName +
        "."
    )
}

foreach ($entity in $entities) {
    $entityStartedAt = Get-Date

    Write-RunLog ""

    Write-RunLog (
        "Starting synchronization for EntityId=" +
        $entity.EntityId +
        "; INN=" +
        $entity.Inn +
        "; Name=" +
        $entity.ShortName +
        "."
    )

    $parameters = @{
        EntityId = [int]$entity.EntityId
        StoreLocation = $StoreLocation
        TimeoutSeconds = $TimeoutSeconds
        EnvFile = $EnvFile
        LogDirectory = $entityLogDirectory
        RetryDelaySeconds = $RetryDelaySeconds
    }

    if (
        -not [string]::IsNullOrWhiteSpace(
            $DateFromUtc
        )
    ) {
        $parameters["DateFromUtc"] = $DateFromUtc
    }

    if (
        -not [string]::IsNullOrWhiteSpace(
            $DateToUtc
        )
    ) {
        $parameters["DateToUtc"] = $DateToUtc
    }

    if ($AllowPinPrompt.IsPresent) {
        $parameters["AllowPinPrompt"] = $true
    }

    if ($SkipEdo.IsPresent) {
        $parameters["SkipEdo"] = $true
    }

    if ($ForceEdo.IsPresent) {
        $parameters["ForceEdo"] = $true
    }

    if ($EdoFailFast.IsPresent) {
        $parameters["EdoFailFast"] = $true
    }

    if ($ContinueOnError.IsPresent) {
        $parameters["ContinueOnError"] = $true
    }

    try {
        & $singleEntityScript @parameters

        $entityFinishedAt = Get-Date

        [void]$results.Add(
            [pscustomobject]@{
                entity_id = [int]$entity.EntityId
                inn = [string]$entity.Inn
                short_name = [string]$entity.ShortName
                status = "SUCCESS"
                started_at = $entityStartedAt.ToString("o")
                finished_at = $entityFinishedAt.ToString("o")
                duration_seconds = [math]::Round(
                    (
                        $entityFinishedAt -
                        $entityStartedAt
                    ).TotalSeconds,
                    3
                )
                error_type = $null
                error_message = $null
            }
        )

        Write-RunLog (
            "Synchronization completed successfully " +
            "for EntityId=" +
            $entity.EntityId +
            "."
        )
    }
    catch {
        $entityFinishedAt = Get-Date

        [void]$results.Add(
            [pscustomobject]@{
                entity_id = [int]$entity.EntityId
                inn = [string]$entity.Inn
                short_name = [string]$entity.ShortName
                status = "FAILED"
                started_at = $entityStartedAt.ToString("o")
                finished_at = $entityFinishedAt.ToString("o")
                duration_seconds = [math]::Round(
                    (
                        $entityFinishedAt -
                        $entityStartedAt
                    ).TotalSeconds,
                    3
                )
                error_type = $_.Exception.GetType().Name
                error_message = $_.Exception.Message
            }
        )

        Write-RunLog (
            "Synchronization failed for EntityId=" +
            $entity.EntityId +
            "; Error=" +
            $_.Exception.Message
        )

        if ($StopOnEntityError.IsPresent) {
            Write-RunLog (
                "StopOnEntityError is enabled. " +
                "Remaining organizations will not be started."
            )

            break
        }
    }
}

$finishedAt = Get-Date

$successCount = @(
    $results |
    Where-Object {
        $_.status -eq "SUCCESS"
    }
).Count

$failedCount = @(
    $results |
    Where-Object {
        $_.status -eq "FAILED"
    }
).Count

if ($failedCount -eq 0) {
    $overallStatus = "SUCCESS"
}
elseif ($successCount -gt 0) {
    $overallStatus = "PARTIAL_SUCCESS"
}
else {
    $overallStatus = "FAILED"
}

$summary = [ordered]@{
    status = $overallStatus
    discovered_count = $entities.Count
    processed_count = $results.Count
    success_count = $successCount
    failed_count = $failedCount
    started_at = $startedAt.ToString("o")
    finished_at = $finishedAt.ToString("o")
    duration_seconds = [math]::Round(
        (
            $finishedAt -
            $startedAt
        ).TotalSeconds,
        3
    )
    entities = $results.ToArray()
    log_path = $script:LogPath
}

Write-RunLog ""

Write-RunLog (
    "Automatic synchronization finished. " +
    "Status=" +
    $overallStatus +
    "; Discovered=" +
    $entities.Count +
    "; Processed=" +
    $results.Count +
    "; Success=" +
    $successCount +
    "; Failed=" +
    $failedCount +
    "."
)

Write-Host (
    $summary |
    ConvertTo-Json `
        -Compress `
        -Depth 8
)

if ($failedCount -gt 0) {
    exit 1
}

exit 0