[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet(
        "Status",
        "Connect",
        "Disconnect"
    )]
    [string]$Action,

    [Parameter(Mandatory = $true)]
    [string]$DeviceName,

    [Parameter(Mandatory = $false)]
    [string]$DkclPath = (
        "C:\Users\kudryavcev\Desktop\dkcl64.exe"
    )
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"


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


function Read-DkclUtf8File {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $bytes = [System.IO.File]::ReadAllBytes(
        $Path
    )

    if ($bytes.Length -eq 0) {
        return ""
    }

    $strictUtf8 = New-Object `
        -TypeName System.Text.UTF8Encoding `
        -ArgumentList @(
            $false,
            $true
        )

    try {
        return $strictUtf8.GetString(
            $bytes
        )
    }
    catch {
        throw (
            "dkcl64 returned a result file " +
            "that is not valid UTF-8. File=" +
            $Path +
            "."
        )
    }
}


function Invoke-DkclCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Command
    )

    $resultFile = Join-Path `
        -Path $env:TEMP `
        -ChildPath (
            "dkcl_result_{0}.txt" -f
            [guid]::NewGuid().ToString(
                "N"
            )
        )

    $redirectArgument = (
        "-r=" +
        $resultFile
    )

    $previousPreference = $ErrorActionPreference
    $nativeOutput = @()
    $exitCode = 0

    try {
        $ErrorActionPreference = "Continue"

        $nativeOutput = @(
            & $DkclPath `
                $redirectArgument `
                -t `
                $Command `
                2>&1 |
            ForEach-Object {
                [string]$_
            }
        )

        if ($null -ne $LASTEXITCODE) {
            $exitCode = [int]$LASTEXITCODE
        }
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }

    if ($exitCode -ne 0) {
        throw (
            "dkcl64 command failed. Command=" +
            $Command +
            "; ExitCode=" +
            $exitCode +
            "; Output=" +
            (
                $nativeOutput -join " | "
            )
        )
    }

    $deadline = (
        Get-Date
    ).AddSeconds(
        15
    )

    while (
        -not (
            Test-Path `
                -LiteralPath $resultFile `
                -PathType Leaf
        )
    ) {
        if (
            (Get-Date) -ge
            $deadline
        ) {
            throw (
                "dkcl64 did not create its result file. " +
                "Command=" +
                $Command +
                "; ExpectedFile=" +
                $resultFile +
                "."
            )
        }

        Start-Sleep `
            -Milliseconds 200
    }

    try {
        $text = Read-DkclUtf8File `
            -Path $resultFile

        return [pscustomobject]@{
            Command = $Command
            ExitCode = $exitCode
            Text = $text

            Lines = @(
                $text -split
                "`r`n|`n|`r"
            )
        }
    }
    finally {
        Remove-Item `
            -LiteralPath $resultFile `
            -Force `
            -ErrorAction SilentlyContinue
    }
}


function Assert-DkclSuccess {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Result
    )

    $preparedText = (
        [string]$Result.Text
    ).Trim()

    if (
        $preparedText -notmatch
        "(?im)^\s*OK\s*$"
    ) {
        throw (
            "DistKontrolUSB rejected the command. " +
            "Command=" +
            $Result.Command +
            "; Result=" +
            $preparedText +
            "."
        )
    }
}


function Get-DeviceList {
    $listResult = Invoke-DkclCommand `
        -Command "LIST"

    $devices = @()

    $devicePattern = (
        '^\s*\*?\s*-->\s*' +
        '(?<name>.*?)\s+' +
        '\((?<address>[^()\s]+\.\d+)\)' +
        '(?:\s+\(In-use by:' +
        '(?<owner>.*?)\s+' +
        '\((?<login>[^()]*)\)\s+' +
        'at\s+' +
        '(?<ip>[^()]*)\))?' +
        '\s*$'
    )

    foreach ($line in $listResult.Lines) {
        $match = [regex]::Match(
            [string]$line,
            $devicePattern
        )

        if (-not $match.Success) {
            continue
        }

        $owner = (
            $match.Groups[
                "owner"
            ].Value
        ).Trim()

        $login = (
            $match.Groups[
                "login"
            ].Value
        ).Trim()

        $ipAddress = (
            $match.Groups[
                "ip"
            ].Value
        ).Trim()

        $devices += [pscustomobject]@{
            Name = (
                $match.Groups[
                    "name"
                ].Value
            ).Trim()

            Address = (
                $match.Groups[
                    "address"
                ].Value
            ).Trim()

            IsBusy = (
                -not [string]::IsNullOrWhiteSpace(
                    $login
                )
            )

            Owner = $owner
            Login = $login
            IpAddress = $ipAddress
        }
    }

    if ($devices.Count -eq 0) {
        throw (
            "LIST returned no parsable devices."
        )
    }

    return $devices
}


function Find-TargetDevice {
    $devices = @(
        Get-DeviceList
    )

    $matches = @(
        $devices |
        Where-Object {
            [string]::Equals(
                [string]$_.Name,
                [string]$DeviceName,
                [System.StringComparison]::OrdinalIgnoreCase
            )
        }
    )

    if ($matches.Count -gt 1) {
        throw (
            "More than one device has the exact name: " +
            $DeviceName +
            "."
        )
    }

    if ($matches.Count -eq 0) {
        return $null
    }

    return $matches[0]
}


function Get-RequiredTargetDevice {
    $device = Find-TargetDevice

    if ($null -ne $device) {
        return $device
    }

    $availableNames = (
        Get-DeviceList |
        ForEach-Object {
            [string]$_.Name
        }
    ) -join "; "

    throw (
        "Device was not found by exact name: " +
        $DeviceName +
        ". Available devices: " +
        $availableNames +
        "."
    )
}


function Test-OwnedByCurrentUser {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Device
    )

    if (-not $Device.IsBusy) {
        return $false
    }

    $currentUser = (
        [string]$env:USERNAME
    ).Trim()

    if (
        [string]::IsNullOrWhiteSpace(
            $currentUser
        )
    ) {
        return $false
    }

    if (
        [string]::Equals(
            [string]$Device.Login,
            $currentUser,
            [System.StringComparison]::OrdinalIgnoreCase
        )
    ) {
        return $true
    }

    if (
        [string]::Equals(
            [string]$Device.Owner,
            $currentUser,
            [System.StringComparison]::OrdinalIgnoreCase
        )
    ) {
        return $true
    }

    return $false
}


function Get-SessionCachePath {
    $currentProcess = Get-Process `
        -Id $PID `
        -ErrorAction Stop

    $processStartTimeUtc = (
        $currentProcess.StartTime
    ).ToUniversalTime()

    $processStartTicks = (
        $processStartTimeUtc.Ticks
    )

    $cacheFileName = (
        "cz_async_diskontrol_{0}_{1}.json" -f
        $PID,
        $processStartTicks
    )

    return Join-Path `
        -Path $env:TEMP `
        -ChildPath $cacheFileName
}


function Save-SessionConnection {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Device
    )

    $cachePath = Get-SessionCachePath

    $record = [ordered]@{
        device_name = (
            [string]$Device.Name
        )

        device_address = (
            [string]$Device.Address
        )

        windows_user = (
            [string]$env:USERNAME
        )

        process_id = $PID

        connected_at = (
            Get-Date
        ).ToString(
            "o"
        )
    }

    $json = (
        $record |
        ConvertTo-Json `
            -Compress `
            -Depth 4
    )

    $utf8NoBom = New-Object `
        -TypeName System.Text.UTF8Encoding `
        -ArgumentList @(
            $false
        )

    [System.IO.File]::WriteAllText(
        $cachePath,
        $json,
        $utf8NoBom
    )
}


function Read-SessionConnection {
    $cachePath = Get-SessionCachePath

    if (
        -not (
            Test-Path `
                -LiteralPath $cachePath `
                -PathType Leaf
        )
    ) {
        return $null
    }

    $json = [System.IO.File]::ReadAllText(
        $cachePath,
        [System.Text.Encoding]::UTF8
    )

    if (
        [string]::IsNullOrWhiteSpace(
            $json
        )
    ) {
        return $null
    }

    try {
        return (
            $json |
            ConvertFrom-Json
        )
    }
    catch {
        throw (
            "Invalid DistKontrolUSB session cache. File=" +
            $cachePath +
            "."
        )
    }
}


function Remove-SessionConnection {
    $cachePath = Get-SessionCachePath

    Remove-Item `
        -LiteralPath $cachePath `
        -Force `
        -ErrorAction SilentlyContinue
}


function New-DeviceResultObject {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,

        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$Address,

        [Parameter(Mandatory = $true)]
        [bool]$IsBusy,

        [Parameter(Mandatory = $false)]
        [AllowEmptyString()]
        [string]$Owner = "",

        [Parameter(Mandatory = $false)]
        [AllowEmptyString()]
        [string]$Login = "",

        [Parameter(Mandatory = $false)]
        [AllowEmptyString()]
        [string]$IpAddress = ""
    )

    return [pscustomobject]@{
        Name = $Name
        Address = $Address
        IsBusy = $IsBusy
        Owner = $Owner
        Login = $Login
        IpAddress = $IpAddress
    }
}


function Write-DeviceResult {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Status,

        [Parameter(Mandatory = $true)]
        [object]$Device,

        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    $result = [ordered]@{
        status = $Status
        message = $Message
        device_name = $Device.Name
        device_address = $Device.Address
        busy = [bool]$Device.IsBusy
        owner = $Device.Owner
        login = $Device.Login
        ip_address = $Device.IpAddress
        current_windows_user = $env:USERNAME

        timestamp = (
            Get-Date
        ).ToString(
            "o"
        )
    }

    Write-Output (
        $result |
        ConvertTo-Json `
            -Compress `
            -Depth 5
    )
}


function Invoke-Status {
    $device = Find-TargetDevice

    if ($null -eq $device) {
        $sessionConnection = Read-SessionConnection

        if (
            $null -ne $sessionConnection -and
            [string]::Equals(
                [string]$sessionConnection.device_name,
                [string]$DeviceName,
                [System.StringComparison]::OrdinalIgnoreCase
            )
        ) {
            $connectedDevice = New-DeviceResultObject `
                -Name ([string]$sessionConnection.device_name) `
                -Address ([string]$sessionConnection.device_address) `
                -IsBusy $true `
                -Owner ([string]$env:USERNAME) `
                -Login ([string]$env:USERNAME)

            Write-DeviceResult `
                -Status "CONNECTED_BY_CURRENT_USER" `
                -Device $connectedDevice `
                -Message (
                    "Device was connected by this " +
                    "PowerShell process."
                )

            return
        }

        $missingDevice = New-DeviceResultObject `
            -Name $DeviceName `
            -Address "" `
            -IsBusy $false

        Write-DeviceResult `
            -Status "NOT_AVAILABLE" `
            -Device $missingDevice `
            -Message (
                "Device is not present in the current LIST result."
            )

        return
    }

    if (-not $device.IsBusy) {
        Write-DeviceResult `
            -Status "FREE" `
            -Device $device `
            -Message "Device is available."

        return
    }

    if (
        Test-OwnedByCurrentUser `
            -Device $device
    ) {
        Write-DeviceResult `
            -Status "CONNECTED_BY_CURRENT_USER" `
            -Device $device `
            -Message (
                "Device is connected by the current user."
            )

        return
    }

    Write-DeviceResult `
        -Status "BUSY" `
        -Device $device `
        -Message (
            "Device is connected by another user. " +
            "No USE or STOP USING command was sent."
        )
}


function Invoke-Connect {
    $device = Get-RequiredTargetDevice

    if ($device.IsBusy) {
        if (
            Test-OwnedByCurrentUser `
                -Device $device
        ) {
            Write-DeviceResult `
                -Status "ALREADY_CONNECTED" `
                -Device $device `
                -Message (
                    "Device is already connected " +
                    "by the current user."
                )

            return
        }

        Write-DeviceResult `
            -Status "BUSY" `
            -Device $device `
            -Message (
                "Device is connected by another user. " +
                "No USE or STOP USING command was sent."
            )

        return
    }

    Write-Step `
        -Message (
            "Connecting exact device. Name=" +
            $device.Name +
            "; Address=" +
            $device.Address +
            "."
        )

    $useResult = Invoke-DkclCommand `
        -Command (
            "USE," +
            $device.Address
        )

    Assert-DkclSuccess `
        -Result $useResult

    Save-SessionConnection `
        -Device $device

    $connectedDevice = New-DeviceResultObject `
        -Name ([string]$device.Name) `
        -Address ([string]$device.Address) `
        -IsBusy $true `
        -Owner ([string]$env:USERNAME) `
        -Login ([string]$env:USERNAME)

    Write-DeviceResult `
        -Status "CONNECTED" `
        -Device $connectedDevice `
        -Message (
            "DistKontrolUSB accepted the connection command. " +
            "Certificate verification must follow."
        )
}


function Invoke-Disconnect {
    $sessionConnection = Read-SessionConnection

    if ($null -eq $sessionConnection) {
        $refusedDevice = New-DeviceResultObject `
            -Name $DeviceName `
            -Address "" `
            -IsBusy $false

        Write-DeviceResult `
            -Status "REFUSED_NO_SESSION_CONNECTION" `
            -Device $refusedDevice `
            -Message (
                "This PowerShell process did not connect " +
                "the requested device. " +
                "No STOP USING command was sent."
            )

        return
    }

    $cachedDeviceName = (
        [string]$sessionConnection.device_name
    )

    if (
        -not [string]::Equals(
            $cachedDeviceName,
            [string]$DeviceName,
            [System.StringComparison]::OrdinalIgnoreCase
        )
    ) {
        $refusedDevice = New-DeviceResultObject `
            -Name $DeviceName `
            -Address "" `
            -IsBusy $false

        Write-DeviceResult `
            -Status "REFUSED_SESSION_MISMATCH" `
            -Device $refusedDevice `
            -Message (
                "Requested device does not match " +
                "the device connected by this process. " +
                "No STOP USING command was sent."
            )

        return
    }

    $cachedAddress = (
        [string]$sessionConnection.device_address
    ).Trim()

    if (
        $cachedAddress -notmatch
        "^[A-Za-z0-9_-]+\.\d+$"
    ) {
        throw (
            "Invalid cached DistKontrolUSB address."
        )
    }

    Write-Step `
        -Message (
            "Disconnecting device connected " +
            "by this PowerShell process. Name=" +
            $cachedDeviceName +
            "; Address=" +
            $cachedAddress +
            "."
        )

    $stopResult = Invoke-DkclCommand `
        -Command (
            "STOP USING," +
            $cachedAddress
        )

    Assert-DkclSuccess `
        -Result $stopResult

    Remove-SessionConnection

    $disconnectedDevice = New-DeviceResultObject `
        -Name $cachedDeviceName `
        -Address $cachedAddress `
        -IsBusy $false

    Write-DeviceResult `
        -Status "DISCONNECTED" `
        -Device $disconnectedDevice `
        -Message (
            "Device connected by this process " +
            "was disconnected successfully."
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


switch ($Action) {
    "Status" {
        Invoke-Status
        return
    }

    "Connect" {
        Invoke-Connect
        return
    }

    "Disconnect" {
        Invoke-Disconnect
        return
    }

    default {
        throw (
            "Unsupported action: " +
            $Action
        )
    }
}