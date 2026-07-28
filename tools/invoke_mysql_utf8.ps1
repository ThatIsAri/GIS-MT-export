[CmdletBinding(
    DefaultParameterSetName = "File"
)]
param(
    [Parameter(
        Mandatory = $true,
        Position = 0,
        ParameterSetName = "File"
    )]
    [string]$SqlFile,

    [Parameter(
        Mandatory = $true,
        ParameterSetName = "Text"
    )]
    [AllowEmptyString()]
    [string]$SqlText,

    [Parameter(
        Mandatory = $true,
        ValueFromPipeline = $true,
        ParameterSetName = "Pipeline"
    )]
    [AllowEmptyString()]
    [string]$InputObject,

    [Parameter(
        Mandatory = $false
    )]
    [string]$EnvFile = ".env",

    [Parameter(
        Mandatory = $false
    )]
    [switch]$Table
)

begin {
    Set-StrictMode -Version Latest
    $ErrorActionPreference = "Stop"

    $pipelineParts = New-Object `
        "System.Collections.Generic.List[string]"

    $projectRoot = Split-Path `
        -Parent `
        $PSScriptRoot

    $originalLocation = Get-Location

    $utf8WithoutBom = New-Object `
        System.Text.UTF8Encoding `
        $false

    $utf8Strict = New-Object `
        System.Text.UTF8Encoding `
        $false, `
        $true

    $previousOutputEncoding = $OutputEncoding
    $previousConsoleOutputEncoding = (
        [Console]::OutputEncoding
    )

    $hostTemporaryFile = $null
    $containerTemporaryFile = $null
    $containerFileCreated = $false
}

process {
    if (
        $PSCmdlet.ParameterSetName -eq "Pipeline"
    ) {
        $pipelineParts.Add(
            $InputObject
        )
    }
}

end {
    try {
        Set-Location `
            -LiteralPath $projectRoot

        $OutputEncoding = $utf8WithoutBom
        [Console]::OutputEncoding = (
            $utf8WithoutBom
        )

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

        switch (
            $PSCmdlet.ParameterSetName
        ) {
            "File" {
                if (
                    -not [System.IO.Path]::IsPathRooted(
                        $SqlFile
                    )
                ) {
                    $SqlFile = Join-Path `
                        $projectRoot `
                        $SqlFile
                }

                $SqlFile = (
                    [System.IO.Path]::GetFullPath(
                        $SqlFile
                    )
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

                $sqlBytes = (
                    [System.IO.File]::ReadAllBytes(
                        $SqlFile
                    )
                )

                try {
                    $resolvedSqlText = (
                        $utf8Strict.GetString(
                            $sqlBytes
                        )
                    )
                }
                catch [System.Text.DecoderFallbackException] {
                    throw (
                        "SQL file must be encoded " +
                        "as UTF-8: " +
                        $SqlFile
                    )
                }
            }

            "Text" {
                $resolvedSqlText = $SqlText
            }

            "Pipeline" {
                $resolvedSqlText = (
                    [string]::Join(
                        [Environment]::NewLine,
                        $pipelineParts
                    )
                )
            }

            default {
                throw (
                    "Unknown parameter set: " +
                    $PSCmdlet.ParameterSetName
                )
            }
        }

        if (
            $resolvedSqlText.Length -gt 0 -and
            $resolvedSqlText[0] -eq (
                [char]0xFEFF
            )
        ) {
            $resolvedSqlText = (
                $resolvedSqlText.Substring(1)
            )
        }

        if (
            [string]::IsNullOrWhiteSpace(
                $resolvedSqlText
            )
        ) {
            throw "SQL text is empty."
        }

        $temporaryId = (
            [guid]::NewGuid().ToString(
                "N"
            )
        )

        $hostTemporaryFile = Join-Path `
            ([System.IO.Path]::GetTempPath()) `
            (
                "cz_async_" +
                $temporaryId +
                ".sql"
            )

        $containerTemporaryFile = (
            "/tmp/cz_async_" +
            $temporaryId +
            ".sql"
        )

        [System.IO.File]::WriteAllText(
            $hostTemporaryFile,
            $resolvedSqlText,
            $utf8WithoutBom
        )

        Write-Host (
            "Copying UTF-8 SQL into " +
            "MySQL container."
        )

        & docker compose `
            --ansi never `
            --env-file $EnvFile `
            cp `
            $hostTemporaryFile `
            (
                "mysql:" +
                $containerTemporaryFile
            )

        if ($LASTEXITCODE -ne 0) {
            throw (
                "Failed to copy SQL into " +
                "MySQL container."
            )
        }

        $containerFileCreated = $true

        if ($Table) {
            $outputArguments = "--table "
        }
        else {
            $outputArguments = (
                "--batch --raw "
            )
        }

        $containerCommand = (
            'MYSQL_PWD="$MYSQL_PASSWORD" ' +
            'exec mysql ' +
            '--default-character-set=utf8mb4 ' +
            $outputArguments +
            '--user="$MYSQL_USER" ' +
            '"$MYSQL_DATABASE" ' +
            '< "' +
            $containerTemporaryFile +
            '"'
        )

        Write-Host (
            "Executing SQL with utf8mb4."
        )

        & docker compose `
            --ansi never `
            --env-file $EnvFile `
            exec `
            -T `
            mysql `
            sh `
            -lc `
            $containerCommand

        $mysqlExitCode = $LASTEXITCODE

        if ($mysqlExitCode -ne 0) {
            throw (
                "MySQL command failed with " +
                "exit code " +
                $mysqlExitCode +
                "."
            )
        }

        Write-Host (
            "SQL executed successfully."
        )
    }
    finally {
        if (
            $containerFileCreated -and
            $containerTemporaryFile
        ) {
            & docker compose `
                --ansi never `
                --env-file $EnvFile `
                exec `
                -T `
                mysql `
                rm `
                -f `
                $containerTemporaryFile `
                2>$null |
            Out-Null
        }

        if (
            $hostTemporaryFile -and
            (
                Test-Path `
                    -LiteralPath `
                    $hostTemporaryFile
            )
        ) {
            Remove-Item `
                -LiteralPath `
                $hostTemporaryFile `
                -Force `
                -ErrorAction SilentlyContinue
        }

        $OutputEncoding = (
            $previousOutputEncoding
        )

        [Console]::OutputEncoding = (
            $previousConsoleOutputEncoding
        )

        Set-Location `
            -LiteralPath `
            $originalLocation
    }
}