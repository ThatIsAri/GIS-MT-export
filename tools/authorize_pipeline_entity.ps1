[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$DeviceName,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^\d{10}(\d{2})?$')]
    [string]$Inn,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9A-Fa-f]{40}$')]
    [string]$CertificateThumbprint,

    [Parameter(Mandatory = $false)]
    [ValidateSet('CurrentUser', 'LocalMachine')]
    [string]$StoreLocation = 'CurrentUser',

    [Parameter(Mandatory = $false)]
    [string]$StoreName = 'My',

    [Parameter(Mandatory = $false)]
    [string]$EnvFile,

    [Parameter(Mandatory = $false)]
    [string]$DkclPath = 'C:\Users\kudryavcev\Desktop\dkcl64.exe',

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
$ErrorActionPreference = 'Stop'

$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = $utf8NoBom
[Console]::OutputEncoding = $utf8NoBom
$OutputEncoding = $utf8NoBom

$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'

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
        $Value -replace '[^0-9A-Fa-f]', ''
    ).ToUpperInvariant()
}


function Get-LastJsonObject {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [object[]]$Lines,

        [Parameter(Mandatory = $true)]
        [string]$CommandName
    )

    $jsonLine = $null

    foreach ($item in $Lines) {
        $line = ([string]$item).Trim()

        if (
            $line.StartsWith('{') -and
            $line.EndsWith('}')
        ) {
            $jsonLine = $line
        }
    }

    if (
        [string]::IsNullOrWhiteSpace(
            [string]$jsonLine
        )
    ) {
        throw (
            $CommandName +
            ' did not return a JSON object.'
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
            ' returned invalid JSON.'
        )
    }
}


$projectRoot = Split-Path `
    -Parent `
    $PSScriptRoot

Set-Location `
    -LiteralPath $projectRoot

$deviceScript = Join-Path `
    -Path $PSScriptRoot `
    -ChildPath 'diskontrol_device.ps1'

$tokenScript = Join-Path `
    -Path $PSScriptRoot `
    -ChildPath 'get_true_api_token.ps1'

if (
    [string]::IsNullOrWhiteSpace(
        $EnvFile
    )
) {
    $EnvFile = Join-Path `
        -Path $projectRoot `
        -ChildPath '.env'
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

foreach ($requiredPath in @(
    $deviceScript,
    $tokenScript,
    $EnvFile,
    $DkclPath
)) {
    if (
        -not (
            Test-Path `
                -LiteralPath $requiredPath `
                -PathType Leaf
        )
    ) {
        throw (
            'Required file was not found: ' +
            $requiredPath
        )
    }
}


function Invoke-DeviceAction {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet('Status', 'Connect', 'Disconnect')]
        [string]$Action
    )

    $output = @(
        & $deviceScript `
            -Action $Action `
            -DeviceName $DeviceName `
            -DkclPath $DkclPath `
            2>&1
    )

    return Get-LastJsonObject `
        -Lines $output `
        -CommandName (
            'diskontrol_device.ps1 ' +
            $Action
        )
}


function Get-ExactCertificate {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Thumbprint
    )

    $storePath = (
        'Cert:\' +
        $StoreLocation +
        '\' +
        $StoreName
    )

    if (
        -not (
            Test-Path `
                -LiteralPath $storePath
        )
    ) {
        return $null
    }

    return (
        Get-ChildItem `
            -LiteralPath $storePath `
            -ErrorAction Stop |
        Where-Object {
            (
                Normalize-Thumbprint `
                    -Value ([string]$_.Thumbprint)
            ) -eq $Thumbprint
        } |
        Select-Object -First 1
    )
}


function Wait-ExactCertificate {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Thumbprint
    )

    $deadline = (Get-Date).AddSeconds(
        $CertificateWaitSeconds
    )

    do {
        $certificate = Get-ExactCertificate `
            -Thumbprint $Thumbprint

        if ($null -ne $certificate) {
            return $certificate
        }

        Start-Sleep -Milliseconds 500
    }
    while ((Get-Date) -lt $deadline)

    return $null
}


function Request-TrueApiToken {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Thumbprint
    )

    $parameters = @{
        Inn = $Inn
        CertificateThumbprint = $Thumbprint
        StoreLocation = $StoreLocation
        EnvFile = $EnvFile
        TimeoutSeconds = $AuthTimeoutSeconds
    }

    if ($AllowPinPrompt.IsPresent) {
        $parameters['AllowPinPrompt'] = $true
    }

    $lines = @(
        & $tokenScript @parameters |
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
            'Token script returned ' +
            $lines.Count +
            ' non-empty lines.'
        )
    }

    $resolvedToken = $lines[0].Trim()

    if (
        [string]::IsNullOrWhiteSpace(
            $resolvedToken
        )
    ) {
        throw 'True API token is empty.'
    }

    if (
        $resolvedToken.Contains("`r") -or
        $resolvedToken.Contains("`n")
    ) {
        throw 'True API token contains line breaks.'
    }

    return $resolvedToken
}


$normalizedThumbprint = Normalize-Thumbprint `
    -Value $CertificateThumbprint

$result = [ordered]@{
    status = 'ERROR'
    message = ''
    device_name = $DeviceName
    device_address = $null
    inn = $Inn
    thumbprint = $normalizedThumbprint
    connected_by_this_run = $false
    certificate = $null
    token = $null
    timestamp = (Get-Date).ToString('o')
}

$exitCode = 10
$connectedByThisRun = $false
$continueWork = $true
$token = $null
$certificate = $null

try {
    $statusResult = Invoke-DeviceAction `
        -Action 'Status'

    $deviceStatus = (
        [string]$statusResult.status
    ).ToUpperInvariant()

    $result.device_address = (
        [string]$statusResult.device_address
    )

    switch ($deviceStatus) {
        'FREE' {
        }

        'BUSY' {
            $result.status = 'SKIPPED_BUSY'

            $result.message = (
                'The device is used by another user. ' +
                'No USE or STOP USING command was sent.'
            )

            $exitCode = 2
            $continueWork = $false
        }

        'NOT_AVAILABLE' {
            $result.status = 'SKIPPED_NOT_AVAILABLE'

            $result.message = (
                'The exact device profile is not present ' +
                'in the current LIST result.'
            )

            $exitCode = 3
            $continueWork = $false
        }

        'CONNECTED_BY_CURRENT_USER' {
            $result.status = 'SKIPPED_ALREADY_CONNECTED'

            $result.message = (
                'The device was connected before this run. ' +
                'It was not used or disconnected.'
            )

            $exitCode = 4
            $continueWork = $false
        }

        'ALREADY_CONNECTED' {
            $result.status = 'SKIPPED_ALREADY_CONNECTED'

            $result.message = (
                'The device was connected before this run. ' +
                'It was not used or disconnected.'
            )

            $exitCode = 4
            $continueWork = $false
        }

        default {
            throw (
                'Unexpected DistKontrol status: ' +
                $deviceStatus
            )
        }
    }

    if ($continueWork) {
        $connectResult = Invoke-DeviceAction `
            -Action 'Connect'

        $connectStatus = (
            [string]$connectResult.status
        ).ToUpperInvariant()

        if ($connectStatus -eq 'BUSY') {
            $result.status = 'SKIPPED_BUSY'

            $result.message = (
                'The device became busy before connection. ' +
                'No STOP USING command was sent.'
            )

            $exitCode = 2
            $continueWork = $false
        }
        elseif ($connectStatus -eq 'RACE_BUSY') {
            $result.status = 'SKIPPED_BUSY'

            $result.message = (
                'Another user connected the device first. ' +
                'No STOP USING command was sent.'
            )

            $exitCode = 2
            $continueWork = $false
        }
        elseif ($connectStatus -ne 'CONNECTED') {
            throw (
                'Unexpected connect status: ' +
                $connectStatus
            )
        }
        else {
            $connectedByThisRun = $true
            $result.connected_by_this_run = $true

            $result.device_address = (
                [string]$connectResult.device_address
            )
        }
    }

    if ($continueWork) {
        $certificate = Wait-ExactCertificate `
            -Thumbprint $normalizedThumbprint

        if ($null -eq $certificate) {
            throw (
                'The exact certificate was not found within ' +
                $CertificateWaitSeconds +
                ' seconds. Thumbprint=' +
                $normalizedThumbprint +
                '.'
            )
        }

        if (-not $certificate.HasPrivateKey) {
            throw 'The exact certificate has no private key.'
        }

        $currentTime = Get-Date

        if (
            $certificate.NotBefore -gt $currentTime -or
            $certificate.NotAfter -le $currentTime
        ) {
            throw 'The exact certificate is not currently valid.'
        }

        if (
            ([string]$certificate.Subject) -notmatch
            [regex]::Escape($Inn)
        ) {
            throw (
                'The configured INN was not found in ' +
                'the exact certificate Subject.'
            )
        }

        $token = Request-TrueApiToken `
            -Thumbprint $normalizedThumbprint

        $result.certificate = [ordered]@{
            thumbprint = $normalizedThumbprint
            certificate_inn = $Inn
            subject_name = [string]$certificate.Subject
            serial_number = [string]$certificate.SerialNumber
            issuer_name = [string]$certificate.Issuer

            valid_from = (
                $certificate.NotBefore
            ).ToUniversalTime().ToString(
                'o'
            )

            valid_to = (
                $certificate.NotAfter
            ).ToUniversalTime().ToString(
                'o'
            )

            store_location = $StoreLocation
            store_name = $StoreName
            provider_name = $null
            diskontrol_profile = $DeviceName
            has_private_key = [bool]$certificate.HasPrivateKey
        }

        $result.status = 'SUCCESS'

        $result.message = (
            'The exact certificate was verified and ' +
            'a True API token was obtained.'
        )

        $result.token = $token
        $exitCode = 0
    }
}
catch {
    $result.status = 'ERROR'
    $result.message = $_.Exception.Message
    $exitCode = 10
}
finally {
    if ($connectedByThisRun) {
        try {
            $disconnectResult = Invoke-DeviceAction `
                -Action 'Disconnect'

            $disconnectStatus = (
                [string]$disconnectResult.status
            ).ToUpperInvariant()

            if ($disconnectStatus -ne 'DISCONNECTED') {
                throw (
                    'Unexpected disconnect status: ' +
                    $disconnectStatus
                )
            }
        }
        catch {
            if ($result.status -eq 'SUCCESS') {
                $result.status = 'ERROR'

                $result.message = (
                    'The token was obtained, but the device ' +
                    'connected by this run could not be disconnected: ' +
                    $_.Exception.Message
                )

                $result.token = $null
                $exitCode = 10
            }
            else {
                $result.message = (
                    $result.message +
                    ' Disconnect error for the device connected ' +
                    'by this run: ' +
                    $_.Exception.Message
                )
            }
        }
    }
}

$result.timestamp = (Get-Date).ToString('o')

Write-Output (
    $result |
    ConvertTo-Json `
        -Compress `
        -Depth 8
)

$token = $null
$certificate = $null
$result.token = $null

exit $exitCode