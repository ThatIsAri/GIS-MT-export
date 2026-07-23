[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateRange(1, 2147483647)]
    [int]$EntityId,

    [Parameter(Mandatory = $false)]
    [string]$CertificateThumbprint,

    [Parameter(Mandatory = $false)]
    [ValidateSet("Any", "CurrentUser", "LocalMachine")]
    [string]$StoreLocation = "Any",

    [Parameter(Mandatory = $false)]
    [ValidateRange(5, 300)]
    [int]$TimeoutSeconds = 60,

    [Parameter(Mandatory = $false)]
    [string]$EnvFile,

    [Parameter(Mandatory = $false)]
    [switch]$AllowPinPrompt,

    [Parameter(Mandatory = $false)]
    [switch]$DiscoveryOnly
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


function Normalize-Thumbprint {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Value
    )

    return (
        (
            $Value -replace '[^0-9A-Fa-f]',
            ''
        ).ToUpperInvariant()
    )
}


function Get-JsonLine {
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
            $line = $_.Trim()

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
            $CommandName +
            " did not return JSON."
        )
    }

    return [string]$jsonLine
}


function Get-TargetCard {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Id
    )

    $output = @(
        & docker compose `
            --ansi never `
            --profile tools `
            run `
            --rm `
            -T `
            --entrypoint python `
            sync-worker `
            -m app.legal_entity_metadata `
            target `
            --entity-id $Id
    )

    if ($LASTEXITCODE -ne 0) {
        throw (
            "Failed to read legal entity card id=" +
            $Id +
            "."
        )
    }

    $jsonLine = Get-JsonLine `
        -Lines $output `
        -CommandName "target"

    try {
        return (
            $jsonLine |
            ConvertFrom-Json
        )
    }
    catch {
        throw (
            "Target command returned invalid JSON."
        )
    }
}


function Test-CertificateInn {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Certificate,

        [Parameter(Mandatory = $true)]
        [string]$Inn
    )

    $subject = [string]$Certificate.Subject

    return (
        $subject -match
        [regex]::Escape(
            $Inn
        )
    )
}


function Find-Certificate {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Inn,

        [Parameter(Mandatory = $true)]
        [string[]]$Locations,

        [Parameter(Mandatory = $false)]
        [AllowNull()]
        [string]$RequestedThumbprint
    )

    $requested = $null

    if (
        -not [string]::IsNullOrWhiteSpace(
            $RequestedThumbprint
        )
    ) {
        $requested = Normalize-Thumbprint `
            -Value $RequestedThumbprint

        if ($requested.Length -ne 40) {
            throw (
                "Certificate thumbprint must contain " +
                "40 hexadecimal characters."
            )
        }
    }

    $now = Get-Date
    $matches = @()

    foreach ($location in $Locations) {
        $storePath = (
            "Cert:\" +
            $location +
            "\My"
        )

        if (
            -not (
                Test-Path `
                    -LiteralPath $storePath
            )
        ) {
            continue
        }

        $certificates = @(
            Get-ChildItem `
                -LiteralPath $storePath `
                -ErrorAction Stop
        )

        foreach ($certificate in $certificates) {
            $thumbprint = Normalize-Thumbprint `
                -Value (
                    [string]$certificate.Thumbprint
                )

            if ($null -ne $requested) {
                if ($thumbprint -ne $requested) {
                    continue
                }
            }

            $innMatches = Test-CertificateInn `
                -Certificate $certificate `
                -Inn $Inn

            if (-not $innMatches) {
                continue
            }

            $matches += [pscustomobject]@{
                Certificate = $certificate
                StoreLocation = $location
                Thumbprint = $thumbprint
            }
        }
    }

    if ($matches.Count -eq 0) {
        throw (
            "No certificate was found for INN " +
            $Inn +
            "."
        )
    }

    $usable = @(
        $matches |
        Where-Object {
            $_.Certificate.HasPrivateKey -and
            $_.Certificate.NotBefore -le $now -and
            $_.Certificate.NotAfter -gt $now
        } |
        Sort-Object `
            -Property @{
                Expression = {
                    $_.Certificate.NotAfter
                }

                Descending = $true
            }
    )

    if ($usable.Count -eq 0) {
        throw (
            "Certificates were found for INN " +
            $Inn +
            ", but none is valid and has a private key."
        )
    }

    return $usable[0]
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
        $parameters[
            "AllowPinPrompt"
        ] = $true
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
                $_
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

    if (
        [string]::IsNullOrWhiteSpace(
            $token
        )
    ) {
        throw (
            "True API token is empty."
        )
    }

    if (
        $token.Contains(
            "`r"
        ) -or
        $token.Contains(
            "`n"
        )
    ) {
        throw (
            "True API token contains line breaks."
        )
    }

    return $token
}


$projectRoot = Split-Path `
    -Parent `
    $PSScriptRoot

Set-Location `
    -LiteralPath $projectRoot


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
    $EnvFile = (
        Resolve-Path `
            -LiteralPath $EnvFile `
            -ErrorAction Stop
    ).Path
}


Write-Host (
    "Reading legal entity card..."
)

$target = Get-TargetCard `
    -Id $EntityId

$inn = (
    [string]$target.inn
).Trim()


if ($inn -notmatch '^\d{10}(\d{2})?$') {
    throw (
        "The legal entity card contains " +
        "an invalid INN."
    )
}


if (
    -not [bool]$target.true_api_enabled
) {
    throw (
        "True API is disabled " +
        "for this legal entity."
    )
}


if (
    -not [bool]$target.auto_discover_certificate
) {
    throw (
        "Automatic certificate discovery " +
        "is disabled."
    )
}


if (
    -not [bool]$target.auto_discover_product_groups
) {
    throw (
        "Automatic product-group discovery " +
        "is disabled."
    )
}


Write-Host (
    "Entity ID: " +
    $EntityId
)

Write-Host (
    "INN: " +
    $inn
)


$locations = @()

if ($StoreLocation -eq "CurrentUser") {
    $locations = @(
        "CurrentUser"
    )
}
elseif ($StoreLocation -eq "LocalMachine") {
    $locations = @(
        "LocalMachine"
    )
}
else {
    $locations = @(
        "CurrentUser",
        "LocalMachine"
    )
}


Write-Host (
    "Searching certificate..."
)

$selected = Find-Certificate `
    -Inn $inn `
    -Locations $locations `
    -RequestedThumbprint $CertificateThumbprint


$certificate = $selected.Certificate

$resolvedStoreLocation = (
    [string]$selected.StoreLocation
)

$thumbprint = (
    [string]$selected.Thumbprint
)

$validFrom = (
    $certificate.NotBefore.ToUniversalTime().ToString(
        "o"
    )
)

$validTo = (
    $certificate.NotAfter.ToUniversalTime().ToString(
        "o"
    )
)


Write-Host (
    "Certificate: " +
    $thumbprint
)

Write-Host (
    "Store: " +
    $resolvedStoreLocation +
    "\My"
)

Write-Host (
    "Valid to: " +
    $certificate.NotAfter.ToString(
        "yyyy-MM-dd HH:mm:ss"
    )
)

Write-Host (
    "Private key: " +
    $certificate.HasPrivateKey
)


$certificatePayload = [ordered]@{
    thumbprint = $thumbprint
    certificate_inn = $inn
    subject_name = [string]$certificate.Subject
    serial_number = [string]$certificate.SerialNumber
    issuer_name = [string]$certificate.Issuer
    valid_from = $validFrom
    valid_to = $validTo
    store_location = $resolvedStoreLocation
    store_name = "My"
    provider_name = $null
    diskontrol_profile = $null
    has_private_key = [bool]$certificate.HasPrivateKey
}


if ($DiscoveryOnly) {
    $discoveryResult = [ordered]@{
        entity_id = $EntityId
        inn = $inn
        certificate = $certificatePayload
    }

    $discoveryResult |
    ConvertTo-Json `
        -Depth 5

    return
}


$tokenScript = Join-Path `
    $PSScriptRoot `
    "get_true_api_token.ps1"


if (
    -not (
        Test-Path `
            -LiteralPath $tokenScript
    )
) {
    throw (
        "Token script was not found: " +
        $tokenScript
    )
}


$token = $null
$payload = $null
$payloadJson = $null
$payloadBase64 = $null


try {
    Write-Host (
        "Requesting True API token..."
    )

    $token = Get-TrueApiToken `
        -ScriptPath $tokenScript `
        -Inn $inn `
        -Thumbprint $thumbprint `
        -CertificateStoreLocation `
            $resolvedStoreLocation `
        -ResolvedEnvFile $EnvFile `
        -ResolvedTimeoutSeconds `
            $TimeoutSeconds `
        -PermitPinPrompt `
            $AllowPinPrompt.IsPresent

    $payload = [ordered]@{
        token = $token
        certificate = $certificatePayload
    }

    $payloadJson = (
        $payload |
        ConvertTo-Json `
            -Compress `
            -Depth 6
    )

    $payloadBytes = (
        $utf8NoBom.GetBytes(
            $payloadJson
        )
    )

    $payloadBase64 = (
        [Convert]::ToBase64String(
            $payloadBytes
        )
    )

    Write-Host (
        "Synchronizing GIS MT metadata..."
    )

    $syncOutput = @(
        $payloadBase64 |
        & docker compose `
            --ansi never `
            --profile tools `
            run `
            --rm `
            -T `
            --entrypoint python `
            sync-worker `
            -m app.legal_entity_metadata `
            sync `
            --entity-id $EntityId
    )

    if ($LASTEXITCODE -ne 0) {
        throw (
            "Metadata synchronization failed."
        )
    }

    $resultJson = Get-JsonLine `
        -Lines $syncOutput `
        -CommandName "sync"

    try {
        $result = (
            $resultJson |
            ConvertFrom-Json
        )
    }
    catch {
        throw (
            "Sync command returned invalid JSON."
        )
    }

    Write-Host ""
    Write-Host (
        "Metadata synchronization completed."
    )

    Write-Host (
        "Participant: " +
        $result.participant_name
    )

    Write-Host (
        "Status: " +
        $result.participant_status
    )

    Write-Host (
        "Certificate ID: " +
        $result.certificate_id
    )

    Write-Host (
        "Product groups: " +
        $result.product_group_count
    )

    Write-Host (
        "Added: " +
        $result.added_product_group_count
    )

    Write-Host (
        "Confirmed: " +
        $result.confirmed_product_group_count
    )

    Write-Host (
        "Unavailable: " +
        $result.unavailable_product_group_count
    )

    $result
}
finally {
    $token = $null
    $payload = $null
    $payloadJson = $null
    $payloadBytes = $null
    $payloadBase64 = $null
}