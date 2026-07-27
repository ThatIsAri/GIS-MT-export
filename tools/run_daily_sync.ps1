[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateRange(1, 2147483647)]
    [int]$EntityId,

    [Parameter(Mandatory = $false)]
    [string]$CertificateThumbprint,

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
    [switch]$ContinueOnError
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

        if (-not [string]::IsNullOrWhiteSpace($script:LogPath)) {
            Add-Content `
                -LiteralPath $script:LogPath `
                -Value "" `
                -Encoding UTF8
        }

        return
    }

    $line = (
        "[" +
        (Get-Date).ToString(
            "yyyy-MM-dd HH:mm:ss"
        ) +
        "] " +
        $Message
    )

    Write-Host $line

    if (-not [string]::IsNullOrWhiteSpace($script:LogPath)) {
        Add-Content `
            -LiteralPath $script:LogPath `
            -Value $line `
            -Encoding UTF8
    }
}


function ConvertFrom-MixedJsonOutput {
    param(
        [Parameter(Mandatory = $true)]
        [object[]]$Lines,

        [Parameter(Mandatory = $true)]
        [string]$CommandName
    )

    $text = (
        $Lines |
        ForEach-Object {
            [string]$_
        }
    ) -join [Environment]::NewLine

    $startIndex = $text.IndexOf("{")
    $endIndex = $text.LastIndexOf("}")

    if ($startIndex -lt 0 -or $endIndex -lt $startIndex) {
        throw (
            $CommandName +
            " did not return a JSON object."
        )
    }

    $jsonText = $text.Substring(
        $startIndex,
        $endIndex - $startIndex + 1
    )

    try {
        return (
            $jsonText |
            ConvertFrom-Json
        )
    }
    catch {
        throw (
            $CommandName +
            " returned invalid JSON."
        )
    }
}


function Get-CompactJsonObject {
    param(
        [Parameter(Mandatory = $true)]
        [object[]]$Lines,

        [Parameter(Mandatory = $true)]
        [string]$CommandName
    )

    $jsonLine = (
        $Lines |
        ForEach-Object {
            [string]$_
        } |
        Where-Object {
            $preparedLine = $_.Trim()

            $preparedLine.StartsWith("{") -and
            $preparedLine.EndsWith("}")
        } |
        Select-Object -Last 1
    )

    if ([string]::IsNullOrWhiteSpace([string]$jsonLine)) {
        throw (
            $CommandName +
            " did not return compact JSON."
        )
    }

    try {
        return (
            [string]$jsonLine |
            ConvertFrom-Json
        )
    }
    catch {
        throw (
            $CommandName +
            " returned invalid compact JSON."
        )
    }
}


function Invoke-DockerWithInput {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,

        [Parameter(Mandatory = $true)]
        [string]$InputText,

        [Parameter(Mandatory = $true)]
        [string]$CommandName
    )

    $previousPreference = $ErrorActionPreference

    $output = New-Object `
        'System.Collections.Generic.List[string]'

    try {
        $ErrorActionPreference = "Continue"

        $InputText |
        & docker @Arguments 2>&1 |
        ForEach-Object {
            $line = [string]$_

            [void]$output.Add(
                $line
            )

            Write-RunLog `
                -Message $line
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
        Output = [string[]]$output.ToArray()
    }
}


function Invoke-DockerWithoutInput {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,

        [Parameter(Mandatory = $true)]
        [string]$CommandName
    )

    $previousPreference = $ErrorActionPreference

    $output = New-Object `
        'System.Collections.Generic.List[string]'

    try {
        $ErrorActionPreference = "Continue"

        & docker @Arguments 2>&1 |
        ForEach-Object {
            $line = [string]$_

            [void]$output.Add(
                $line
            )

            Write-RunLog `
                -Message $line
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
        Output = [string[]]$output.ToArray()
    }
}


function Get-TrueApiToken {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ScriptPath,

        [Parameter(Mandatory = $true)]
        [string]$Inn,

        [Parameter(Mandatory = $true)]
        [string]$Thumbprint,

        [Parameter(Mandatory = $true)]
        [string]$CertificateStoreLocation,

        [Parameter(Mandatory = $true)]
        [string]$ResolvedEnvFile,

        [Parameter(Mandatory = $true)]
        [int]$ResolvedTimeoutSeconds,

        [Parameter(Mandatory = $true)]
        [bool]$PermitPinPrompt
    )

    $parameters = @{
        Inn = $Inn
        CertificateThumbprint = $Thumbprint
        StoreLocation = $CertificateStoreLocation
        EnvFile = $ResolvedEnvFile
        TimeoutSeconds = $ResolvedTimeoutSeconds
    }

    if ($PermitPinPrompt) {
        $parameters["AllowPinPrompt"] = $true
    }

    $output = @(
        & $ScriptPath @parameters
    )

    $lines = @(
        $output |
        ForEach-Object {
            [string]$_
        } |
        Where-Object {
            -not [string]::IsNullOrWhiteSpace(
                [string]$_
            )
        }
    )

    if ($lines.Count -ne 1) {
        throw (
            "Token script returned " +
            $lines.Count +
            " non-empty lines instead of one."
        )
    }

    $token = $lines[0].Trim()

    if ([string]::IsNullOrWhiteSpace($token)) {
        throw "True API token is empty."
    }

    if ($token.Contains("`r") -or $token.Contains("`n")) {
        throw (
            "True API token contains line breaks."
        )
    }

    return $token
}


function Get-RabbitRetryDelaySeconds {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ResolvedEnvFile,

        [Parameter(Mandatory = $true)]
        [int]$ExplicitValue
    )

    if ($ExplicitValue -gt 0) {
        return $ExplicitValue
    }

    $rawValue = (
        [Environment]::GetEnvironmentVariable(
            "RABBITMQ_RETRY_DELAY_SECONDS",
            "Process"
        )
    )

    if (
        [string]::IsNullOrWhiteSpace($rawValue) -and
        (Test-Path -LiteralPath $ResolvedEnvFile)
    ) {
        $matchingLine = (
            Get-Content `
                -LiteralPath $ResolvedEnvFile |
            Where-Object {
                $_ -match (
                    '^\s*' +
                    [regex]::Escape(
                        "RABBITMQ_RETRY_DELAY_SECONDS"
                    ) +
                    '\s*='
                )
            } |
            Select-Object -Last 1
        )

        if (-not [string]::IsNullOrWhiteSpace([string]$matchingLine)) {
            $separatorIndex = (
                [string]$matchingLine
            ).IndexOf("=")

            if ($separatorIndex -ge 0) {
                $rawValue = (
                    [string]$matchingLine
                ).Substring(
                    $separatorIndex + 1
                ).Trim()
            }
        }
    }

    if ([string]::IsNullOrWhiteSpace($rawValue)) {
        return 300
    }

    if (
        $rawValue.Length -ge 2 -and
        (
            (
                $rawValue.StartsWith('"') -and
                $rawValue.EndsWith('"')
            ) -or
            (
                $rawValue.StartsWith("'") -and
                $rawValue.EndsWith("'")
            )
        )
    ) {
        $rawValue = $rawValue.Substring(
            1,
            $rawValue.Length - 2
        )
    }

    try {
        $parsedValue = [int]$rawValue
    }
    catch {
        throw (
            "RABBITMQ_RETRY_DELAY_SECONDS " +
            "must be an integer."
        )
    }

    if ($parsedValue -lt 1 -or $parsedValue -gt 86400) {
        throw (
            "RABBITMQ_RETRY_DELAY_SECONDS " +
            "must be between 1 and 86400."
        )
    }

    return $parsedValue
}


$projectRoot = Split-Path `
    -Parent `
    $PSScriptRoot

Set-Location `
    -LiteralPath $projectRoot

$metadataScript = Join-Path `
    $PSScriptRoot `
    "sync_legal_entity_metadata.ps1"

$tokenScript = Join-Path `
    $PSScriptRoot `
    "get_true_api_token.ps1"

$composeFile = Join-Path `
    $projectRoot `
    "compose.yaml"

foreach (
    $requiredPath
    in @(
        $metadataScript,
        $tokenScript,
        $composeFile
    )
) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw (
            "Required file was not found: " +
            $requiredPath
        )
    }
}

$null = Get-Command `
    docker `
    -ErrorAction Stop

if ([string]::IsNullOrWhiteSpace($EnvFile)) {
    $EnvFile = Join-Path `
        $projectRoot `
        ".env"
}
else {
    $EnvFile = (
        Resolve-Path `
            -LiteralPath $EnvFile `
            -ErrorAction Stop
    ).Path
}

if (-not (Test-Path -LiteralPath $EnvFile)) {
    throw (
        "Environment file was not found: " +
        $EnvFile
    )
}

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

$LogDirectory = (
    [System.IO.Path]::GetFullPath(
        $LogDirectory
    )
)

New-Item `
    -ItemType Directory `
    -Path $LogDirectory `
    -Force |
Out-Null

$timestamp = (
    Get-Date
).ToString(
    "yyyyMMdd_HHmmss"
)

$script:LogPath = Join-Path `
    $LogDirectory `
    (
        "entity_" +
        $EntityId +
        "_" +
        $timestamp +
        ".log"
    )

$resolvedRetryDelaySeconds = (
    Get-RabbitRetryDelaySeconds `
        -ResolvedEnvFile $EnvFile `
        -ExplicitValue $RetryDelaySeconds
)

$retryWaitSeconds = (
    $resolvedRetryDelaySeconds + 5
)

$token = $null
$metadataPayload = $null
$metadataPayloadJson = $null
$metadataPayloadBase64 = $null

try {
    Write-RunLog (
        "RabbitMQ legal entity synchronization started. " +
        "EntityId=" +
        $EntityId +
        "."
    )

    Write-RunLog (
        "RabbitMQ retry delay: " +
        $resolvedRetryDelaySeconds +
        " seconds."
    )

    $discoveryParameters = @{
        EntityId = $EntityId
        StoreLocation = $StoreLocation
        TimeoutSeconds = $TimeoutSeconds
        EnvFile = $EnvFile
        DiscoveryOnly = $true
    }

    if (-not [string]::IsNullOrWhiteSpace($CertificateThumbprint)) {
        $discoveryParameters["CertificateThumbprint"] = (
            $CertificateThumbprint
        )
    }

    Write-RunLog "Discovering certificate."

    $discoveryOutput = @(
        & $metadataScript @discoveryParameters
    )

    $discovery = ConvertFrom-MixedJsonOutput `
        -Lines $discoveryOutput `
        -CommandName "Certificate discovery"

    $inn = (
        [string]$discovery.inn
    ).Trim()

    $certificate = $discovery.certificate

    $thumbprint = (
        [string]$certificate.thumbprint
    ).Trim()

    $resolvedStoreLocation = (
        [string]$certificate.store_location
    ).Trim()

    if ($inn -notmatch '^\d{10}(\d{2})?$') {
        throw (
            "Certificate discovery returned " +
            "an invalid INN."
        )
    }

    if ($thumbprint -notmatch '^[0-9A-Fa-f]{40}$') {
        throw (
            "Certificate discovery returned " +
            "an invalid thumbprint."
        )
    }

    if ($resolvedStoreLocation -notin @("CurrentUser", "LocalMachine")) {
        throw (
            "Certificate discovery returned " +
            "an invalid store location."
        )
    }

    Write-RunLog (
        "Certificate selected. Store=" +
        $resolvedStoreLocation +
        "\My."
    )

    Write-RunLog (
        "Requesting fresh True API token."
    )

    $token = Get-TrueApiToken `
        -ScriptPath $tokenScript `
        -Inn $inn `
        -Thumbprint $thumbprint `
        -CertificateStoreLocation $resolvedStoreLocation `
        -ResolvedEnvFile $EnvFile `
        -ResolvedTimeoutSeconds $TimeoutSeconds `
        -PermitPinPrompt $AllowPinPrompt.IsPresent

    Write-RunLog (
        "True API token received."
    )

    $metadataPayload = [ordered]@{
        token = $token
        certificate = $certificate
    }

    $metadataPayloadJson = (
        $metadataPayload |
        ConvertTo-Json `
            -Compress `
            -Depth 6
    )

    $metadataPayloadBase64 = (
        [Convert]::ToBase64String(
            $utf8NoBom.GetBytes(
                $metadataPayloadJson
            )
        )
    )

    $metadataArguments = @(
        "compose",
        "--ansi",
        "never",
        "--profile",
        "tools",
        "run",
        "--rm",
        "-T",
        "--entrypoint",
        "python",
        "sync-worker",
        "-m",
        "app.legal_entity_metadata",
        "sync",
        "--entity-id",
        [string]$EntityId
    )

    Write-RunLog (
        "Synchronizing participant metadata " +
        "and product groups."
    )

    $metadataResult = Invoke-DockerWithInput `
        -Arguments $metadataArguments `
        -InputText $metadataPayloadBase64 `
        -CommandName "Metadata synchronization"

    if ($metadataResult.ExitCode -ne 0) {
        throw (
            "Metadata synchronization failed " +
            "with exit code " +
            $metadataResult.ExitCode +
            "."
        )
    }

    $metadataJson = Get-CompactJsonObject `
        -Lines $metadataResult.Output `
        -CommandName "Metadata synchronization"

    Write-RunLog (
        "Metadata synchronized. " +
        "ProductGroups=" +
        $metadataJson.product_group_count +
        "; Added=" +
        $metadataJson.added_product_group_count +
        "; Unavailable=" +
        $metadataJson.unavailable_product_group_count +
        "."
    )

    $publishArguments = @(
        "compose",
        "--ansi",
        "never",
        "--profile",
        "tools",
        "run",
        "--rm",
        "-T",
        "--entrypoint",
        "python",
        "sync-worker",
        "-m",
        "app.rabbitmq_jobs",
        "--entity-id",
        [string]$EntityId,
        "--requested-by",
        "run_daily_sync.ps1"
    )

    if (-not [string]::IsNullOrWhiteSpace($DateFromUtc)) {
        $publishArguments += @(
            "--date-from",
            $DateFromUtc
        )
    }

    if (-not [string]::IsNullOrWhiteSpace($DateToUtc)) {
        $publishArguments += @(
            "--date-to",
            $DateToUtc
        )
    }

    if ($SkipEdo) {
        $publishArguments += "--skip-edo"
    }

    if ($ForceEdo) {
        $publishArguments += "--force-edo"
    }

    if ($EdoFailFast) {
        $publishArguments += "--edo-fail-fast"
    }

    if ($ContinueOnError) {
        $publishArguments += "--continue-on-error"
    }

    Write-RunLog (
        "Publishing synchronization job."
    )

    $publishResult = Invoke-DockerWithoutInput `
        -Arguments $publishArguments `
        -CommandName "RabbitMQ job publication"

    if ($publishResult.ExitCode -ne 0) {
        throw (
            "RabbitMQ job publication failed " +
            "with exit code " +
            $publishResult.ExitCode +
            "."
        )
    }

    $publishedJob = Get-CompactJsonObject `
        -Lines $publishResult.Output `
        -CommandName "RabbitMQ job publication"

    if ([string]$publishedJob.status -ne "PUBLISHED") {
        throw (
            "RabbitMQ publisher returned " +
            "an unexpected status."
        )
    }

    if ([int]$publishedJob.legal_entity_id -ne $EntityId) {
        throw (
            "Published job belongs to another " +
            "legal entity."
        )
    }

    $jobId = (
        [string]$publishedJob.job_id
    ).Trim()

    Write-RunLog (
        "Job published. JobId=" +
        $jobId +
        "; Queue=" +
        $publishedJob.queue +
        "."
    )

    $workerArguments = @(
        "compose",
        "--ansi",
        "never",
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
        "app.rabbitmq_worker",
        "--entity-id",
        [string]$EntityId,
        "--once"
    )

    $workerCycle = 0

    while ($true) {
        $workerCycle += 1

        Write-RunLog (
            "Starting RabbitMQ worker cycle " +
            $workerCycle +
            "."
        )

        $workerResult = Invoke-DockerWithInput `
            -Arguments $workerArguments `
            -InputText $token `
            -CommandName "RabbitMQ worker"

        $workerExitCode = (
            [int]$workerResult.ExitCode
        )

        Write-RunLog (
            "RabbitMQ worker cycle " +
            $workerCycle +
            " finished with exit code " +
            $workerExitCode +
            "."
        )

        if ($workerExitCode -eq 0) {
            $workerJson = Get-CompactJsonObject `
                -Lines $workerResult.Output `
                -CommandName "RabbitMQ worker"

            if ([string]$workerJson.status -ne "SUCCESS") {
                throw (
                    "RabbitMQ worker returned exit code 0 " +
                    "with an unexpected status: " +
                    $workerJson.status +
                    "."
                )
            }

            if (
                -not [string]::IsNullOrWhiteSpace(
                    [string]$workerJson.job_id
                ) -and
                [string]$workerJson.job_id -ne $jobId
            ) {
                throw (
                    "RabbitMQ worker processed another job. " +
                    "Expected JobId=" +
                    $jobId +
                    "; actual JobId=" +
                    $workerJson.job_id +
                    "."
                )
            }

            Write-RunLog (
                "Synchronization job completed successfully. " +
                "JobId=" +
                $jobId +
                "."
            )

            break
        }

        if ($workerExitCode -eq 21) {
            throw (
                "True API authorization failed and " +
                "the retry limit was exhausted. " +
                "The job was moved to dead-letter."
            )
        }

        if ($workerExitCode -eq 31) {
            throw (
                "The synchronization retry limit " +
                "was exhausted. " +
                "The job was moved to dead-letter."
            )
        }

        if ($workerExitCode -ne 20 -and $workerExitCode -ne 30) {
            throw (
                "RabbitMQ worker failed with " +
                "unexpected exit code " +
                $workerExitCode +
                "."
            )
        }

        if ($workerExitCode -eq 20) {
            Write-RunLog (
                "The token was rejected. " +
                "The job is waiting in the retry queue."
            )
        }
        else {
            Write-RunLog (
                "The job failed temporarily and " +
                "is waiting in the retry queue."
            )
        }

        Write-RunLog (
            "Waiting " +
            $retryWaitSeconds +
            " seconds before the next worker cycle."
        )

        $token = $null

        Start-Sleep `
            -Seconds $retryWaitSeconds

        Write-RunLog (
            "Requesting a new True API token " +
            "for the retry cycle."
        )

        $token = Get-TrueApiToken `
            -ScriptPath $tokenScript `
            -Inn $inn `
            -Thumbprint $thumbprint `
            -CertificateStoreLocation $resolvedStoreLocation `
            -ResolvedEnvFile $EnvFile `
            -ResolvedTimeoutSeconds $TimeoutSeconds `
            -PermitPinPrompt $AllowPinPrompt.IsPresent

        Write-RunLog (
            "Fresh True API token received."
        )
    }

    Write-RunLog (
        "RabbitMQ legal entity synchronization " +
        "completed successfully."
    )

    Write-RunLog (
        "Log file: " +
        $script:LogPath
    )
}
finally {
    $token = $null
    $metadataPayload = $null
    $metadataPayloadJson = $null
    $metadataPayloadBase64 = $null
}