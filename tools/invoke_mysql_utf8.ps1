[CmdletBinding()]
param(
    [Parameter(
        Mandatory = $true,
        Position = 0
    )]
    [string]$SqlFile,

    [Parameter(
        Mandatory = $false
    )]
    [string]$EnvFile = ".env"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path `
    -Parent `
    $PSScriptRoot

Set-Location `
    -LiteralPath $projectRoot

if (
    -not [System.IO.Path]::IsPathRooted(
        $SqlFile
    )
) {
    $SqlFile = Join-Path `
        $projectRoot `
        $SqlFile
}

$SqlFile = [System.IO.Path]::GetFullPath(
    $SqlFile
)

if (
    -not (
        Test-Path `
            -LiteralPath $SqlFile `
            -PathType Leaf
    )
) {
    throw (
        "SQL file was not found: " +
        $SqlFile
    )
}

if (
    -not [System.IO.Path]::IsPathRooted(
        $EnvFile
    )
) {
    $EnvFile = Join-Path `
        $projectRoot `
        $EnvFile
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

$temporaryName = (
    "/tmp/cz_async_" +
    [guid]::NewGuid().ToString(
        "N"
    ) +
    ".sql"
)

Write-Host (
    "Copying UTF-8 SQL file into MySQL container."
)

& docker compose `
    --env-file $EnvFile `
    cp `
    $SqlFile `
    (
        "mysql:" +
        $temporaryName
    )

if ($LASTEXITCODE -ne 0) {
    throw (
        "Failed to copy SQL file into MySQL container."
    )
}

try {
    Write-Host (
        "Executing SQL file with utf8mb4."
    )

    $containerCommand = (
        'export MYSQL_PWD="$MYSQL_PASSWORD"; ' +
        'exec mysql ' +
        '--default-character-set=utf8mb4 ' +
        '--user="$MYSQL_USER" ' +
        '"$MYSQL_DATABASE" ' +
        '< "' +
        $temporaryName +
        '"'
    )

    & docker compose `
        --env-file $EnvFile `
        exec `
        -T `
        mysql `
        sh `
        -c `
        $containerCommand

    if ($LASTEXITCODE -ne 0) {
        throw (
            "MySQL command failed with exit code " +
            $LASTEXITCODE +
            "."
        )
    }
}
finally {
    & docker compose `
        --env-file $EnvFile `
        exec `
        -T `
        mysql `
        rm `
        -f `
        $temporaryName |
    Out-Null
}

Write-Host (
    "SQL file executed successfully."
)