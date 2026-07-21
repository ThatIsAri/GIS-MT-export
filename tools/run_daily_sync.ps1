[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string[]]$ProductGroups = @(
        "beer",
        "water"
    ),

    [Parameter(Mandatory = $false)]
    [ValidateRange(1, 30)]
    [int]$LookbackDays = 3,

    [Parameter(Mandatory = $false)]
    [string]$DateFromUtc,

    [Parameter(Mandatory = $false)]
    [string]$DateToUtc,

    [Parameter(Mandatory = $false)]
    [ValidateRange(1, 1000)]
    [int]$Limit = 100,

    [Parameter(Mandatory = $false)]
    [ValidateRange(1, 10000)]
    [int]$MaxPages = 1000,

    [Parameter(Mandatory = $false)]
    [ValidateRange(0, 10000)]
    [int]$DetailsDelayMs = 100,

    [Parameter(Mandatory = $false)]
    [ValidateRange(1, 1000)]
    [int]$BatchSize = 50,

    [Parameter(Mandatory = $false)]
    [ValidateRange(0, 10000)]
    [int]$EdoDelayMs = 150,

    [Parameter(Mandatory = $false)]
    [string]$LogDirectory,

    [Parameter(Mandatory = $false)]
    [switch]$AllowPinPrompt,

    [Parameter(Mandatory = $false)]
    [switch]$ContinueOnError
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$script:LogPath = $null


function Write-RunLog {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    $timestamp = (Get-Date).ToString(
        "yyyy-MM-dd HH:mm:ss"
    )

    $line = (
        "[" +
        $timestamp +
        "] " +
        $Message
    )

    Write-Host $line

    Add-Content `
        -LiteralPath $script:LogPath `
        -Value $line `
        -Encoding UTF8
}


function Convert-ToUtcDateTime {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Value,

        [Parameter(Mandatory = $true)]
        [string]$ParameterName
    )

    try {
        $parsed = [DateTimeOffset]::Parse(
            $Value,
            [System.Globalization.CultureInfo]::InvariantCulture,
            [System.Globalization.DateTimeStyles]::AssumeUniversal
        )

        return $parsed.UtcDateTime
    }
    catch {
        throw (
            "Invalid value for " +
            $ParameterName +
            ": " +
            $Value +
            ". Use ISO 8601 format."
        )
    }
}


function Get-FreshTrueApiToken {
    param(
        [Parameter(Mandatory = $true)]
        [string]$TokenScript,

        [Parameter(Mandatory = $true)]
        [bool]$PermitPinPrompt
    )

    Write-RunLog `
        -Message "Requesting a fresh True API token."

    if ($PermitPinPrompt) {
        $tokenResult = @(
            & $TokenScript -AllowPinPrompt
        )
    }
    else {
        $tokenResult = @(
            & $TokenScript
        )
    }

    $tokenLines = @(
        $tokenResult |
        ForEach-Object {
            [string]$_
        } |
        Where-Object {
            -not [string]::IsNullOrWhiteSpace($_)
        }
    )

    if ($tokenLines.Count -ne 1) {
        throw (
            "Token script returned an unexpected " +
            "number of output values: " +
            $tokenLines.Count +
            "."
        )
    }

    $resolvedToken = $tokenLines[0].Trim()

    if ([string]::IsNullOrWhiteSpace($resolvedToken)) {
        throw "True API token is empty."
    }

    if (
        $resolvedToken.Contains("`r") -or
        $resolvedToken.Contains("`n")
    ) {
        throw (
            "True API token contains " +
            "line breaks."
        )
    }

    Write-RunLog `
        -Message (
            "True API token received. " +
            "Length: " +
            $resolvedToken.Length +
            "."
        )

    return $resolvedToken
}


function Invoke-ProductGroupSync {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Token,

        [Parameter(Mandatory = $true)]
        [string]$ProductGroup,

        [Parameter(Mandatory = $true)]
        [string]$ResolvedDateFrom,

        [Parameter(Mandatory = $true)]
        [string]$ResolvedDateTo
    )

    $dockerArguments = @(
        "compose",
        "--profile",
        "tools",
        "run",
        "--rm",
        "-T",
        "--entrypoint",
        "python",
        "sync-worker",
        "-u",
        "-m",
        "app.sync_pipeline",
        "--pg",
        $ProductGroup,
        "--date-from",
        $ResolvedDateFrom,
        "--date-to",
        $ResolvedDateTo,
        "--limit",
        [string]$Limit,
        "--max-pages",
        [string]$MaxPages,
        "--details-delay-ms",
        [string]$DetailsDelayMs,
        "--batch-size",
        [string]$BatchSize,
        "--edo-delay-ms",
        [string]$EdoDelayMs
    )

    Write-RunLog `
        -Message (
            "Starting product group: " +
            $ProductGroup +
            "."
        )

    Add-Content `
        -LiteralPath $script:LogPath `
        -Value (
            "============================================================"
        ) `
        -Encoding UTF8

    $exitCode = 1

    $previousErrorActionPreference = (
        $ErrorActionPreference
    )

    try {
        # Docker Compose writes normal container status
        # messages to stderr. They must not terminate
        # the PowerShell script.
        $ErrorActionPreference = "Continue"

        $Token |
        & docker @dockerArguments 2>&1 |
        ForEach-Object {
            $outputLine = [string]$_

            Write-Host $outputLine

            Add-Content `
                -LiteralPath $script:LogPath `
                -Value $outputLine `
                -Encoding UTF8
        }

        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = (
            $previousErrorActionPreference
        )
    }

    if ($null -eq $exitCode) {
        $exitCode = 1
    }

    Write-RunLog `
        -Message (
            "Product group " +
            $ProductGroup +
            " finished with exit code " +
            $exitCode +
            "."
        )

    return [int]$exitCode
}


$projectRoot = Split-Path `
    -Parent `
    $PSScriptRoot

$composeFile = Join-Path `
    $projectRoot `
    "compose.yaml"

$tokenScript = Join-Path `
    $PSScriptRoot `
    "get_true_api_token.ps1"


if (-not (Test-Path -LiteralPath $composeFile)) {
    throw (
        "compose.yaml not found: " +
        $composeFile
    )
}

if (-not (Test-Path -LiteralPath $tokenScript)) {
    throw (
        "Token script not found: " +
        $tokenScript
    )
}

$null = Get-Command `
    docker `
    -ErrorAction Stop


if ([string]::IsNullOrWhiteSpace($LogDirectory)) {
    $LogDirectory = Join-Path `
        $projectRoot `
        "logs\daily_sync"
}
elseif (-not [System.IO.Path]::IsPathRooted($LogDirectory)) {
    $LogDirectory = Join-Path `
        $projectRoot `
        $LogDirectory
}

$resolvedLogDirectory = [System.IO.Path]::GetFullPath(
    $LogDirectory
)

New-Item `
    -ItemType Directory `
    -Path $resolvedLogDirectory `
    -Force |
Out-Null

$runTimestamp = (Get-Date).ToString(
    "yyyyMMdd_HHmmss"
)

$script:LogPath = Join-Path `
    $resolvedLogDirectory `
    (
        "daily_sync_" +
        $runTimestamp +
        ".log"
    )


$hasDateFrom = -not [string]::IsNullOrWhiteSpace(
    $DateFromUtc
)

$hasDateTo = -not [string]::IsNullOrWhiteSpace(
    $DateToUtc
)

if ($hasDateFrom -ne $hasDateTo) {
    throw (
        "DateFromUtc and DateToUtc " +
        "must be provided together."
    )
}

if ($hasDateFrom) {
    $resolvedFromDate = Convert-ToUtcDateTime `
        -Value $DateFromUtc `
        -ParameterName "DateFromUtc"

    $resolvedToDate = Convert-ToUtcDateTime `
        -Value $DateToUtc `
        -ParameterName "DateToUtc"
}
else {
    $resolvedToDate = [DateTime]::UtcNow

    $resolvedFromDate = $resolvedToDate.AddDays(
        -$LookbackDays
    )
}

if ($resolvedFromDate -ge $resolvedToDate) {
    throw (
        "DateFromUtc must be earlier " +
        "than DateToUtc."
    )
}

$resolvedDateFromText = $resolvedFromDate.ToString(
    "yyyy-MM-ddTHH:mm:ssZ",
    [System.Globalization.CultureInfo]::InvariantCulture
)

$resolvedDateToText = $resolvedToDate.ToString(
    "yyyy-MM-ddTHH:mm:ssZ",
    [System.Globalization.CultureInfo]::InvariantCulture
)


$preparedProductGroups = @(
    $ProductGroups |
    ForEach-Object {
        $_.Trim().ToLowerInvariant()
    } |
    Where-Object {
        -not [string]::IsNullOrWhiteSpace($_)
    } |
    Select-Object -Unique
)

if ($preparedProductGroups.Count -eq 0) {
    throw (
        "At least one product group " +
        "must be specified."
    )
}

foreach ($productGroup in $preparedProductGroups) {
    if ($productGroup -notmatch '^[a-z0-9_-]+$') {
        throw (
            "Invalid product group: " +
            $productGroup
        )
    }
}


Write-RunLog `
    -Message "Daily GIS MT synchronization started."

Write-RunLog `
    -Message (
        "Project root: " +
        $projectRoot
    )

Write-RunLog `
    -Message (
        "Date range: " +
        $resolvedDateFromText +
        " - " +
        $resolvedDateToText +
        "."
    )

Write-RunLog `
    -Message (
        "Product groups: " +
        ($preparedProductGroups -join ", ") +
        "."
    )

Write-RunLog `
    -Message (
        "Log file: " +
        $script:LogPath
    )


$failedGroups = New-Object `
    System.Collections.Generic.List[string]

$fatalError = $null

Push-Location `
    $projectRoot

try {
    $token = Get-FreshTrueApiToken `
        -TokenScript $tokenScript `
        -PermitPinPrompt $AllowPinPrompt.IsPresent

    foreach ($productGroup in $preparedProductGroups) {
        $exitCode = Invoke-ProductGroupSync `
            -Token $token `
            -ProductGroup $productGroup `
            -ResolvedDateFrom $resolvedDateFromText `
            -ResolvedDateTo $resolvedDateToText

        if ($exitCode -eq 20) {
            Write-RunLog `
                -Message (
                    "Token was rejected for " +
                    $productGroup +
                    ". Refreshing token and retrying once."
                )

            $token = Get-FreshTrueApiToken `
                -TokenScript $tokenScript `
                -PermitPinPrompt $AllowPinPrompt.IsPresent

            $exitCode = Invoke-ProductGroupSync `
                -Token $token `
                -ProductGroup $productGroup `
                -ResolvedDateFrom $resolvedDateFromText `
                -ResolvedDateTo $resolvedDateToText
        }

        if ($exitCode -ne 0) {
            $failedGroups.Add(
                $productGroup
            )

            if (-not $ContinueOnError.IsPresent) {
                throw (
                    "Synchronization failed for " +
                    $productGroup +
                    " with exit code " +
                    $exitCode +
                    "."
                )
            }
        }
    }
}
catch {
    $fatalError = $_.Exception.Message
}
finally {
    Remove-Variable `
        token `
        -ErrorAction SilentlyContinue

    Pop-Location
}


if ($null -ne $fatalError) {
    Write-RunLog `
        -Message (
            "Daily synchronization failed: " +
            $fatalError
        )

    exit 1
}

if ($failedGroups.Count -gt 0) {
    Write-RunLog `
        -Message (
            "Daily synchronization completed " +
            "with errors. Failed groups: " +
            ($failedGroups -join ", ") +
            "."
        )

    exit 2
}

Write-RunLog `
    -Message (
        "Daily GIS MT synchronization " +
        "completed successfully."
    )

exit 0