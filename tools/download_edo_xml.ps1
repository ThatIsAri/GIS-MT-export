[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$RequestUrl,

    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$Authorization,

    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$Cookie,

    [Parameter(Mandatory = $false)]
    [string]$OutputRoot = ""
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"


function Get-HeaderValue {
    param(
        [Parameter(Mandatory = $true)]
        $Headers,

        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $value = $Headers[$Name]

    if ($null -eq $value) {
        return ""
    }

    if ($value -is [System.Array]) {
        return ($value -join "; ")
    }

    return [string]$value
}


function Get-ResponseFileName {
    param(
        [Parameter(Mandatory = $false)]
        [AllowEmptyString()]
        [string]$ContentDisposition,

        [Parameter(Mandatory = $true)]
        [string]$Fallback
    )

    if ([string]::IsNullOrWhiteSpace($ContentDisposition)) {
        return $Fallback
    }

    $utf8Pattern = "filename\*=UTF-8''(?<name>[^;]+)"

    $utf8Match = [regex]::Match(
        $ContentDisposition,
        $utf8Pattern,
        [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
    )

    if ($utf8Match.Success) {
        $encodedName = $utf8Match.Groups["name"].Value.Trim()
        $encodedName = $encodedName.Trim('"')

        return [System.Uri]::UnescapeDataString($encodedName)
    }

    $regularPattern = 'filename\s*=\s*"?(?<name>[^";]+)"?'

    $regularMatch = [regex]::Match(
        $ContentDisposition,
        $regularPattern,
        [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
    )

    if ($regularMatch.Success) {
        return $regularMatch.Groups["name"].Value.Trim()
    }

    return $Fallback
}


function Get-SafeFileName {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FileName,

        [Parameter(Mandatory = $true)]
        [string]$Fallback
    )

    $preparedName = $FileName.Trim()

    if ([string]::IsNullOrWhiteSpace($preparedName)) {
        $preparedName = $Fallback
    }

    $invalidCharacters = [System.IO.Path]::GetInvalidFileNameChars()

    foreach ($invalidCharacter in $invalidCharacters) {
        $preparedName = $preparedName.Replace(
            [string]$invalidCharacter,
            "_"
        )
    }

    $preparedName = $preparedName.Trim()
    $preparedName = $preparedName.TrimEnd(".")

    if ([string]::IsNullOrWhiteSpace($preparedName)) {
        $preparedName = $Fallback
    }

    if (
        -not $preparedName.EndsWith(
            ".xml",
            [System.StringComparison]::OrdinalIgnoreCase
        )
    ) {
        $preparedName = $preparedName + ".xml"
    }

    if ($preparedName.Length -gt 220) {
        $preparedName = $preparedName.Substring(0, 216) + ".xml"
    }

    return $preparedName
}


$preparedRequestUrl = $RequestUrl.Trim()
$preparedAuthorization = $Authorization.Trim()
$preparedCookie = $Cookie.Trim()

if ([string]::IsNullOrWhiteSpace($preparedAuthorization)) {
    throw "Authorization is empty."
}

if ([string]::IsNullOrWhiteSpace($preparedCookie)) {
    throw "Cookie is empty."
}

if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $projectRoot = Split-Path -Parent $PSScriptRoot

    $OutputRoot = Join-Path `
        $projectRoot `
        "data\edo_inbox\bff"
}

if (
    $preparedAuthorization.StartsWith(
        "Bearer ",
        [System.StringComparison]::OrdinalIgnoreCase
    )
) {
    $authorizationHeader = $preparedAuthorization
}
else {
    $authorizationHeader = "Bearer " + $preparedAuthorization
}

if (
    $authorizationHeader.Contains("`r") -or
    $authorizationHeader.Contains("`n")
) {
    throw "Authorization contains a line break."
}

if (
    $preparedCookie.Contains("`r") -or
    $preparedCookie.Contains("`n")
) {
    throw "Cookie contains a line break."
}

try {
    $requestUri = [System.Uri]$preparedRequestUrl
}
catch {
    throw "RequestUrl is not a valid URL."
}

if ($requestUri.Scheme -ne "https") {
    throw "RequestUrl must use HTTPS."
}

if (
    $requestUri.Host -ne "softdrinks.crpt.ru"
) {
    throw "Only softdrinks.crpt.ru is allowed."
}

$documentPathPattern = (
    "/incoming-documents/" +
    "(?<id>[0-9a-fA-F]{8}-" +
    "[0-9a-fA-F]{4}-" +
    "[0-9a-fA-F]{4}-" +
    "[0-9a-fA-F]{4}-" +
    "[0-9a-fA-F]{12})" +
    "/content/?$"
)

$documentIdMatch = [regex]::Match(
    $requestUri.AbsolutePath,
    $documentPathPattern
)

if (-not $documentIdMatch.Success) {
    throw (
        "RequestUrl does not match " +
        "/incoming-documents/{UUID}/content."
    )
}

$documentId = $documentIdMatch.Groups["id"].Value

$refererUrl = (
    "https://softdrinks.crpt.ru/" +
    "documents/incoming/upd970/" +
    $documentId
)

$headers = @{
    Authorization     = $authorizationHeader
    Cookie            = $preparedCookie
    Accept            = "application/json, text/plain, */*"
    "Accept-Language" = "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"
    Referer           = $refererUrl
    "X-Source-App"    = "@crpt/lightindustry"
    "Sec-Fetch-Dest"  = "empty"
    "Sec-Fetch-Mode"  = "cors"
    "Sec-Fetch-Site"  = "same-origin"
    "Cache-Control"   = "no-cache"
    Pragma            = "no-cache"
}

$userAgent = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) " +
    "AppleWebKit/537.36 (KHTML, like Gecko) " +
    "Chrome/150.0.0.0 Safari/537.36"
)

$outputDirectory = Join-Path `
    $OutputRoot `
    $documentId

New-Item `
    -ItemType Directory `
    -Force `
    -Path $outputDirectory |
Out-Null

$temporaryFileName = (
    "edo-" +
    $documentId +
    "-" +
    [System.Guid]::NewGuid().ToString("N") +
    ".tmp"
)

$temporaryFile = Join-Path `
    ([System.IO.Path]::GetTempPath()) `
    $temporaryFileName

try {
    $requestParameters = @{
        Uri             = $preparedRequestUrl
        Method          = "Get"
        Headers         = $headers
        UserAgent       = $userAgent
        OutFile         = $temporaryFile
        PassThru        = $true
        UseBasicParsing = $true
    }

    $response = Invoke-WebRequest @requestParameters

    $statusCode = [int]$response.StatusCode

    $contentType = Get-HeaderValue `
        -Headers $response.Headers `
        -Name "Content-Type"

    $contentDisposition = Get-HeaderValue `
        -Headers $response.Headers `
        -Name "Content-Disposition"

    if ($statusCode -ne 200) {
        throw "Server returned HTTP $statusCode."
    }

    if (-not (Test-Path $temporaryFile)) {
        throw "Response file was not created."
    }

    $temporaryFileInfo = Get-Item $temporaryFile

    if ($temporaryFileInfo.Length -le 0) {
        throw "Server returned an empty file."
    }

    if (
        $contentType -notmatch "(?i)(application|text)/xml"
    ) {
        $displayContentType = $contentType

        if ([string]::IsNullOrWhiteSpace($displayContentType)) {
            $displayContentType = "not specified"
        }

        throw (
            "Server returned non-XML content. " +
            "Content-Type: " +
            $displayContentType +
            "; size: " +
            $temporaryFileInfo.Length +
            " bytes."
        )
    }

    $fallbackFileName = (
        "incoming_" +
        $documentId +
        ".xml"
    )

    $responseFileName = Get-ResponseFileName `
        -ContentDisposition $contentDisposition `
        -Fallback $fallbackFileName

    $safeFileName = Get-SafeFileName `
        -FileName $responseFileName `
        -Fallback $fallbackFileName

    $temporaryHash = (
        Get-FileHash `
            -Path $temporaryFile `
            -Algorithm SHA256
    ).Hash.ToLowerInvariant()

    $outputPath = Join-Path `
        $outputDirectory `
        $safeFileName

    $created = $true

    if (Test-Path $outputPath) {
        $existingHash = (
            Get-FileHash `
                -Path $outputPath `
                -Algorithm SHA256
        ).Hash.ToLowerInvariant()

        if ($existingHash -eq $temporaryHash) {
            Remove-Item `
                -Path $temporaryFile `
                -Force

            $created = $false
        }
        else {
            $baseName = (
                [System.IO.Path]::GetFileNameWithoutExtension(
                    $safeFileName
                )
            )

            $versionedFileName = (
                $baseName +
                "_" +
                $temporaryHash.Substring(0, 12) +
                ".xml"
            )

            $outputPath = Join-Path `
                $outputDirectory `
                $versionedFileName

            if (Test-Path $outputPath) {
                $versionedHash = (
                    Get-FileHash `
                        -Path $outputPath `
                        -Algorithm SHA256
                ).Hash.ToLowerInvariant()

                if ($versionedHash -eq $temporaryHash) {
                    Remove-Item `
                        -Path $temporaryFile `
                        -Force

                    $created = $false
                }
                else {
                    Move-Item `
                        -Path $temporaryFile `
                        -Destination $outputPath `
                        -Force
                }
            }
            else {
                Move-Item `
                    -Path $temporaryFile `
                    -Destination $outputPath
            }
        }
    }
    else {
        Move-Item `
            -Path $temporaryFile `
            -Destination $outputPath
    }

    $savedFile = Get-Item $outputPath

    [pscustomobject]@{
        Success     = $true
        Created     = $created
        DocumentId  = $documentId
        FilePath    = $savedFile.FullName
        FileSize    = $savedFile.Length
        ContentType = $contentType
        Sha256      = $temporaryHash
    }
}
finally {
    if (Test-Path $temporaryFile) {
        Remove-Item `
            -Path $temporaryFile `
            -Force `
            -ErrorAction SilentlyContinue
    }
}