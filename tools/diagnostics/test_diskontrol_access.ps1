[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$EnvFile,

    [Parameter(Mandatory = $false)]
    [ValidateRange(5, 300)]
    [int]$TimeoutSeconds = 60,

    [Parameter(Mandatory = $false)]
    [ValidateRange(1, 100)]
    [int]$ExpectedEntityCount = 4,

    [Parameter(Mandatory = $false)]
    [ValidateRange(1, 600)]
    [int]$MutexTimeoutSeconds = 120,

    [Parameter(Mandatory = $false)]
    [switch]$AllowPinPrompt
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

$script:SigningMutexName = "CZ_ASYNC_DISKKONTROL_AUTH"


function Write-Step {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    Write-Host (
        "[" +
        (Get-Date -Format "yyyy-MM-dd HH:mm:ss") +
        "] " +
        $Message
    )
}


function Normalize-Thumbprint {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Value
    )

    return (
        $Value -replace "[^0-9A-Fa-f]", ""
    ).ToUpperInvariant()
}


function Invoke-NativeCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,

        [Parameter(Mandatory = $false)]
        [string[]]$Arguments = @(),

        [Parameter(Mandatory = $false)]
        [AllowNull()]
        [string]$StandardInput = $null
    )

    $previousPreference = $ErrorActionPreference
    $outputLines = @()
    $exitCode = 1

    try {
        $ErrorActionPreference = "Continue"

        if ($null -eq $StandardInput) {
            $outputLines = @(
                & $FilePath @Arguments 2>&1 |
                    ForEach-Object {
                        [string]$_
                    }
            )
        }
        else {
            $outputLines = @(
                $StandardInput |
                    & $FilePath @Arguments 2>&1 |
                    ForEach-Object {
                        [string]$_
                    }
            )
        }

        if ($null -ne $LASTEXITCODE) {
            $exitCode = [int]$LASTEXITCODE
        }
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }

    return [pscustomobject]@{
        ExitCode = $exitCode
        Output = $outputLines
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
        "compose",
        "--ansi",
        "never",
        "--env-file",
        $ResolvedEnvFile,
        "exec",
        "-T",
        "mysql",
        "sh",
        "-c",
        $containerCommand
    )

    return Invoke-NativeCommand `
        -FilePath "docker" `
        -Arguments $dockerArguments `
        -StandardInput $Query
}


function Get-ConfiguredEntities {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ResolvedEnvFile
    )

    $query = @'
SELECT
    e.id,
    e.inn,
    REPLACE(
        REPLACE(
            REPLACE(
                e.short_name,
                CHAR(9),
                ' '
            ),
            CHAR(10),
            ' '
        ),
        CHAR(13),
        ' '
    ) AS short_name,
    UPPER(
        REPLACE(
            c.thumbprint,
            ' ',
            ''
        )
    ) AS thumbprint,
    COALESCE(
        c.store_location,
        'CurrentUser'
    ) AS store_location,
    COALESCE(
        c.store_name,
        'My'
    ) AS store_name
FROM legal_entity AS e
INNER JOIN legal_entity_integration_config AS cfg
    ON cfg.legal_entity_id = e.id
INNER JOIN legal_entity_certificate AS c
    ON c.id = (
        SELECT c2.id
        FROM legal_entity_certificate AS c2
        WHERE c2.legal_entity_id = e.id
          AND c2.is_active = 1
        ORDER BY c2.id DESC
        LIMIT 1
    )
WHERE e.status IN (
    'SETUP',
    'ACTIVE'
)
  AND cfg.true_api_enabled = 1
ORDER BY e.id;
'@

    $queryResult = Invoke-MySqlQuery `
        -Query $query `
        -ResolvedEnvFile $ResolvedEnvFile

    if ($queryResult.ExitCode -ne 0) {
        foreach ($line in $queryResult.Output) {
            Write-Host (
                [string]$line
            )
        }

        throw (
            "MySQL query failed with exit code " +
            $queryResult.ExitCode +
            "."
        )
    }

    $entities = @()

    foreach ($line in $queryResult.Output) {
        $preparedLine = (
            [string]$line
        ).Trim()

        if (
            [string]::IsNullOrWhiteSpace(
                $preparedLine
            )
        ) {
            continue
        }

        $parts = $preparedLine -split "`t", 6

        if ($parts.Count -ne 6) {
            throw (
                "Unexpected MySQL row: " +
                $preparedLine
            )
        }

        $entityId = 0

        $entityIdParsed = [int]::TryParse(
            [string]$parts[0],
            [ref]$entityId
        )

        if (-not $entityIdParsed) {
            throw (
                "Invalid entity id in MySQL row: " +
                $preparedLine
            )
        }

        $entity = [pscustomobject]@{
            EntityId = $entityId

            Inn = (
                [string]$parts[1]
            ).Trim()

            ShortName = (
                [string]$parts[2]
            ).Trim()

            Thumbprint = Normalize-Thumbprint `
                -Value ([string]$parts[3])

            StoreLocation = (
                [string]$parts[4]
            ).Trim()

            StoreName = (
                [string]$parts[5]
            ).Trim()
        }

        if (
            $entity.Inn -notmatch
            "^\d{10}(\d{2})?$"
        ) {
            throw (
                "Invalid INN for entity id=" +
                $entity.EntityId +
                "."
            )
        }

        if (
            $entity.Thumbprint -notmatch
            "^[0-9A-F]{40}$"
        ) {
            throw (
                "Invalid thumbprint for entity id=" +
                $entity.EntityId +
                "."
            )
        }

        if (
            $entity.StoreLocation -ne "CurrentUser" -and
            $entity.StoreLocation -ne "LocalMachine"
        ) {
            throw (
                "Invalid store location for entity id=" +
                $entity.EntityId +
                "."
            )
        }

        if (
            [string]::IsNullOrWhiteSpace(
                $entity.StoreName
            )
        ) {
            throw (
                "Empty store name for entity id=" +
                $entity.EntityId +
                "."
            )
        }

        $entities += $entity
    }

    return $entities
}


function Get-RegisteredCertificate {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Entity
    )

    $certificatePath = (
        "Cert:\" +
        $Entity.StoreLocation +
        "\" +
        $Entity.StoreName
    )

    if (
        -not (
            Test-Path `
                -Path $certificatePath
        )
    ) {
        throw (
            "Certificate store not found: " +
            $certificatePath +
            "."
        )
    }

    $certificate = (
        Get-ChildItem `
            -Path $certificatePath |
        Where-Object {
            (
                Normalize-Thumbprint `
                    -Value ([string]$_.Thumbprint)
            ) -eq $Entity.Thumbprint
        } |
        Select-Object `
            -First 1
    )

    if ($null -eq $certificate) {
        throw (
            "Certificate not found in " +
            $certificatePath +
            ". Thumbprint=" +
            $Entity.Thumbprint +
            "."
        )
    }

    if (-not $certificate.HasPrivateKey) {
        throw (
            "Certificate has no registered private key."
        )
    }

    $now = Get-Date

    if ($certificate.NotBefore -gt $now) {
        throw (
            "Certificate is not valid yet."
        )
    }

    if ($certificate.NotAfter -le $now) {
        throw (
            "Certificate has expired."
        )
    }

    if (
        (
            [string]$certificate.Subject
        ) -notmatch
        [regex]::Escape(
            [string]$Entity.Inn
        )
    ) {
        throw (
            "Entity INN was not found in certificate Subject."
        )
    }

    return $certificate
}


function Test-TrueApiToken {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Entity,

        [Parameter(Mandatory = $true)]
        [string]$TokenScript,

        [Parameter(Mandatory = $true)]
        [string]$ResolvedEnvFile,

        [Parameter(Mandatory = $true)]
        [int]$ResolvedTimeoutSeconds,

        [Parameter(Mandatory = $true)]
        [int]$ResolvedMutexTimeoutSeconds,

        [Parameter(Mandatory = $true)]
        [bool]$PermitPinPrompt
    )

    $mutex = New-Object `
        -TypeName System.Threading.Mutex `
        -ArgumentList $false, $script:SigningMutexName

    $mutexAcquired = $false
    $token = $null
    $tokenOutput = $null
    $tokenLines = $null

    try {
        Write-Step (
            "Waiting for the signing mutex."
        )

        try {
            $mutexAcquired = $mutex.WaitOne(
                [TimeSpan]::FromSeconds(
                    $ResolvedMutexTimeoutSeconds
                )
            )
        }
        catch {
            $caughtException = $_.Exception
            $innerException = $caughtException.InnerException

            if (
                $caughtException -is
                    [System.Threading.AbandonedMutexException] -or
                $innerException -is
                    [System.Threading.AbandonedMutexException]
            ) {
                $mutexAcquired = $true
            }
            else {
                throw
            }
        }

        if (-not $mutexAcquired) {
            throw (
                "Signing mutex timeout after " +
                $ResolvedMutexTimeoutSeconds +
                " seconds."
            )
        }

        Write-Step (
            "Signing mutex acquired. " +
            "Requesting True API token."
        )

        $tokenParameters = @{
            Inn = [string]$Entity.Inn

            CertificateThumbprint = (
                [string]$Entity.Thumbprint
            )

            StoreLocation = (
                [string]$Entity.StoreLocation
            )

            EnvFile = $ResolvedEnvFile

            TimeoutSeconds = (
                $ResolvedTimeoutSeconds
            )
        }

        if ($PermitPinPrompt) {
            $tokenParameters[
                "AllowPinPrompt"
            ] = $true
        }

        $tokenOutput = @(
            & $TokenScript @tokenParameters
        )

        $tokenLines = @(
            $tokenOutput |
            ForEach-Object {
                [string]$_
            } |
            Where-Object {
                -not [string]::IsNullOrWhiteSpace(
                    [string]$_
                )
            }
        )

        if ($tokenLines.Count -ne 1) {
            throw (
                "Token script returned " +
                $tokenLines.Count +
                " non-empty output lines."
            )
        }

        $token = $tokenLines[0].Trim()

        if (
            [string]::IsNullOrWhiteSpace(
                $token
            )
        ) {
            throw (
                "True API returned an empty token."
            )
        }

        if (
            $token.Contains("`r") -or
            $token.Contains("`n")
        ) {
            throw (
                "True API token contains line breaks."
            )
        }

        Write-Step (
            "True API token received successfully."
        )
    }
    finally {
        $token = $null
        $tokenOutput = $null
        $tokenLines = $null

        if ($mutexAcquired) {
            try {
                $mutex.ReleaseMutex()
            }
            catch {
            }
        }

        $mutex.Dispose()
    }
}


$toolsRoot = Split-Path `
    -Parent `
    $PSScriptRoot

$projectRoot = Split-Path `
    -Parent `
    $toolsRoot

Set-Location `
    -LiteralPath $projectRoot

$tokenScript = Join-Path `
    -Path $toolsRoot `
    -ChildPath "get_true_api_token.ps1"

if (
    -not (
        Test-Path `
            -LiteralPath $tokenScript `
            -PathType Leaf
    )
) {
    throw (
        "Token script not found: " +
        $tokenScript
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
        -Path $projectRoot `
        -ChildPath ".env"
}
elseif (
    -not [System.IO.Path]::IsPathRooted(
        $EnvFile
    )
) {
    $EnvFile = Join-Path `
        -Path $projectRoot `
        -ChildPath $EnvFile
}

$EnvFile = [System.IO.Path]::GetFullPath(
    $EnvFile
)

if (
    -not (
        Test-Path `
            -LiteralPath $EnvFile `
            -PathType Leaf
    )
) {
    throw (
        "Environment file not found: " +
        $EnvFile
    )
}

Write-Step (
    "Starting MySQL."
)

$startupArguments = @(
    "compose",
    "--ansi",
    "never",
    "--env-file",
    $EnvFile,
    "up",
    "-d",
    "--wait",
    "mysql"
)

$startupResult = Invoke-NativeCommand `
    -FilePath "docker" `
    -Arguments $startupArguments

foreach ($line in $startupResult.Output) {
    Write-Host (
        [string]$line
    )
}

if ($startupResult.ExitCode -ne 0) {
    throw (
        "MySQL startup failed with exit code " +
        $startupResult.ExitCode +
        "."
    )
}

Write-Step (
    "Reading configured entities from MySQL."
)

$entities = @(
    Get-ConfiguredEntities `
        -ResolvedEnvFile $EnvFile
)

Write-Step (
    "Configured entities found: " +
    $entities.Count +
    "."
)

foreach ($entity in $entities) {
    Write-Step (
        "Entity: id=" +
        $entity.EntityId +
        "; INN=" +
        $entity.Inn +
        "; name=" +
        $entity.ShortName +
        "."
    )
}

if (
    $entities.Count -ne
    $ExpectedEntityCount
) {
    throw (
        "Expected entity count: " +
        $ExpectedEntityCount +
        "; actual: " +
        $entities.Count +
        "."
    )
}

$results = @()

foreach ($entity in $entities) {
    Write-Host ""

    Write-Step (
        "Testing entity id=" +
        $entity.EntityId +
        "; INN=" +
        $entity.Inn +
        "; name=" +
        $entity.ShortName +
        "."
    )

    $startedAt = Get-Date
    $certificate = $null

    try {
        $certificate = (
            Get-RegisteredCertificate `
                -Entity $entity
        )

        Write-Step (
            "Certificate found. ValidTo=" +
            $certificate.NotAfter.ToString(
                "yyyy-MM-dd HH:mm:ss"
            ) +
            "; HasPrivateKey=" +
            $certificate.HasPrivateKey +
            "."
        )

        Test-TrueApiToken `
            -Entity $entity `
            -TokenScript $tokenScript `
            -ResolvedEnvFile $EnvFile `
            -ResolvedTimeoutSeconds $TimeoutSeconds `
            -ResolvedMutexTimeoutSeconds $MutexTimeoutSeconds `
            -PermitPinPrompt $AllowPinPrompt.IsPresent

        $finishedAt = Get-Date

        $results += [pscustomobject]@{
            entity_id = [int]$entity.EntityId
            inn = [string]$entity.Inn
            short_name = [string]$entity.ShortName
            status = "SUCCESS"

            duration_seconds = [math]::Round(
                (
                    $finishedAt -
                    $startedAt
                ).TotalSeconds,
                3
            )

            error_type = $null
            error_message = $null
        }

        Write-Step (
            "Entity test completed successfully."
        )
    }
    catch {
        $finishedAt = Get-Date

        $results += [pscustomobject]@{
            entity_id = [int]$entity.EntityId
            inn = [string]$entity.Inn
            short_name = [string]$entity.ShortName
            status = "FAILED"

            duration_seconds = [math]::Round(
                (
                    $finishedAt -
                    $startedAt
                ).TotalSeconds,
                3
            )

            error_type = (
                $_.Exception.GetType().Name
            )

            error_message = (
                $_.Exception.Message
            )
        }

        Write-Step (
            "Entity test failed. Type=" +
            $_.Exception.GetType().Name +
            "; Error=" +
            $_.Exception.Message
        )
    }
    finally {
        $certificate = $null
    }
}

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

Write-Host ""

Write-Step (
    "Test finished. Status=" +
    $overallStatus +
    "; Success=" +
    $successCount +
    "; Failed=" +
    $failedCount +
    "."
)

$summary = [ordered]@{
    status = $overallStatus
    expected_count = $ExpectedEntityCount
    processed_count = $results.Count
    success_count = $successCount
    failed_count = $failedCount
    entities = $results
}

Write-Host (
    $summary |
    ConvertTo-Json `
        -Compress `
        -Depth 6
)

if ($failedCount -gt 0) {
    exit 1
}

exit 0