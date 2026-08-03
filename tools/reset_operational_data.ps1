[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$SqlFile = Join-Path $PSScriptRoot 'reset_operational_data.sql'
$OfficialDirectory = Join-Path $ProjectRoot 'data\official'
$InboxDirectory = Join-Path $ProjectRoot 'data\edo_inbox'


function Write-Step {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    Write-Host ''
    Write-Host ('==> ' + $Message) -ForegroundColor Cyan
}


function Assert-ExitCode {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    if ($LASTEXITCODE -ne 0) {
        throw ($Message + ' Exit code: ' + $LASTEXITCODE + '.')
    }
}


function Clear-DirectoryContent {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
        return
    }

    $EmptyDirectoryName = 'gis_mt_empty_' + [Guid]::NewGuid().ToString('N')
    $EmptyDirectory = Join-Path $env:TEMP $EmptyDirectoryName

    New-Item -ItemType Directory -Path $EmptyDirectory -Force | Out-Null

    try {
        & robocopy.exe $EmptyDirectory $Path /MIR /R:1 /W:1 /NFL /NDL /NJH /NJS /NP /XJ | Out-Null

        $RobocopyExitCode = $LASTEXITCODE

        if ($RobocopyExitCode -ge 8) {
            throw (
                'Robocopy failed for directory: ' +
                $Path +
                '. Exit code: ' +
                $RobocopyExitCode +
                '.'
            )
        }
    }
    finally {
        if (Test-Path -LiteralPath $EmptyDirectory) {
            Remove-Item -LiteralPath $EmptyDirectory -Recurse -Force -ErrorAction SilentlyContinue
        }
    }

    $RemainingItems = @(Get-ChildItem -LiteralPath $Path -Force -ErrorAction SilentlyContinue)

    if ($RemainingItems.Count -ne 0) {
        throw ('Directory is not empty after cleanup: ' + $Path)
    }
}


$PreviousLocation = Get-Location

try {
    Set-Location $ProjectRoot

    Write-Step 'Checking reset files'

    if (-not (Test-Path -LiteralPath $SqlFile)) {
        throw ('SQL file not found: ' + $SqlFile)
    }


    Write-Step 'Checking Docker Compose configuration'

    docker compose config --quiet
    Assert-ExitCode 'Docker Compose configuration is invalid.'


    Write-Step 'Starting MySQL and RabbitMQ'

    docker compose up -d mysql rabbitmq
    Assert-ExitCode 'Failed to start MySQL or RabbitMQ.'


    Write-Step 'Stopping application services'

    docker compose stop pipeline-dispatcher control-web
    Assert-ExitCode 'Failed to stop application services.'


    Write-Step 'Reading RabbitMQ virtual host'

    $VhostOutput = docker compose exec -T rabbitmq sh -lc 'printf "%s" "${RABBITMQ_DEFAULT_VHOST:-/}"'
    Assert-ExitCode 'Failed to read RabbitMQ virtual host.'

    $Vhost = ($VhostOutput | Out-String).Trim()

    if ([string]::IsNullOrWhiteSpace($Vhost)) {
        $Vhost = '/'
    }

    Write-Host ('RabbitMQ vhost: ' + $Vhost)


    Write-Step 'Reading RabbitMQ queues'

    $QueueOutput = docker compose exec -T rabbitmq rabbitmqctl -q -p $Vhost list_queues name
    Assert-ExitCode 'Failed to read RabbitMQ queues.'

    $Queues = @(
        $QueueOutput |
        ForEach-Object { $_.ToString().Trim() } |
        Where-Object {
            (-not [string]::IsNullOrWhiteSpace($_)) -and
            (
                ($_ -like 'gis_mt.jobs*') -or
                ($_ -like 'gis_mt.auth*') -or
                ($_ -like 'gis_mt.pipeline*')
            )
        } |
        Sort-Object -Unique
    )

    if ($Queues.Count -eq 0) {
        Write-Host 'GIS MT RabbitMQ queues were not found.'
    }
    else {
        foreach ($Queue in $Queues) {
            Write-Host ('Purging queue: ' + $Queue)

            docker compose exec -T rabbitmq rabbitmqctl -q -p $Vhost purge_queue $Queue
            Assert-ExitCode ('Failed to purge RabbitMQ queue: ' + $Queue)
        }
    }


    Write-Step 'Clearing official document directory'

    Clear-DirectoryContent -Path $OfficialDirectory
    Write-Host ('Cleared: ' + $OfficialDirectory)


    Write-Step 'Clearing EDO inbox directory'

    Clear-DirectoryContent -Path $InboxDirectory
    Write-Host ('Cleared: ' + $InboxDirectory)


    Write-Step 'Copying SQL reset file to MySQL container'

    docker compose cp $SqlFile 'mysql:/tmp/reset_operational_data.sql'
    Assert-ExitCode 'Failed to copy SQL reset file to MySQL container.'


    Write-Step 'Resetting operational database data'

    docker compose exec -T mysql sh -lc 'mysql --default-character-set=utf8mb4 --show-warnings -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" < /tmp/reset_operational_data.sql'
    Assert-ExitCode 'Database reset failed.'


    Write-Step 'Removing temporary SQL file'

    docker compose exec -T mysql rm -f /tmp/reset_operational_data.sql

    if ($LASTEXITCODE -ne 0) {
        Write-Warning 'Temporary SQL file could not be removed.'
    }


    Write-Step 'Checking document directories'

    $OfficialItems = @(Get-ChildItem -LiteralPath $OfficialDirectory -Force -ErrorAction SilentlyContinue)
    $InboxItems = @(Get-ChildItem -LiteralPath $InboxDirectory -Force -ErrorAction SilentlyContinue)

    if ($OfficialItems.Count -ne 0) {
        throw ('Official directory is not empty: ' + $OfficialDirectory)
    }

    if ($InboxItems.Count -ne 0) {
        throw ('EDO inbox directory is not empty: ' + $InboxDirectory)
    }


    Write-Host ''
    Write-Host 'OPERATIONAL DATA RESET COMPLETED' -ForegroundColor Green
    Write-Host ''
    Write-Host 'The control-web service remains stopped.'
    Write-Host 'The pipeline-dispatcher service remains stopped.'
    Write-Host 'Do not start the application before installing the new logic.'
}
finally {
    Set-Location $PreviousLocation
}