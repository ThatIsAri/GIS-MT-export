[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$Inn,

    [Parameter(Mandatory = $false)]
    [string]$CertificateThumbprint,

    [Parameter(Mandatory = $false)]
    [ValidateSet("CurrentUser", "LocalMachine")]
    [string]$StoreLocation,

    [Parameter(Mandatory = $false)]
    [string]$TrueApiBaseUrl,

    [Parameter(Mandatory = $false)]
    [string]$EnvFile,

    [Parameter(Mandatory = $false)]
    [ValidateRange(5, 300)]
    [int]$TimeoutSeconds = 60,

    [Parameter(Mandatory = $false)]
    [switch]$AllowPinPrompt,

    [Parameter(Mandatory = $false)]
    [switch]$ListCertificates
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Security

[System.Net.ServicePointManager]::SecurityProtocol = `
    [System.Net.SecurityProtocolType]::Tls12


function Read-DotEnvFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $result = @{}

    if (-not (Test-Path -LiteralPath $Path)) {
        return $result
    }

    foreach ($rawLine in Get-Content -LiteralPath $Path) {
        $line = $rawLine.Trim()

        if (
            [string]::IsNullOrWhiteSpace($line) -or
            $line.StartsWith("#")
        ) {
            continue
        }

        $separatorIndex = $line.IndexOf("=")

        if ($separatorIndex -lt 1) {
            continue
        }

        $name = $line.Substring(
            0,
            $separatorIndex
        ).Trim()

        $value = $line.Substring(
            $separatorIndex + 1
        ).Trim()

        if (
            $value.Length -ge 2 -and
            (
                (
                    $value.StartsWith('"') -and
                    $value.EndsWith('"')
                ) -or
                (
                    $value.StartsWith("'") -and
                    $value.EndsWith("'")
                )
            )
        ) {
            $value = $value.Substring(
                1,
                $value.Length - 2
            )
        }

        if (-not [string]::IsNullOrWhiteSpace($name)) {
            $result[$name] = $value
        }
    }

    return $result
}


function Get-ConfigValue {
    param(
        [Parameter(Mandatory = $false)]
        [AllowNull()]
        [string]$ExplicitValue,

        [Parameter(Mandatory = $true)]
        [string]$EnvironmentName,

        [Parameter(Mandatory = $true)]
        [hashtable]$DotEnv,

        [Parameter(Mandatory = $false)]
        [AllowNull()]
        [string]$DefaultValue
    )

    if (
        -not [string]::IsNullOrWhiteSpace(
            $ExplicitValue
        )
    ) {
        return $ExplicitValue.Trim()
    }

    $processValue = [Environment]::GetEnvironmentVariable(
        $EnvironmentName,
        "Process"
    )

    if (
        -not [string]::IsNullOrWhiteSpace(
            $processValue
        )
    ) {
        return $processValue.Trim()
    }

    if ($DotEnv.ContainsKey($EnvironmentName)) {
        $fileValue = [string]$DotEnv[$EnvironmentName]

        if (
            -not [string]::IsNullOrWhiteSpace(
                $fileValue
            )
        ) {
            return $fileValue.Trim()
        }
    }

    return $DefaultValue
}


function Normalize-Thumbprint {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Value
    )

    return (
        $Value -replace '[^0-9a-fA-F]', ''
    ).ToUpperInvariant()
}


function Get-StoreLocationValue {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Value
    )

    if ($Value -eq "LocalMachine") {
        return [System.Security.Cryptography.X509Certificates.StoreLocation]::LocalMachine
    }

    return [System.Security.Cryptography.X509Certificates.StoreLocation]::CurrentUser
}


function Get-SigningCertificates {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Location
    )

    $locationValue = Get-StoreLocationValue `
        -Value $Location

    $store = New-Object `
        System.Security.Cryptography.X509Certificates.X509Store(
            "My",
            $locationValue
        )

    try {
        $store.Open(
            [System.Security.Cryptography.X509Certificates.OpenFlags]::ReadOnly -bor
            [System.Security.Cryptography.X509Certificates.OpenFlags]::OpenExistingOnly
        )

        $now = Get-Date

        return @(
            $store.Certificates |
            Where-Object {
                $_.HasPrivateKey -and
                $_.NotBefore -le $now -and
                $_.NotAfter -gt $now
            } |
            ForEach-Object {
                New-Object `
                    System.Security.Cryptography.X509Certificates.X509Certificate2(
                        $_
                    )
            }
        )
    }
    finally {
        $store.Close()
    }
}


function Select-SigningCertificate {
    param(
        [Parameter(Mandatory = $true)]
        [object[]]$Certificates,

        [Parameter(Mandatory = $false)]
        [AllowNull()]
        [string]$Thumbprint,

        [Parameter(Mandatory = $false)]
        [AllowNull()]
        [string]$OrganizationInn
    )

    if (
        -not [string]::IsNullOrWhiteSpace(
            $Thumbprint
        )
    ) {
        $normalizedThumbprint = Normalize-Thumbprint `
            -Value $Thumbprint

        $certificate = $Certificates |
            Where-Object {
                (
                    Normalize-Thumbprint `
                        -Value $_.Thumbprint
                ) -eq $normalizedThumbprint
            } |
            Select-Object -First 1

        if ($null -eq $certificate) {
            throw (
                "Certificate not found in the selected store. " +
                "Thumbprint: " +
                $normalizedThumbprint
            )
        }

        return $certificate
    }

    if (
        -not [string]::IsNullOrWhiteSpace(
            $OrganizationInn
        )
    ) {
        $innMatches = @(
            $Certificates |
            Where-Object {
                $_.Subject -match (
                    [regex]::Escape(
                        $OrganizationInn
                    )
                )
            }
        )

        if ($innMatches.Count -eq 1) {
            return $innMatches[0]
        }
    }

    if ($Certificates.Count -eq 1) {
        return $Certificates[0]
    }

    $candidateText = (
        $Certificates |
        Select-Object `
            Thumbprint, `
            Subject, `
            NotAfter, `
            @{Name="Algorithm"; Expression={$_.PublicKey.Oid.FriendlyName}} |
        Format-Table -AutoSize |
        Out-String
    ).Trim()

    throw (
        "Unable to select one signing certificate. " +
        "Set GIS_MT_CERT_THUMBPRINT in .env.`r`n`r`n" +
        $candidateText
    )
}


function Get-DigestAlgorithmOid {
    param(
        [Parameter(Mandatory = $true)]
        [System.Security.Cryptography.X509Certificates.X509Certificate2]$Certificate
    )

    $publicKeyOid = $Certificate.PublicKey.Oid.Value

    switch ($publicKeyOid) {
        "1.2.643.7.1.1.1.1" {
            return "1.2.643.7.1.1.2.2"
        }

        "1.2.643.7.1.1.1.2" {
            return "1.2.643.7.1.1.2.3"
        }

        "1.2.643.2.2.19" {
            return "1.2.643.2.2.9"
        }

        default {
            return $null
        }
    }
}


function New-AttachedCmsSignature {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Data,

        [Parameter(Mandatory = $true)]
        [System.Security.Cryptography.X509Certificates.X509Certificate2]$Certificate,

        [Parameter(Mandatory = $true)]
        [bool]$Silent
    )

    $utf8Encoding = [System.Text.UTF8Encoding]::new(
        $false
    )

    [byte[]]$contentBytes = $utf8Encoding.GetBytes(
        $Data
    )

    $contentInfo = (
        [System.Security.Cryptography.Pkcs.ContentInfo]::new(
            $contentBytes
        )
    )

    $signedCms = (
        [System.Security.Cryptography.Pkcs.SignedCms]::new(
            $contentInfo,
            $false
        )
    )

    $signer = (
        [System.Security.Cryptography.Pkcs.CmsSigner]::new(
            $Certificate
        )
    )

    $signer.IncludeOption = (
        [System.Security.Cryptography.X509Certificates.X509IncludeOption]::EndCertOnly
    )

    $digestOid = Get-DigestAlgorithmOid `
        -Certificate $Certificate

    if (
        -not [string]::IsNullOrWhiteSpace(
            $digestOid
        )
    ) {
        $signer.DigestAlgorithm = (
            [System.Security.Cryptography.Oid]::new(
                $digestOid
            )
        )
    }

    try {
        $signedCms.ComputeSignature(
            $signer,
            $Silent
        )
    }
    catch {
        throw (
            "CMS signing failed. " +
            "Certificate: " +
            $Certificate.Thumbprint +
            ". Error: " +
            $_.Exception.Message
        )
    }

    [byte[]]$encodedSignature = (
        $signedCms.Encode()
    )

    return [Convert]::ToBase64String(
        $encodedSignature
    )
}


$projectRoot = Split-Path `
    -Parent `
    $PSScriptRoot

if (
    [string]::IsNullOrWhiteSpace(
        $EnvFile
    )
) {
    $EnvFile = Join-Path `
        $projectRoot `
        ".env"
}

$dotEnv = Read-DotEnvFile `
    -Path $EnvFile

$resolvedInn = Get-ConfigValue `
    -ExplicitValue $Inn `
    -EnvironmentName "GIS_MT_AUTH_INN" `
    -DotEnv $dotEnv `
    -DefaultValue $null

$resolvedThumbprint = Get-ConfigValue `
    -ExplicitValue $CertificateThumbprint `
    -EnvironmentName "GIS_MT_CERT_THUMBPRINT" `
    -DotEnv $dotEnv `
    -DefaultValue $null

$resolvedStoreLocation = Get-ConfigValue `
    -ExplicitValue $StoreLocation `
    -EnvironmentName "GIS_MT_CERT_STORE_LOCATION" `
    -DotEnv $dotEnv `
    -DefaultValue "CurrentUser"

$resolvedBaseUrl = Get-ConfigValue `
    -ExplicitValue $TrueApiBaseUrl `
    -EnvironmentName "GIS_MT_TRUE_API_V3_URL" `
    -DotEnv $dotEnv `
    -DefaultValue "https://markirovka.crpt.ru/api/v3/true-api"

if (
    $resolvedStoreLocation -notin @(
        "CurrentUser",
        "LocalMachine"
    )
) {
    throw (
        "GIS_MT_CERT_STORE_LOCATION must be " +
        "CurrentUser or LocalMachine."
    )
}

$certificates = Get-SigningCertificates `
    -Location $resolvedStoreLocation

if ($ListCertificates) {
    $certificates |
        Select-Object `
            Thumbprint, `
            Subject, `
            NotBefore, `
            NotAfter, `
            HasPrivateKey, `
            @{Name="AlgorithmOid"; Expression={$_.PublicKey.Oid.Value}}, `
            @{Name="Algorithm"; Expression={$_.PublicKey.Oid.FriendlyName}} |
        Format-Table -AutoSize

    exit 0
}

if (
    [string]::IsNullOrWhiteSpace(
        $resolvedInn
    )
) {
    throw (
        "GIS_MT_AUTH_INN is not set. " +
        "Add it to .env or pass -Inn."
    )
}

if ($resolvedInn -notmatch '^\d{10}(\d{2})?$') {
    throw (
        "GIS_MT_AUTH_INN must contain " +
        "10 or 12 digits."
    )
}

$certificate = Select-SigningCertificate `
    -Certificates $certificates `
    -Thumbprint $resolvedThumbprint `
    -OrganizationInn $resolvedInn

$baseUrl = $resolvedBaseUrl.TrimEnd("/")

Write-Verbose (
    "Certificate: " +
    $certificate.Thumbprint
)

Write-Verbose (
    "Certificate subject: " +
    $certificate.Subject
)

Write-Verbose (
    "True API: " +
    $baseUrl
)

$authKeyUrl = (
    $baseUrl +
    "/auth/key"
)

$authKeyResponse = Invoke-RestMethod `
    -Method Get `
    -Uri $authKeyUrl `
    -Headers @{
        Accept = "application/json"
    } `
    -TimeoutSec $TimeoutSeconds

$authUuid = [string]$authKeyResponse.uuid
$authData = [string]$authKeyResponse.data

if (
    [string]::IsNullOrWhiteSpace(
        $authUuid
    ) -or
    [string]::IsNullOrWhiteSpace(
        $authData
    )
) {
    throw (
        "The /auth/key response does not " +
        "contain uuid and data."
    )
}

$signature = New-AttachedCmsSignature `
    -Data $authData `
    -Certificate $certificate `
    -Silent (-not $AllowPinPrompt.IsPresent)

$requestBody = @{
    uuid = $authUuid
    data = $signature
    inn  = $resolvedInn
} | ConvertTo-Json -Compress

$signInUrl = (
    $baseUrl +
    "/auth/simpleSignIn"
)

try {
    $signInResponse = Invoke-RestMethod `
        -Method Post `
        -Uri $signInUrl `
        -Headers @{
            Accept = "application/json"
        } `
        -ContentType "application/json; charset=utf-8" `
        -Body $requestBody `
        -TimeoutSec $TimeoutSeconds
}
catch {
    $responseText = $null

    try {
        $response = $_.Exception.Response

        if ($null -ne $response) {
            $stream = $response.GetResponseStream()

            if ($null -ne $stream) {
                $reader = New-Object `
                    System.IO.StreamReader(
                        $stream
                    )

                try {
                    $responseText = $reader.ReadToEnd()
                }
                finally {
                    $reader.Dispose()
                }
            }
        }
    }
    catch {
        $responseText = $null
    }

    if (
        -not [string]::IsNullOrWhiteSpace(
            $responseText
        )
    ) {
        throw (
            "True API authentication failed: " +
            $responseText
        )
    }

    throw
}

$token = [string]$signInResponse.token

if (
    [string]::IsNullOrWhiteSpace(
        $token
    )
) {
    $errorMessage = [string]$signInResponse.error_message
    $description = [string]$signInResponse.description
    $code = [string]$signInResponse.code

    throw (
        "True API did not return a token. " +
        "Code: " +
        $code +
        "; error: " +
        $errorMessage +
        "; description: " +
        $description
    )
}

$token = $token.Trim()

if (
    $token.Contains("`r") -or
    $token.Contains("`n")
) {
    throw "True API returned a token with line breaks."
}

Write-Output $token