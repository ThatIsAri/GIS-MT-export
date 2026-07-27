[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$DeviceName,

    [Parameter(Mandatory = $true)]
    [string]$EntitySearch,

    [Parameter(Mandatory = $false)]
    [string]$EnvFile,

    [Parameter(Mandatory = $false)]
    [string]$DkclPath = (
        "C:\Users\kudryavcev\Desktop\dkcl64.exe"
    ),

    [Parameter(Mandatory = $false)]
    [ValidateRange(5, 180)]
    [int]$CertificateWaitSeconds = 60,

    [Parameter(Mandatory = $false)]
    [ValidateRange(5, 300)]
    [int]$AuthTimeoutSeconds = 60,

    [Parameter(Mandatory = $false)]
    [switch]$AllowPinPrompt
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"


function Write-Step {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    Write-Host (
        "[{0}] {1}" -f
        (Get-Date -Format "yyyy-MM-dd HH:mm:ss"),
        $Message
    )
}


function Convert-HexUtf8 {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Hex
    )

    $prepared = $Hex.Trim()

    if (
        [string]::IsNullOrWhiteSpace(
            $prepared
        )
    ) {
        return ""
    }

    if (
        $prepared.Length % 2 -ne 0 -or
        $prepared -notmatch "^[0-9A-Fa-f]+$"
    ) {
        throw (
            "Invalid UTF-8 hex value: " +
            $prepared
        )
    }

    $bytes = New-Object byte[] (
        $prepared.Length / 2
    )

    for (
        $index = 0;
        $index -lt $bytes.Length;
        $index++
    ) {
        $bytes[$index] = [Convert]::ToByte(
            $prepared.Substring(
                $index * 2,
                2
            ),
            16
        )
    }

    return [System.Text.Encoding]::UTF8.GetString(
        $bytes
    )
}


function Normalize-Thumbprint {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Value
    )

    return (
        $Value -replace
        "[^0-9A-Fa-f]",
        ""
    ).ToUpperInvariant()
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

    $arguments = @(
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

    $previousPreference = $ErrorActionPreference

    try {
        $ErrorActionPreference = "Continue"

        $output = @(
            $Query |
                & docker @arguments 2>&1 |
                ForEach-Object {
                    [string]$_
                }
        )

        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }

    if ($null -eq $exitCode) {
        $exitCode = 1
    }

    if ($exitCode -ne 0) {
        throw (
            "MySQL query failed. ExitCode=" +
            $exitCode +
            "; Output=" +
            (
                $output -join " | "
            )
        )
    }

    return $output
}


function Get-DatabaseEntity {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ResolvedEnvFile
    )

    $query = @'
SELECT
    e.id,
    e.inn,
    HEX(e.short_name) AS short_name_hex,
    UPPER(
        REPLACE(
            REPLACE(
                c.thumbprint,
                ' ',
                ''
            ),
            ':',
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

    $rows = @(
        Invoke-MySqlQuery `
            -Query $query `
            -ResolvedEnvFile $ResolvedEnvFile
    )

    $entities = @()

    foreach ($row in $rows) {
        $prepared = (
            [string]$row
        ).Trim()

        if (
            [string]::IsNullOrWhiteSpace(
                $prepared
            )
        ) {
            continue
        }

        $parts = $prepared -split "`t", 6

        if ($parts.Count -ne 6) {
            throw (
                "Unexpected MySQL row: " +
                $prepared
            )
        }

        $entityId = 0

        if (
            -not [int]::TryParse(
                [string]$parts[0],
                [ref]$entityId
            )
        ) {
            throw (
                "Invalid entity id: " +
                [string]$parts[0]
            )
        }

        $entities += [pscustomobject]@{
            EntityId = $entityId

            Inn = (
                [string]$parts[1]
            ).Trim()

            ShortName = Convert-HexUtf8 `
                -Hex ([string]$parts[2])

            Thumbprint = Normalize-Thumbprint `
                -Value ([string]$parts[3])

            StoreLocation = (
                [string]$parts[4]
            ).Trim()

            StoreName = (
                [string]$parts[5]
            ).Trim()
        }
    }

    $searchValue = (
        $EntitySearch.Trim()
    ).ToUpperInvariant()

    $matches = @(
        $entities |
        Where-Object {
            (
                [string]$_.ShortName
            ).ToUpperInvariant().Contains(
                $searchValue
            )
        }
    )

    if ($matches.Count -eq 0) {
        throw (
            "No database entity matched EntitySearch=" +
            $EntitySearch +
            "."
        )
    }

    if ($matches.Count -gt 1) {
        $matchedNames = (
            $matches |
            ForEach-Object {
                [string]$_.ShortName
            }
        ) -join "; "

        throw (
            "More than one database entity matched. " +
            "Matches=" +
            $matchedNames
        )
    }

    $entity = $matches[0]

    if (
        $entity.Inn -notmatch
        "^\d{10}(\d{2})?$"
    ) {
        throw (
            "Invalid INN in database."
        )
    }

    if (
        $entity.Thumbprint -notmatch
        "^[0-9A-F]{40}$"
    ) {
        throw (
            "Invalid thumbprint in database."
        )
    }

    return $entity
}


function Invoke-DeviceAction {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet(
            "Status",
            "Connect",
            "Disconnect"
        )]
        [string]$DeviceAction,

        [Parameter(Mandatory = $true)]
        [string]$DeviceScript
    )

    $output = @(
        & $DeviceScript `
            -Action $DeviceAction `
            -DeviceName $DeviceName `
            -DkclPath $DkclPath
    )

    $jsonLine = (
        $output |
        ForEach-Object {
            [string]$_
        } |
        Where-Object {
            $line = (
                [string]$_
            ).Trim()

            $line.StartsWith(
                "{"
            ) -and
            $line.EndsWith(
                "}"
            )
        } |
        Select-Object -Last 1
    )

    if (
        [string]::IsNullOrWhiteSpace(
            [string]$jsonLine
        )
    ) {
        throw (
            "Device script returned no JSON. Output=" +
            (
                $output -join " | "
            )
        )
    }

    return (
        [string]$jsonLine |
        ConvertFrom-Json
    )
}


function Wait-ForCertificate {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Entity
    )

    $storePath = (
        "Cert:\" +
        $Entity.StoreLocation +
        "\" +
        $Entity.StoreName
    )

    if (
        -not (
            Test-Path `
                -Path $storePath
        )
    ) {
        throw (
            "Certificate store was not found: " +
            $storePath
        )
    }

    $deadline = (
        Get-Date
    ).AddSeconds(
        $CertificateWaitSeconds
    )

    while (
        (Get-Date) -lt
        $deadline
    ) {
        $certificate = (
            Get-ChildItem `
                -Path $storePath |
            Where-Object {
                (
                    Normalize-Thumbprint `
                        -Value (
                            [string]$_.Thumbprint
                        )
                ) -eq $Entity.Thumbprint
            } |
            Select-Object -First 1
        )

        if (
            $null -ne $certificate -and
            $certificate.HasPrivateKey
        ) {
            if (
                (
                    [string]$certificate.Subject
                ) -notmatch
                [regex]::Escape(
                    [string]$Entity.Inn
                )
            ) {
                throw (
                    "Certificate thumbprint matched, " +
                    "but INN was not found in Subject."
                )
            }

            if (
                $certificate.NotBefore -gt
                (Get-Date)
            ) {
                throw (
                    "Certificate is not valid yet."
                )
            }

            if (
                $certificate.NotAfter -le
                (Get-Date)
            ) {
                throw (
                    "Certificate has expired."
                )
            }

            return $certificate
        }

        Start-Sleep -Seconds 2
    }

    throw (
        "The expected certificate did not become available. " +
        "ExpectedThumbprint=" +
        $Entity.Thumbprint +
        "; ExpectedINN=" +
        $Entity.Inn +
        "."
    )
}


function Test-TrueApiAuthorization {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Entity,

        [Parameter(Mandatory = $true)]
        [string]$TokenScript,

        [Parameter(Mandatory = $true)]
        [string]$ResolvedEnvFile
    )

    $parameters = @{
        Inn = [string]$Entity.Inn

        CertificateThumbprint = (
            [string]$Entity.Thumbprint
        )

        StoreLocation = (
            [string]$Entity.StoreLocation
        )

        EnvFile = $ResolvedEnvFile

        TimeoutSeconds = (
            $AuthTimeoutSeconds
        )
    }

    if ($AllowPinPrompt.IsPresent) {
        $parameters[
            "AllowPinPrompt"
        ] = $true
    }

    $token = $null
    $output = $null
    $lines = $null

    try {
        $output = @(
            & $TokenScript @parameters
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
                " non-empty output lines."
            )
        }

        $token = (
            [string]$lines[0]
        ).Trim()

        if (
            [string]::IsNullOrWhiteSpace(
                $token
            )
        ) {
            throw (
                "True API returned an empty token."
            )
        }

        return $true
    }
    finally {
        $token = $null
        $output = $null
        $lines = $null
    }
}


$projectRoot = Split-Path `
    -Parent `
    $PSScriptRoot

Set-Location `
    -LiteralPath $projectRoot

$deviceScript = Join-Path `
    -Path $PSScriptRoot `
    -ChildPath "diskontrol_device.ps1"

$tokenScript = Join-Path `
    -Path $PSScriptRoot `
    -ChildPath "get_true_api_token.ps1"

if (
    -not (
        Test-Path `
            -LiteralPath $deviceScript `
            -PathType Leaf
    )
) {
    throw (
        "Device script not found: " +
        $deviceScript
    )
}

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


$connectedByThisRun = $false
$exitCode = 0
$finalStatus = "FAILED"
$finalMessage = ""

try {
    Write-Step "Reading the permitted entity from MySQL."

    $entity = Get-DatabaseEntity `
        -ResolvedEnvFile $EnvFile

    Write-Step (
        "Database entity found. EntityId=" +
        $entity.EntityId +
        "; INN=" +
        $entity.Inn +
        "; ShortName=" +
        $entity.ShortName +
        "; Thumbprint=" +
        $entity.Thumbprint +
        "."
    )

    Write-Step (
        "Checking only the exact DistKontrol device: " +
        $DeviceName +
        "."
    )

    $statusResult = Invoke-DeviceAction `
        -DeviceAction "Status" `
        -DeviceScript $deviceScript

    Write-Step (
        "Device status=" +
        [string]$statusResult.status +
        "; Address=" +
        [string]$statusResult.device_address +
        "."
    )

    if (
        (
            [string]$statusResult.status
        ) -eq "BUSY"
    ) {
        $finalStatus = "SKIPPED_BUSY"

        $finalMessage = (
            "The device is used by another user. " +
            "No disconnect command was sent."
        )

        Write-Step $finalMessage
    }
    else {
        if (
            (
                [string]$statusResult.status
            ) -eq "FREE"
        ) {
            Write-Step "Connecting the selected device."

            $connectResult = Invoke-DeviceAction `
                -DeviceAction "Connect" `
                -DeviceScript $deviceScript

            Write-Step (
                "Connect result=" +
                [string]$connectResult.status +
                "."
            )

            if (
                (
                    [string]$connectResult.status
                ) -eq "CONNECTED"
            ) {
                $connectedByThisRun = $true
            }
            elseif (
                (
                    [string]$connectResult.status
                ) -eq "ALREADY_CONNECTED"
            ) {
                $connectedByThisRun = $false
            }
            elseif (
                (
                    [string]$connectResult.status
                ) -in @(
                    "BUSY",
                    "BUSY_TIMEOUT",
                    "RACE_BUSY"
                )
            ) {
                $finalStatus = "SKIPPED_BUSY"

                $finalMessage = (
                    "The device became busy. " +
                    "No disconnect command was sent."
                )

                Write-Step $finalMessage
            }
            else {
                throw (
                    "Device connection failed. Status=" +
                    [string]$connectResult.status +
                    "; Message=" +
                    [string]$connectResult.message
                )
            }
        }
        elseif (
            (
                [string]$statusResult.status
            ) -eq "CONNECTED_BY_CURRENT_USER"
        ) {
            Write-Step (
                "The device was already connected " +
                "before this test."
            )

            $connectedByThisRun = $false
        }
        else {
            throw (
                "Unsupported device status: " +
                [string]$statusResult.status
            )
        }

        if ($finalStatus -ne "SKIPPED_BUSY") {
            Write-Step (
                "Waiting for the exact certificate " +
                "configured in MySQL."
            )

            $certificate = Wait-ForCertificate `
                -Entity $entity

            Write-Step (
                "Certificate verified. Subject=" +
                $certificate.Subject +
                "; ValidTo=" +
                $certificate.NotAfter.ToString(
                    "yyyy-MM-dd HH:mm:ss"
                ) +
                "."
            )

            Write-Step (
                "Requesting a True API token. " +
                "The token will not be printed or stored."
            )

            $null = Test-TrueApiAuthorization `
                -Entity $entity `
                -TokenScript $tokenScript `
                -ResolvedEnvFile $EnvFile

            $finalStatus = "SUCCESS"

            $finalMessage = (
                "The selected organization was authenticated " +
                "successfully."
            )

            Write-Step $finalMessage
        }
    }
}
catch {
    $exitCode = 1
    $finalStatus = "FAILED"
    $finalMessage = $_.Exception.Message

    Write-Step (
        "Test failed. Error=" +
        $finalMessage
    )
}
finally {
    if ($connectedByThisRun) {
        try {
            Write-Step (
                "Disconnecting only the device " +
                "connected by this test."
            )

            $disconnectResult = Invoke-DeviceAction `
                -DeviceAction "Disconnect" `
                -DeviceScript $deviceScript

            Write-Step (
                "Disconnect result=" +
                [string]$disconnectResult.status +
                "."
            )

            if (
                (
                    [string]$disconnectResult.status
                ) -notin @(
                    "DISCONNECTED",
                    "ALREADY_DISCONNECTED"
                )
            ) {
                throw (
                    "Unexpected disconnect status: " +
                    [string]$disconnectResult.status
                )
            }
        }
        catch {
            $exitCode = 1

            Write-Step (
                "Disconnect failed. Error=" +
                $_.Exception.Message
            )
        }
    }
    else {
        Write-Step (
            "No disconnect command is required."
        )
    }
}


$result = [ordered]@{
    status = $finalStatus
    message = $finalMessage
    device_name = $DeviceName
    entity_search = $EntitySearch
    connected_by_this_run = $connectedByThisRun
    timestamp = (
        Get-Date
    ).ToString(
        "o"
    )
}

Write-Host ""

Write-Output (
    $result |
    ConvertTo-Json `
        -Compress `
        -Depth 5
)

exit $exitCode