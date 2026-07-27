[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$OutputDirectory
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"


function Write-Step {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

    Write-Host (
        "[{0}] {1}" -f
        $timestamp,
        $Message
    )
}


$sourceCode = @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;

public sealed class AssistantNativeWindow
{
    public long Handle { get; set; }
    public long ParentHandle { get; set; }
    public int ProcessId { get; set; }
    public int ThreadId { get; set; }
    public int ControlId { get; set; }
    public string ClassName { get; set; }
    public string Text { get; set; }
    public bool Visible { get; set; }
    public bool Enabled { get; set; }
    public int Left { get; set; }
    public int Top { get; set; }
    public int Width { get; set; }
    public int Height { get; set; }
}

public static class AssistantNativeInspector
{
    private delegate bool EnumWindowsCallback(
        IntPtr windowHandle,
        IntPtr parameter
    );

    [StructLayout(LayoutKind.Sequential)]
    private struct RECT
    {
        public int Left;
        public int Top;
        public int Right;
        public int Bottom;
    }

    [DllImport("user32.dll")]
    private static extern bool EnumChildWindows(
        IntPtr parentWindow,
        EnumWindowsCallback callback,
        IntPtr parameter
    );

    [DllImport(
        "user32.dll",
        CharSet = CharSet.Unicode
    )]
    private static extern int GetWindowText(
        IntPtr windowHandle,
        StringBuilder text,
        int maximumLength
    );

    [DllImport("user32.dll")]
    private static extern int GetWindowTextLength(
        IntPtr windowHandle
    );

    [DllImport(
        "user32.dll",
        CharSet = CharSet.Unicode
    )]
    private static extern int GetClassName(
        IntPtr windowHandle,
        StringBuilder className,
        int maximumLength
    );

    [DllImport("user32.dll")]
    private static extern uint GetWindowThreadProcessId(
        IntPtr windowHandle,
        out uint processId
    );

    [DllImport("user32.dll")]
    private static extern IntPtr GetParent(
        IntPtr windowHandle
    );

    [DllImport("user32.dll")]
    private static extern int GetDlgCtrlID(
        IntPtr windowHandle
    );

    [DllImport("user32.dll")]
    private static extern bool IsWindowVisible(
        IntPtr windowHandle
    );

    [DllImport("user32.dll")]
    private static extern bool IsWindowEnabled(
        IntPtr windowHandle
    );

    [DllImport("user32.dll")]
    private static extern bool GetWindowRect(
        IntPtr windowHandle,
        out RECT rectangle
    );

    private static string ReadWindowText(
        IntPtr windowHandle
    )
    {
        int textLength = GetWindowTextLength(
            windowHandle
        );

        int capacity = Math.Max(
            textLength + 1,
            1024
        );

        StringBuilder text = new StringBuilder(
            capacity
        );

        GetWindowText(
            windowHandle,
            text,
            capacity
        );

        return text.ToString();
    }

    private static string ReadClassName(
        IntPtr windowHandle
    )
    {
        StringBuilder className = new StringBuilder(
            1024
        );

        GetClassName(
            windowHandle,
            className,
            className.Capacity
        );

        return className.ToString();
    }

    private static AssistantNativeWindow ReadWindow(
        IntPtr windowHandle
    )
    {
        uint processId;

        uint threadId = GetWindowThreadProcessId(
            windowHandle,
            out processId
        );

        RECT rectangle;

        bool rectangleAvailable = GetWindowRect(
            windowHandle,
            out rectangle
        );

        int left = 0;
        int top = 0;
        int width = 0;
        int height = 0;

        if (rectangleAvailable)
        {
            left = rectangle.Left;
            top = rectangle.Top;

            width = Math.Max(
                0,
                rectangle.Right - rectangle.Left
            );

            height = Math.Max(
                0,
                rectangle.Bottom - rectangle.Top
            );
        }

        return new AssistantNativeWindow
        {
            Handle = windowHandle.ToInt64(),
            ParentHandle = GetParent(
                windowHandle
            ).ToInt64(),
            ProcessId = (int)processId,
            ThreadId = (int)threadId,
            ControlId = GetDlgCtrlID(
                windowHandle
            ),
            ClassName = ReadClassName(
                windowHandle
            ),
            Text = ReadWindowText(
                windowHandle
            ),
            Visible = IsWindowVisible(
                windowHandle
            ),
            Enabled = IsWindowEnabled(
                windowHandle
            ),
            Left = left,
            Top = top,
            Width = width,
            Height = height
        };
    }

    public static AssistantNativeWindow[] Enumerate(
        long rootHandle
    )
    {
        List<AssistantNativeWindow> result =
            new List<AssistantNativeWindow>();

        HashSet<long> processedHandles =
            new HashSet<long>();

        IntPtr rootWindow = new IntPtr(
            rootHandle
        );

        processedHandles.Add(
            rootWindow.ToInt64()
        );

        result.Add(
            ReadWindow(
                rootWindow
            )
        );

        EnumChildWindows(
            rootWindow,
            delegate(
                IntPtr childWindow,
                IntPtr parameter
            )
            {
                long handle = childWindow.ToInt64();

                if (
                    processedHandles.Add(
                        handle
                    )
                )
                {
                    result.Add(
                        ReadWindow(
                            childWindow
                        )
                    );
                }

                return true;
            },
            IntPtr.Zero
        );

        return result.ToArray();
    }
}
'@


if (
    -not (
        "AssistantNativeInspector" -as [type]
    )
) {
    Add-Type `
        -TypeDefinition $sourceCode `
        -Language CSharp
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
        -ChildPath "logs\assistant_native"
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

$windowsFile = Join-Path `
    -Path $OutputDirectory `
    -ChildPath (
        "assistant_windows_{0}.csv" -f
        $timestamp
    )

$processFile = Join-Path `
    -Path $OutputDirectory `
    -ChildPath (
        "assistant_processes_{0}.json" -f
        $timestamp
    )

$connectionsFile = Join-Path `
    -Path $OutputDirectory `
    -ChildPath (
        "assistant_connections_{0}.csv" -f
        $timestamp
    )


Write-Step "Searching for assistant.exe."

$assistantProcesses = @(
    Get-Process `
        -Name "assistant" `
        -ErrorAction SilentlyContinue
)

$assistant = $assistantProcesses |
    Where-Object {
        $_.MainWindowHandle -ne 0
    } |
    Select-Object -First 1

if ($null -eq $assistant) {
    throw (
        "assistant.exe with a main window was not found."
    )
}

Write-Step (
    "assistant.exe found. PID={0}; Handle={1}." -f
    $assistant.Id,
    $assistant.MainWindowHandle
)


Write-Step "Searching for ast_service.exe."

$serviceProcesses = @(
    Get-CimInstance `
        -ClassName Win32_Process `
        -Filter "Name='ast_service.exe'" `
        -ErrorAction SilentlyContinue
)

if ($serviceProcesses.Count -eq 0) {
    Write-Step "ast_service.exe was not found."
}
else {
    foreach ($serviceProcess in $serviceProcesses) {
        Write-Step (
            "ast_service.exe found. PID={0}." -f
            $serviceProcess.ProcessId
        )
    }
}


Write-Step "Reading native windows."

$nativeWindows = @(
    [AssistantNativeInspector]::Enumerate(
        $assistant.MainWindowHandle.ToInt64()
    )
)

$nativeWindows |
    Sort-Object `
        ParentHandle,
        Top,
        Left |
    Export-Csv `
        -LiteralPath $windowsFile `
        -NoTypeInformation `
        -Encoding UTF8

Write-Step (
    "Native windows found: {0}." -f
    $nativeWindows.Count
)


$assistantCim = Get-CimInstance `
    -ClassName Win32_Process `
    -Filter (
        "ProcessId={0}" -f
        $assistant.Id
    ) `
    -ErrorAction SilentlyContinue

$assistantReport = [ordered]@{
    process_id = $assistant.Id
    process_name = $assistant.ProcessName
    window_title = $assistant.MainWindowTitle
    window_handle = (
        $assistant.MainWindowHandle.ToInt64()
    )
    executable_path = $null
    command_line = $null
    parent_process_id = $null
}

if ($null -ne $assistantCim) {
    $assistantReport.executable_path = (
        $assistantCim.ExecutablePath
    )

    $assistantReport.command_line = (
        $assistantCim.CommandLine
    )

    $assistantReport.parent_process_id = (
        $assistantCim.ParentProcessId
    )
}

$serviceReport = @()

foreach ($serviceProcess in $serviceProcesses) {
    $serviceReport += [ordered]@{
        process_id = $serviceProcess.ProcessId
        parent_process_id = (
            $serviceProcess.ParentProcessId
        )
        process_name = $serviceProcess.Name
        executable_path = (
            $serviceProcess.ExecutablePath
        )
        command_line = (
            $serviceProcess.CommandLine
        )
        creation_date = (
            $serviceProcess.CreationDate
        )
    }
}

$fullProcessReport = [ordered]@{
    captured_at = (
        Get-Date
    ).ToString(
        "o"
    )
    assistant = $assistantReport
    ast_service = $serviceReport
}

$fullProcessReport |
    ConvertTo-Json `
        -Depth 8 |
    Set-Content `
        -LiteralPath $processFile `
        -Encoding UTF8


Write-Step "Reading network endpoints."

$targetProcessIds = @(
    [int]$assistant.Id
)

foreach ($serviceProcess in $serviceProcesses) {
    $targetProcessIds += (
        [int]$serviceProcess.ProcessId
    )
}

$connectionRows = @()

foreach ($targetProcessId in $targetProcessIds) {
    $targetProcessName = "unknown"

    try {
        $targetProcess = Get-Process `
            -Id $targetProcessId `
            -ErrorAction Stop

        $targetProcessName = (
            $targetProcess.ProcessName
        )
    }
    catch {
        $targetProcessName = "unknown"
    }

    $tcpConnections = @(
        Get-NetTCPConnection `
            -OwningProcess $targetProcessId `
            -ErrorAction SilentlyContinue
    )

    foreach ($connection in $tcpConnections) {
        $connectionRows += [pscustomobject]@{
            Protocol = "TCP"
            ProcessId = $targetProcessId
            ProcessName = $targetProcessName
            LocalAddress = $connection.LocalAddress
            LocalPort = $connection.LocalPort
            RemoteAddress = $connection.RemoteAddress
            RemotePort = $connection.RemotePort
            State = $connection.State
        }
    }

    $udpEndpoints = @(
        Get-NetUDPEndpoint `
            -OwningProcess $targetProcessId `
            -ErrorAction SilentlyContinue
    )

    foreach ($endpoint in $udpEndpoints) {
        $connectionRows += [pscustomobject]@{
            Protocol = "UDP"
            ProcessId = $targetProcessId
            ProcessName = $targetProcessName
            LocalAddress = $endpoint.LocalAddress
            LocalPort = $endpoint.LocalPort
            RemoteAddress = ""
            RemotePort = ""
            State = ""
        }
    }
}

$connectionRows |
    Export-Csv `
        -LiteralPath $connectionsFile `
        -NoTypeInformation `
        -Encoding UTF8


Write-Host ""
Write-Host "Native windows:"
Write-Host ""

$nativeWindows |
    Sort-Object `
        Top,
        Left |
    Format-Table `
        Handle,
        ParentHandle,
        ControlId,
        ClassName,
        Text,
        Visible,
        Enabled,
        Left,
        Top,
        Width,
        Height `
        -AutoSize `
        -Wrap

Write-Host ""
Write-Host "Network endpoints:"
Write-Host ""

if ($connectionRows.Count -eq 0) {
    Write-Host "No TCP or UDP endpoints were found."
}
else {
    $connectionRows |
        Format-Table `
            Protocol,
            ProcessId,
            ProcessName,
            LocalAddress,
            LocalPort,
            RemoteAddress,
            RemotePort,
            State `
            -AutoSize `
            -Wrap
}

Write-Host ""
Write-Host "Result files:"
Write-Host $windowsFile
Write-Host $processFile
Write-Host $connectionsFile