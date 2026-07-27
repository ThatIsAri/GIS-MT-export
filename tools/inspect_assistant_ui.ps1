[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$OutputDirectory
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
        "[" +
        (Get-Date -Format "yyyy-MM-dd HH:mm:ss") +
        "] " +
        $Message
    )
}


function Get-SafeValue {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Expression,

        [Parameter(Mandatory = $false)]
        [AllowNull()]
        $Fallback = $null
    )

    try {
        return & $Expression
    }
    catch {
        return $Fallback
    }
}


function Get-PatternNames {
    param(
        [Parameter(Mandatory = $true)]
        [System.Windows.Automation.AutomationElement]$Element
    )

    try {
        $patternNames = @(
            $Element.GetSupportedPatterns() |
                ForEach-Object {
                    [string]$_.ProgrammaticName
                }
        )

        return (
            $patternNames -join ";"
        )
    }
    catch {
        return ""
    }
}


function Get-ParentProcessInfo {
    param(
        [Parameter(Mandatory = $true)]
        [int]$ProcessId
    )

    $currentProcess = Get-CimInstance `
        -ClassName Win32_Process `
        -Filter (
            "ProcessId=" +
            $ProcessId
        ) `
        -ErrorAction SilentlyContinue

    if ($null -eq $currentProcess) {
        return $null
    }

    $parentProcess = Get-CimInstance `
        -ClassName Win32_Process `
        -Filter (
            "ProcessId=" +
            $currentProcess.ParentProcessId
        ) `
        -ErrorAction SilentlyContinue

    if ($null -eq $parentProcess) {
        return $null
    }

    return [pscustomobject]@{
        ProcessId = $parentProcess.ProcessId
        Name = $parentProcess.Name
        ExecutablePath = $parentProcess.ExecutablePath
        CommandLine = $parentProcess.CommandLine
    }
}


$projectRoot = Split-Path `
    -Parent `
    $PSScriptRoot

if (
    [string]::IsNullOrWhiteSpace(
        $OutputDirectory
    )
) {
    $OutputDirectory = Join-Path `
        -Path $projectRoot `
        -ChildPath "logs\assistant_ui"
}
elseif (
    -not [System.IO.Path]::IsPathRooted(
        $OutputDirectory
    )
) {
    $OutputDirectory = Join-Path `
        -Path $projectRoot `
        -ChildPath $OutputDirectory
}

$OutputDirectory = [System.IO.Path]::GetFullPath(
    $OutputDirectory
)

New-Item `
    -ItemType Directory `
    -Path $OutputDirectory `
    -Force |
    Out-Null

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"

$uiCsvPath = Join-Path `
    -Path $OutputDirectory `
    -ChildPath (
        "assistant_ui_" +
        $timestamp +
        ".csv"
    )

$interactiveCsvPath = Join-Path `
    -Path $OutputDirectory `
    -ChildPath (
        "assistant_interactive_" +
        $timestamp +
        ".csv"
    )

$processJsonPath = Join-Path `
    -Path $OutputDirectory `
    -ChildPath (
        "assistant_process_" +
        $timestamp +
        ".json"
    )

$connectionsCsvPath = Join-Path `
    -Path $OutputDirectory `
    -ChildPath (
        "assistant_connections_" +
        $timestamp +
        ".csv"
    )


Write-Step "Searching for assistant.exe."

$assistantProcesses = @(
    Get-Process `
        -Name "assistant" `
        -ErrorAction SilentlyContinue
)

if ($assistantProcesses.Count -eq 0) {
    throw "assistant.exe is not running."
}

$assistant = (
    $assistantProcesses |
        Where-Object {
            $_.MainWindowHandle -ne 0
        } |
        Sort-Object `
            -Property StartTime `
            -Descending |
        Select-Object `
            -First 1
)

if ($null -eq $assistant) {
    throw (
        "assistant.exe is running, " +
        "but its main window was not found."
    )
}

Write-Step (
    "Process found. PID=" +
    $assistant.Id +
    "; Title=" +
    $assistant.MainWindowTitle +
    "."
)


$processCim = Get-CimInstance `
    -ClassName Win32_Process `
    -Filter (
        "ProcessId=" +
        $assistant.Id
    ) `
    -ErrorAction SilentlyContinue

$parentProcessInfo = Get-ParentProcessInfo `
    -ProcessId $assistant.Id

$childProcesses = @(
    Get-CimInstance `
        -ClassName Win32_Process `
        -ErrorAction SilentlyContinue |
        Where-Object {
            $_.ParentProcessId -eq $assistant.Id
        } |
        Select-Object `
            ProcessId,
            ParentProcessId,
            Name,
            ExecutablePath,
            CommandLine
)

$versionInfo = $null

if (
    -not [string]::IsNullOrWhiteSpace(
        [string]$assistant.Path
    ) -and
    (
        Test-Path `
            -LiteralPath $assistant.Path `
            -PathType Leaf
    )
) {
    $assistantFile = Get-Item `
        -LiteralPath $assistant.Path

    $versionInfo = [pscustomobject]@{
        FileDescription = (
            $assistantFile.VersionInfo.FileDescription
        )

        ProductName = (
            $assistantFile.VersionInfo.ProductName
        )

        CompanyName = (
            $assistantFile.VersionInfo.CompanyName
        )

        FileVersion = (
            $assistantFile.VersionInfo.FileVersion
        )

        ProductVersion = (
            $assistantFile.VersionInfo.ProductVersion
        )

        OriginalFilename = (
            $assistantFile.VersionInfo.OriginalFilename
        )
    }
}

$processStartTime = Get-SafeValue `
    -Expression {
        $assistant.StartTime.ToString(
            "o"
        )
    } `
    -Fallback ""

$processCommandLine = ""

if ($null -ne $processCim) {
    $processCommandLine = (
        [string]$processCim.CommandLine
    )
}

$processReport = [ordered]@{
    captured_at = (
        Get-Date
    ).ToString(
        "o"
    )

    process = [ordered]@{
        id = $assistant.Id
        process_name = $assistant.ProcessName
        main_window_title = $assistant.MainWindowTitle
        main_window_handle = (
            $assistant.MainWindowHandle.ToInt64()
        )
        path = $assistant.Path
        start_time = $processStartTime
        command_line = $processCommandLine
    }

    parent_process = $parentProcessInfo
    version_info = $versionInfo
    child_processes = $childProcesses
}

$processReport |
    ConvertTo-Json `
        -Depth 8 |
    Set-Content `
        -LiteralPath $processJsonPath `
        -Encoding UTF8

Write-Step (
    "Process report saved: " +
    $processJsonPath
)


Write-Step "Reading TCP connections."

$connections = @(
    Get-NetTCPConnection `
        -OwningProcess $assistant.Id `
        -ErrorAction SilentlyContinue |
        Select-Object `
            LocalAddress,
            LocalPort,
            RemoteAddress,
            RemotePort,
            State,
            OwningProcess
)

$connections |
    Export-Csv `
        -LiteralPath $connectionsCsvPath `
        -NoTypeInformation `
        -Encoding UTF8

Write-Step (
    "TCP report saved: " +
    $connectionsCsvPath
)


Write-Step "Loading UI Automation assemblies."

Add-Type `
    -AssemblyName UIAutomationClient

Add-Type `
    -AssemblyName UIAutomationTypes


$windowHandle = [System.IntPtr](
    $assistant.MainWindowHandle
)

$rootElement = (
    [System.Windows.Automation.AutomationElement]::FromHandle(
        $windowHandle
    )
)

if ($null -eq $rootElement) {
    throw (
        "UI Automation could not open " +
        "the assistant window."
    )
}

Write-Step "Reading UI Automation tree."

$allCondition = (
    [System.Windows.Automation.Condition]::TrueCondition
)

$elements = $rootElement.FindAll(
    [System.Windows.Automation.TreeScope]::Subtree,
    $allCondition
)

$rows = @()

for (
    $index = 0;
    $index -lt $elements.Count;
    $index++
) {
    $element = $elements.Item(
        $index
    )

    $name = Get-SafeValue `
        -Expression {
            [string]$element.Current.Name
        } `
        -Fallback ""

    $automationId = Get-SafeValue `
        -Expression {
            [string]$element.Current.AutomationId
        } `
        -Fallback ""

    $className = Get-SafeValue `
        -Expression {
            [string]$element.Current.ClassName
        } `
        -Fallback ""

    $controlType = Get-SafeValue `
        -Expression {
            [string]$element.Current.ControlType.ProgrammaticName
        } `
        -Fallback ""

    $frameworkId = Get-SafeValue `
        -Expression {
            [string]$element.Current.FrameworkId
        } `
        -Fallback ""

    $isEnabled = Get-SafeValue `
        -Expression {
            [bool]$element.Current.IsEnabled
        } `
        -Fallback $false

    $isOffscreen = Get-SafeValue `
        -Expression {
            [bool]$element.Current.IsOffscreen
        } `
        -Fallback $true

    $isKeyboardFocusable = Get-SafeValue `
        -Expression {
            [bool]$element.Current.IsKeyboardFocusable
        } `
        -Fallback $false

    $rectangle = Get-SafeValue `
        -Expression {
            $element.Current.BoundingRectangle
        } `
        -Fallback $null

    $left = $null
    $top = $null
    $width = $null
    $height = $null

    if ($null -ne $rectangle) {
        $left = $rectangle.Left
        $top = $rectangle.Top
        $width = $rectangle.Width
        $height = $rectangle.Height
    }

    $patterns = Get-PatternNames `
        -Element $element

    $rows += [pscustomobject]@{
        Index = $index
        Name = $name
        AutomationId = $automationId
        ControlType = $controlType
        ClassName = $className
        FrameworkId = $frameworkId
        Patterns = $patterns
        IsEnabled = $isEnabled
        IsOffscreen = $isOffscreen
        IsKeyboardFocusable = $isKeyboardFocusable
        Left = $left
        Top = $top
        Width = $width
        Height = $height
    }
}

$rows |
    Export-Csv `
        -LiteralPath $uiCsvPath `
        -NoTypeInformation `
        -Encoding UTF8

Write-Step (
    "Full UI report saved: " +
    $uiCsvPath
)


$interactiveRows = @(
    $rows |
        Where-Object {
            $_.Patterns -match (
                "InvokePattern|" +
                "SelectionItemPattern|" +
                "TogglePattern|" +
                "ExpandCollapsePattern|" +
                "ValuePattern|" +
                "LegacyIAccessiblePattern"
            )
        }
)

$interactiveRows |
    Export-Csv `
        -LiteralPath $interactiveCsvPath `
        -NoTypeInformation `
        -Encoding UTF8

Write-Step (
    "Interactive UI report saved: " +
    $interactiveCsvPath
)


Write-Host ""
Write-Host "Interactive UI elements:"
Write-Host ""

if ($interactiveRows.Count -eq 0) {
    Write-Host (
        "No interactive UI Automation " +
        "elements were found."
    )
}
else {
    $interactiveRows |
        Select-Object `
            Index,
            Name,
            AutomationId,
            ControlType,
            ClassName,
            Patterns,
            IsEnabled,
            IsOffscreen |
        Format-Table `
            -AutoSize `
            -Wrap
}

Write-Host ""
Write-Host "Result files:"
Write-Host $processJsonPath
Write-Host $connectionsCsvPath
Write-Host $uiCsvPath
Write-Host $interactiveCsvPath