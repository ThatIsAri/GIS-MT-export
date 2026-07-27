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

    Write-Host (
        "[{0}] {1}" -f
        (Get-Date -Format "yyyy-MM-dd HH:mm:ss"),
        $Message
    )
}


$sourceCode = @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;

public sealed class AssistantWindowRecord
{
    public long Handle { get; set; }
    public long ParentHandle { get; set; }
    public long OwnerHandle { get; set; }
    public int ProcessId { get; set; }
    public int ThreadId { get; set; }
    public int ControlId { get; set; }
    public bool TopLevel { get; set; }
    public bool Visible { get; set; }
    public bool Enabled { get; set; }
    public string ClassName { get; set; }
    public string Text { get; set; }
    public int Left { get; set; }
    public int Top { get; set; }
    public int Width { get; set; }
    public int Height { get; set; }
}

public static class AssistantWindowScanner
{
    private const uint GW_OWNER = 4;

    private delegate bool EnumWindowCallback(
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
    private static extern bool EnumWindows(
        EnumWindowCallback callback,
        IntPtr parameter
    );

    [DllImport("user32.dll")]
    private static extern bool EnumChildWindows(
        IntPtr parentWindow,
        EnumWindowCallback callback,
        IntPtr parameter
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
    private static extern IntPtr GetWindow(
        IntPtr windowHandle,
        uint command
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

    private static string ReadText(
        IntPtr windowHandle
    )
    {
        int length = GetWindowTextLength(
            windowHandle
        );

        int capacity = Math.Max(
            length + 1,
            2048
        );

        StringBuilder value = new StringBuilder(
            capacity
        );

        GetWindowText(
            windowHandle,
            value,
            capacity
        );

        return value.ToString();
    }

    private static string ReadClassName(
        IntPtr windowHandle
    )
    {
        StringBuilder value = new StringBuilder(
            1024
        );

        GetClassName(
            windowHandle,
            value,
            value.Capacity
        );

        return value.ToString();
    }

    private static AssistantWindowRecord ReadWindow(
        IntPtr windowHandle,
        bool topLevel
    )
    {
        uint processId;

        uint threadId = GetWindowThreadProcessId(
            windowHandle,
            out processId
        );

        RECT rectangle;

        bool hasRectangle = GetWindowRect(
            windowHandle,
            out rectangle
        );

        int left = 0;
        int top = 0;
        int width = 0;
        int height = 0;

        if (hasRectangle)
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

        return new AssistantWindowRecord
        {
            Handle = windowHandle.ToInt64(),
            ParentHandle = GetParent(
                windowHandle
            ).ToInt64(),
            OwnerHandle = GetWindow(
                windowHandle,
                GW_OWNER
            ).ToInt64(),
            ProcessId = (int)processId,
            ThreadId = (int)threadId,
            ControlId = GetDlgCtrlID(
                windowHandle
            ),
            TopLevel = topLevel,
            Visible = IsWindowVisible(
                windowHandle
            ),
            Enabled = IsWindowEnabled(
                windowHandle
            ),
            ClassName = ReadClassName(
                windowHandle
            ),
            Text = ReadText(
                windowHandle
            ),
            Left = left,
            Top = top,
            Width = width,
            Height = height
        };
    }

    public static AssistantWindowRecord[] Scan(
        int targetProcessId
    )
    {
        List<AssistantWindowRecord> result =
            new List<AssistantWindowRecord>();

        HashSet<long> processed =
            new HashSet<long>();

        EnumWindows(
            delegate(
                IntPtr topLevelWindow,
                IntPtr parameter
            )
            {
                uint processId;

                GetWindowThreadProcessId(
                    topLevelWindow,
                    out processId
                );

                if (
                    processId !=
                    (uint)targetProcessId
                )
                {
                    return true;
                }

                long topLevelHandle =
                    topLevelWindow.ToInt64();

                if (
                    processed.Add(
                        topLevelHandle
                    )
                )
                {
                    result.Add(
                        ReadWindow(
                            topLevelWindow,
                            true
                        )
                    );
                }

                EnumChildWindows(
                    topLevelWindow,
                    delegate(
                        IntPtr childWindow,
                        IntPtr childParameter
                    )
                    {
                        long childHandle =
                            childWindow.ToInt64();

                        if (
                            processed.Add(
                                childHandle
                            )
                        )
                        {
                            result.Add(
                                ReadWindow(
                                    childWindow,
                                    false
                                )
                            );
                        }

                        return true;
                    },
                    IntPtr.Zero
                );

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
        "AssistantWindowScanner" -as [type]
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
        -ChildPath "logs\assistant_all_windows"
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

$outputFile = Join-Path `
    -Path $OutputDirectory `
    -ChildPath (
        "assistant_all_windows_{0}.csv" -f
        $timestamp
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

foreach ($process in $assistantProcesses) {
    Write-Step (
        "Scanning PID={0}." -f
        $process.Id
    )
}

$allRows = @()

foreach ($process in $assistantProcesses) {
    $processRows = @(
        [AssistantWindowScanner]::Scan(
            $process.Id
        )
    )

    foreach ($row in $processRows) {
        $allRows += $row
    }
}

if ($allRows.Count -eq 0) {
    throw (
        "No windows were found for assistant.exe."
    )
}

$allRows |
    Sort-Object `
        ProcessId,
        TopLevel,
        Top,
        Left |
    Export-Csv `
        -LiteralPath $outputFile `
        -NoTypeInformation `
        -Encoding UTF8


Write-Step (
    "Windows found: {0}." -f
    $allRows.Count
)

Write-Host ""
Write-Host "Visible top-level windows:"
Write-Host ""

$visibleTopLevel = @(
    $allRows |
        Where-Object {
            $_.TopLevel -and
            $_.Visible -and
            $_.Width -gt 0 -and
            $_.Height -gt 0
        }
)

if ($visibleTopLevel.Count -eq 0) {
    Write-Host (
        "No visible top-level windows " +
        "with non-zero size were found."
    )
}
else {
    $visibleTopLevel |
        Format-Table `
            Handle,
            OwnerHandle,
            ProcessId,
            ThreadId,
            ClassName,
            Text,
            Enabled,
            Left,
            Top,
            Width,
            Height `
            -AutoSize `
            -Wrap
}

Write-Host ""
Write-Host "All windows with text:"
Write-Host ""

$windowsWithText = @(
    $allRows |
        Where-Object {
            -not [string]::IsNullOrWhiteSpace(
                [string]$_.Text
            )
        }
)

if ($windowsWithText.Count -eq 0) {
    Write-Host "No windows with text were found."
}
else {
    $windowsWithText |
        Format-Table `
            Handle,
            ParentHandle,
            OwnerHandle,
            TopLevel,
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
}

Write-Host ""
Write-Host "Output file:"
Write-Host $outputFile