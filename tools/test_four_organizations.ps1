[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$EnvFile,

    [Parameter(Mandatory = $false)]
    [string]$DkclPath = "C:\Users\kudryavcev\Desktop\dkcl64.exe",

    [Parameter(Mandatory = $false)]
    [ValidateRange(1, 10)]
    [int]$StatusAttempts = 4,

    [Parameter(Mandatory = $false)]
    [ValidateRange(1, 30)]
    [int]$StatusRetrySeconds = 3,

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


function Write-RunLine {
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


function ConvertFrom-Utf8Base64 {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Value
    )

    $bytes = [System.Convert]::FromBase64String(
        $Value
    )

    return [System.Text.Encoding]::UTF8.GetString(
        $bytes
    )
}


function Get-LastJsonObject {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [object[]]$OutputLines
    )

    $jsonLine = $null

    foreach ($item in $OutputLines) {
        $line = (
            [string]$item
        ).Trim()

        if (
            $line.StartsWith("{") -and
            $line.EndsWith("}")
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
            "The called script did not return a JSON result."
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
            "Invalid JSON result: " +
            [string]$jsonLine
        )
    }
}


function Get-DeviceStatus {
    param(
        [Parameter(Mandatory = $true)]
        [string]$DeviceName,

        [Parameter(Mandatory = $true)]
        [string]$DeviceScript
    )

    $output = @(
        & $DeviceScript `
            -Action Status `
            -DeviceName $DeviceName `
            -DkclPath $DkclPath `
            2>&1
    )

    return Get-LastJsonObject `
        -OutputLines $output
}


function Get-StableDeviceStatus {
    param(
        [Parameter(Mandatory = $true)]
        [string]$DeviceName,

        [Parameter(Mandatory = $true)]
        [string]$DeviceScript
    )

    $lastResult = $null

    for (
        $attempt = 1;
        $attempt -le $StatusAttempts;
        $attempt++
    ) {
        $lastResult = Get-DeviceStatus `
            -DeviceName $DeviceName `
            -DeviceScript $DeviceScript

        Write-RunLine (
            "Status attempt " +
            $attempt +
            "/" +
            $StatusAttempts +
            "; Device=" +
            $DeviceName +
            "; Status=" +
            [string]$lastResult.status +
            "."
        )

        if (
            (
                [string]$lastResult.status
            ) -ne "NOT_AVAILABLE"
        ) {
            return $lastResult
        }

        if ($attempt -lt $StatusAttempts) {
            Start-Sleep `
                -Seconds $StatusRetrySeconds
        }
    }

    return $lastResult
}


function Invoke-SingleOrganizationTest {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Organization,

        [Parameter(Mandatory = $true)]
        [string]$TestScript,

        [Parameter(Mandatory = $true)]
        [string]$PowerShellExe,

        [Parameter(Mandatory = $true)]
        [string]$ResolvedEnvFile
    )

    $arguments = @(
        "-NoLogo",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        $TestScript,
        "-DeviceName",
        [string]$Organization.DeviceName,
        "-EntitySearch",
        [string]$Organization.EntitySearch,
        "-EnvFile",
        $ResolvedEnvFile,
        "-DkclPath",
        $DkclPath,
        "-CertificateWaitSeconds",
        [string]$CertificateWaitSeconds,
        "-AuthTimeoutSeconds",
        [string]$AuthTimeoutSeconds
    )

    if ($AllowPinPrompt.IsPresent) {
        $arguments += "-AllowPinPrompt"
    }

    $startedAt = Get-Date
    $output = @()
    $processExitCode = 1

    try {
        $output = @(
            & $PowerShellExe @arguments 2>&1 |
            ForEach-Object {
                [string]$_
            }
        )

        if ($null -ne $LASTEXITCODE) {
            $processExitCode = [int]$LASTEXITCODE
        }
    }
    catch {
        return [pscustomobject]@{
            DeviceName = [string]$Organization.DeviceName
            EntitySearch = [string]$Organization.EntitySearch
            Status = "FAILED"
            Message = $_.Exception.Message
            ExitCode = 1
            DurationSeconds = [math]::Round(
                (
                    (Get-Date) -
                    $startedAt
                ).TotalSeconds,
                3
            )
        }
    }

    foreach ($line in $output) {
        Write-Host $line
    }

    try {
        $childResult = Get-LastJsonObject `
            -OutputLines $output

        return [pscustomobject]@{
            DeviceName = [string]$Organization.DeviceName
            EntitySearch = [string]$Organization.EntitySearch
            Status = [string]$childResult.status
            Message = [string]$childResult.message
            ExitCode = $processExitCode
            DurationSeconds = [math]::Round(
                (
                    (Get-Date) -
                    $startedAt
                ).TotalSeconds,
                3
            )
        }
    }
    catch {
        return [pscustomobject]@{
            DeviceName = [string]$Organization.DeviceName
            EntitySearch = [string]$Organization.EntitySearch
            Status = "FAILED_RESULT_PARSE"
            Message = $_.Exception.Message
            ExitCode = $processExitCode
            DurationSeconds = [math]::Round(
                (
                    (Get-Date) -
                    $startedAt
                ).TotalSeconds,
                3
            )
        }
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

$testScript = Join-Path `
    -Path $PSScriptRoot `
    -ChildPath "test_one_organization.ps1"

$powerShellExe = (
    Get-Process `
        -Id $PID `
        -ErrorAction Stop
).Path

if (
    -not (
        Test-Path `
            -LiteralPath $deviceScript `
            -PathType Leaf
    )
) {
    throw (
        "Device script was not found: " +
        $deviceScript
    )
}

if (
    -not (
        Test-Path `
            -LiteralPath $testScript `
            -PathType Leaf
    )
) {
    throw (
        "Single organization test script was not found: " +
        $testScript
    )
}

if (
    -not (
        Test-Path `
            -LiteralPath $powerShellExe `
            -PathType Leaf
    )
) {
    throw (
        "PowerShell executable was not found: " +
        $powerShellExe
    )
}

if (
    -not (
        Test-Path `
            -LiteralPath $DkclPath `
            -PathType Leaf
    )
) {
    throw (
        "dkcl64.exe was not found: " +
        $DkclPath
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
        "Environment file was not found: " +
        $EnvFile
    )
}


$organizations = @(
    [pscustomobject]@{
        DeviceName = ConvertFrom-Utf8Base64 `
            -Value "0JjQnyDQk9C+0YDQsdGD0L3QvtCy"

        EntitySearch = ConvertFrom-Utf8Base64 `
            -Value "0JPQntCg0JHQo9Cd0J7QkiDQmtCY0KDQmNCb0Jsg0JLQkNCU0JjQnNCe0JLQmNCn"
    },

    [pscustomobject]@{
        DeviceName = ConvertFrom-Utf8Base64 `
            -Value "0JjQnyDQk9C+0YDQsdGD0L3QvtCy0LA="

        EntitySearch = ConvertFrom-Utf8Base64 `
            -Value "0JPQntCg0JHQo9Cd0J7QktCQINCQ0JvQldCa0KHQkNCd0JTQoNCQINCe0JvQldCT0J7QktCd0JA="
    },

    [pscustomobject]@{
        DeviceName = ConvertFrom-Utf8Base64 `
            -Value "0JjQnyDQmtGA0LjRhtC40L3QsA=="

        EntitySearch = ConvertFrom-Utf8Base64 `
            -Value "0JrQoNCY0KbQmNCd0JAg0JLQmNCe0JvQldCi0KLQkCDQndCY0JrQntCb0JDQldCS0J3QkA=="
    },

    [pscustomobject]@{
        DeviceName = ConvertFrom-Utf8Base64 `
            -Value "0JjQnyDQm9C10LHQtdC00LXQstCw"

        EntitySearch = ConvertFrom-Utf8Base64 `
            -Value "0JvQldCR0JXQlNCV0JLQkCDQkNCd0J3QkCDQkNCd0JTQoNCV0JXQktCd0JA="
    }
)


$results = @()

Write-RunLine (
    "Starting sequential test of four organizations."
)

foreach ($organization in $organizations) {
    Write-Host ""
    Write-Host "============================================================"

    Write-RunLine (
        "Organization=" +
        [string]$organization.DeviceName +
        "."
    )

    $statusResult = $null

    try {
        $statusResult = Get-StableDeviceStatus `
            -DeviceName (
                [string]$organization.DeviceName
            ) `
            -DeviceScript $deviceScript
    }
    catch {
        $results += [pscustomobject]@{
            DeviceName = [string]$organization.DeviceName
            EntitySearch = [string]$organization.EntitySearch
            Status = "FAILED_STATUS_CHECK"
            Message = $_.Exception.Message
            ExitCode = 1
            DurationSeconds = 0
        }

        continue
    }

    $currentStatus = (
        [string]$statusResult.status
    )

    if ($currentStatus -eq "BUSY") {
        Write-RunLine (
            "SKIPPED_BUSY. No USE or STOP USING command was sent."
        )

        $results += [pscustomobject]@{
            DeviceName = [string]$organization.DeviceName
            EntitySearch = [string]$organization.EntitySearch
            Status = "SKIPPED_BUSY"
            Message = "Device is used by another user."
            ExitCode = 0
            DurationSeconds = 0
        }

        continue
    }

    if ($currentStatus -eq "NOT_AVAILABLE") {
        Write-RunLine (
            "SKIPPED_NOT_AVAILABLE. No USE or STOP USING command was sent."
        )

        $results += [pscustomobject]@{
            DeviceName = [string]$organization.DeviceName
            EntitySearch = [string]$organization.EntitySearch
            Status = "SKIPPED_NOT_AVAILABLE"
            Message = "Device did not appear in LIST."
            ExitCode = 0
            DurationSeconds = 0
        }

        continue
    }

    if ($currentStatus -eq "CONNECTED_BY_CURRENT_USER") {
        Write-RunLine (
            "SKIPPED_ALREADY_CONNECTED. Existing connection was not used or disconnected."
        )

        $results += [pscustomobject]@{
            DeviceName = [string]$organization.DeviceName
            EntitySearch = [string]$organization.EntitySearch
            Status = "SKIPPED_ALREADY_CONNECTED"
            Message = "Device was already connected before this test."
            ExitCode = 0
            DurationSeconds = 0
        }

        continue
    }

    if ($currentStatus -ne "FREE") {
        Write-RunLine (
            "Unsupported status=" +
            $currentStatus +
            "."
        )

        $results += [pscustomobject]@{
            DeviceName = [string]$organization.DeviceName
            EntitySearch = [string]$organization.EntitySearch
            Status = "FAILED_UNSUPPORTED_STATUS"
            Message = (
                "Unsupported device status: " +
                $currentStatus
            )
            ExitCode = 1
            DurationSeconds = 0
        }

        continue
    }

    Write-RunLine (
        "Starting full test for " +
        [string]$organization.DeviceName +
        "."
    )

    $testResult = Invoke-SingleOrganizationTest `
        -Organization $organization `
        -TestScript $testScript `
        -PowerShellExe $powerShellExe `
        -ResolvedEnvFile $EnvFile

    $results += $testResult

    Start-Sleep `
        -Seconds 2
}


Write-Host ""
Write-Host "============================================================"

$successCount = @(
    $results |
    Where-Object {
        $_.Status -eq "SUCCESS"
    }
).Count

$skippedCount = @(
    $results |
    Where-Object {
        $_.Status -in @(
            "SKIPPED_BUSY",
            "SKIPPED_NOT_AVAILABLE",
            "SKIPPED_ALREADY_CONNECTED"
        )
    }
).Count

$failedCount = @(
    $results |
    Where-Object {
        $_.Status -notin @(
            "SUCCESS",
            "SKIPPED_BUSY",
            "SKIPPED_NOT_AVAILABLE",
            "SKIPPED_ALREADY_CONNECTED"
        )
    }
).Count

if ($failedCount -gt 0) {
    $overallStatus = "FAILED"
}
elseif ($skippedCount -gt 0) {
    $overallStatus = "COMPLETED_WITH_SKIPS"
}
else {
    $overallStatus = "SUCCESS"
}

$results |
Select-Object `
    DeviceName,
    Status,
    DurationSeconds,
    Message |
Format-Table `
    -AutoSize `
    -Wrap

Write-RunLine (
    "OverallStatus=" +
    $overallStatus +
    "; Success=" +
    $successCount +
    "; Skipped=" +
    $skippedCount +
    "; Failed=" +
    $failedCount +
    "."
)

$summary = [ordered]@{
    status = $overallStatus
    total = $results.Count
    success = $successCount
    skipped = $skippedCount
    failed = $failedCount
    organizations = $results
    timestamp = (
        Get-Date
    ).ToString(
        "o"
    )
}

Write-Host ""

Write-Output (
    $summary |
    ConvertTo-Json `
        -Compress `
        -Depth 7
)

if ($failedCount -gt 0) {
    exit 1
}

exit 0