param(
    [int]$PostgresTimeoutSeconds = 60,
    [int]$RedisTimeoutSeconds = 30
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Ok {
    param([string]$Message)
    Write-Host "OK: $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "WARN: $Message" -ForegroundColor Yellow
}

function Fail {
    param([string]$Message)
    Write-Host ""
    Write-Host "ERROR: $Message" -ForegroundColor Red
    exit 1
}

function Test-PortOpen {
    param(
        [string]$HostName,
        [int]$Port
    )

    try {
        $client = [System.Net.Sockets.TcpClient]::new()
        $connect = $client.BeginConnect($HostName, $Port, $null, $null)
        $isOpen = $connect.AsyncWaitHandle.WaitOne(1000, $false)
        if ($isOpen) {
            $client.EndConnect($connect)
        }
        $client.Close()
        return $isOpen
    }
    catch {
        return $false
    }
}

function Get-PortOwnerSummary {
    param([int]$Port)

    $matches = netstat -ano | Select-String "LISTENING\s+\d+$"
    foreach ($match in $matches) {
        $line = $match.Line.Trim()
        if ($line -match "^\S+\s+\S+:$Port\s+\S+\s+LISTENING\s+(\d+)$") {
            $processId = $Matches[1]
            $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
            if ($process) {
                return "PID $processId ($($process.ProcessName))"
            }
            return "PID $processId"
        }
    }

    return "unknown process"
}

function Get-DotEnvValue {
    param(
        [string]$Name,
        [string]$DefaultValue
    )

    if (-not (Test-Path ".env")) {
        return $DefaultValue
    }

    $line = Get-Content ".env" | Where-Object { $_ -match "^\s*$([regex]::Escape($Name))\s*=" } | Select-Object -First 1
    if (-not $line) {
        return $DefaultValue
    }

    $value = ($line -split "=", 2)[1].Trim()
    return $value.Trim('"').Trim("'")
}

function Get-EnvironmentOrDotEnvValue {
    param(
        [string]$Name,
        [string]$DefaultValue
    )

    $value = [Environment]::GetEnvironmentVariable($Name)
    if (-not [string]::IsNullOrWhiteSpace($value)) {
        return $value.Trim('"').Trim("'")
    }

    return Get-DotEnvValue -Name $Name -DefaultValue $DefaultValue
}

function Test-TruthyValue {
    param([string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $false
    }

    $normalized = $Value.Trim().ToLowerInvariant()
    return $normalized -in @("1", "true", "yes", "y", "on")
}

function ConvertTo-ProcessArguments {
    param([string[]]$Arguments)

    $quoted = foreach ($arg in $Arguments) {
        if ($null -eq $arg) {
            '""'
        }
        elseif ($arg -match '[\s"]') {
            '"' + ($arg -replace '"', '\"') + '"'
        }
        else {
            $arg
        }
    }

    return ($quoted -join " ")
}

function ConvertTo-SingleQuotedPowerShellLiteral {
    param([string]$Value)

    return "'" + ($Value -replace "'", "''") + "'"
}

function Invoke-NativeCommand {
    param(
        [string[]]$Command,
        [string]$LogFile,
        [switch]$WriteToHost
    )

    $exe = $Command[0]
    $args = @()
    if ($Command.Length -gt 1) {
        $args = $Command[1..($Command.Length - 1)]
    }

    $psi = [System.Diagnostics.ProcessStartInfo]::new()
    $psi.FileName = $exe
    $psi.Arguments = ConvertTo-ProcessArguments -Arguments $args
    $psi.WorkingDirectory = (Get-Location).Path
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true

    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $psi

    [void]$process.Start()
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    $process.WaitForExit()

    if ($stdout) {
        Add-Content -Path $LogFile -Value $stdout
        if ($WriteToHost) {
            Write-Host $stdout.TrimEnd()
        }
    }
    if ($stderr) {
        Add-Content -Path $LogFile -Value $stderr
        if ($WriteToHost) {
            Write-Host $stderr.TrimEnd()
        }
    }

    return [pscustomobject]@{
        ExitCode = $process.ExitCode
        StdOut = $stdout
        StdErr = $stderr
    }
}

function Invoke-Logged {
    param(
        [string]$Description,
        [string[]]$Command,
        [string]$LogFile
    )

    Write-Step $Description
    Add-Content -Path $LogFile -Value ""
    Add-Content -Path $LogFile -Value "### $Description"
    Add-Content -Path $LogFile -Value "### $(Get-Date -Format o)"
    Add-Content -Path $LogFile -Value "### $($Command -join ' ')"

    $result = Invoke-NativeCommand -Command $Command -LogFile $LogFile -WriteToHost
    if ($result.ExitCode -ne 0) {
        Fail "$Description failed with exit code $($result.ExitCode). See log: $LogFile"
    }
}

function Wait-Postgres {
    param(
        [int]$TimeoutSeconds,
        [string]$PostgresUser,
        [string]$PostgresDb,
        [string]$LogFile
    )

    Write-Step "Waiting for Postgres to be ready"
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $result = Invoke-NativeCommand `
            -Command @("docker", "compose", "exec", "-T", "postgres", "pg_isready", "-U", $PostgresUser, "-d", $PostgresDb) `
            -LogFile $LogFile
        if ($result.ExitCode -eq 0) {
            Write-Ok "Postgres is ready"
            return
        }
        Start-Sleep -Seconds 2
    }

    Fail "Postgres did not become ready within $TimeoutSeconds seconds. Check Docker Desktop and port 5432. See log: $LogFile"
}

function Wait-Redis {
    param(
        [int]$TimeoutSeconds,
        [string]$LogFile
    )

    Write-Step "Checking Redis"
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $result = Invoke-NativeCommand `
            -Command @("docker", "compose", "exec", "-T", "redis", "redis-cli", "ping") `
            -LogFile $LogFile
        if ($result.ExitCode -eq 0 -and $result.StdOut -match "PONG") {
            Write-Ok "Redis is running"
            return
        }
        Start-Sleep -Seconds 2
    }

    Fail "Redis did not respond within $TimeoutSeconds seconds. See log: $LogFile"
}

function Wait-HttpEndpoint {
    param(
        [string]$Name,
        [string]$Url,
        [int]$TimeoutSeconds,
        [string]$LogFile
    )

    Write-Step "Waiting for $Name to be ready"
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-RestMethod -Uri $Url -TimeoutSec 2
            if ($null -ne $response) {
                Write-Ok "$Name is ready at $Url"
                return
            }
        }
        catch {
            Start-Sleep -Seconds 1
        }
    }

    Write-Host ""
    Write-Host "Last FastAPI log lines:" -ForegroundColor Yellow
    if (Test-Path $LogFile) {
        Get-Content -Path $LogFile -Tail 80
    }
    else {
        Write-Host "Log file not found: $LogFile" -ForegroundColor Yellow
    }
    Fail "$Name did not become ready within $TimeoutSeconds seconds. Check the FastAPI log: $LogFile"
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path (Join-Path $ScriptDir "..")
Set-Location $ProjectRoot

$RequiredRootFiles = @(
    "docker-compose.yml",
    "alembic.ini",
    "pyproject.toml",
    "api\main.py",
    "ui\app.py"
)

Write-Step "Validating AVM-v2 project root"
foreach ($path in $RequiredRootFiles) {
    if (-not (Test-Path $path)) {
        Fail "This script must run from the AVM-v2 project root. Missing: $path"
    }
}
Write-Ok "Project root: $ProjectRoot"

$LogDir = Join-Path $ProjectRoot "logs\startup"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$StartupLog = Join-Path $LogDir "startup-$Timestamp.log"
$ApiLog = Join-Path $LogDir "api-$Timestamp.log"
$StreamlitLog = Join-Path $LogDir "streamlit-$Timestamp.log"
$SchedulerLog = Join-Path $LogDir "scheduler-$Timestamp.log"
$ApiRunner = Join-Path $LogDir "run-api-$Timestamp.ps1"
$StreamlitRunner = Join-Path $LogDir "run-streamlit-$Timestamp.ps1"
$SchedulerRunner = Join-Path $LogDir "run-scheduler-$Timestamp.ps1"
$SchedulerPidFile = Join-Path $LogDir "scheduler-$Timestamp.pid"

"AVM-v2 startup $(Get-Date -Format o)" | Set-Content -Path $StartupLog
Write-Ok "Startup log: $StartupLog"

Write-Step "Checking local environment"
if (-not (Test-Path ".env")) {
    Fail ".env does not exist. Create it from .env.example and keep local URLs using localhost."
}

$EnvText = Get-Content -Raw ".env"
if ($EnvText -match "(?im)^\s*(DATABASE_URL|SYNC_DATABASE_URL|DATABASE_URL_SYNC)\s*=.*@postgres:") {
    Fail ".env is configured for Docker-internal DB host '@postgres:'. For local Windows mode, use '@localhost:5432'. The script will not modify .env automatically."
}
Write-Ok ".env exists and database URLs look local"

$PythonExe = ".\.venv-win\Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    Fail ".venv-win was not found. Recreate it with: python -m venv .venv-win; .\.venv-win\Scripts\Activate.ps1; python -m pip install --upgrade pip; pip install -r requirements.txt"
}
Write-Ok "Using Python: $PythonExe"

$ApiPort = [int](Get-DotEnvValue -Name "API_PORT" -DefaultValue "8000")
$StreamlitPort = [int](Get-DotEnvValue -Name "STREAMLIT_PORT" -DefaultValue "8501")
$PostgresPort = [int](Get-DotEnvValue -Name "POSTGRES_PORT" -DefaultValue "5432")
$PostgresUser = Get-DotEnvValue -Name "POSTGRES_USER" -DefaultValue "avm"
$PostgresDb = Get-DotEnvValue -Name "POSTGRES_DB" -DefaultValue "avm"
$StartSchedulerFlag = Get-EnvironmentOrDotEnvValue `
    -Name "AVM_START_SCHEDULER" `
    -DefaultValue (Get-EnvironmentOrDotEnvValue -Name "START_SCHEDULER" -DefaultValue "false")
$StartScheduler = Test-TruthyValue -Value $StartSchedulerFlag

Write-Step "Checking Docker"
$DockerCommand = Get-Command docker -ErrorAction SilentlyContinue
if (-not $DockerCommand) {
    Fail "Docker is not installed or not available in PATH."
}

$dockerInfo = Invoke-NativeCommand -Command @("docker", "info") -LogFile $StartupLog
if ($dockerInfo.ExitCode -ne 0) {
    Fail "Docker Desktop is not running or this shell cannot reach Docker. Open Docker Desktop and try again."
}
Write-Ok "Docker is installed and running"

Write-Step "Checking local ports"
if (Test-PortOpen -HostName "127.0.0.1" -Port $ApiPort) {
    $owner = Get-PortOwnerSummary -Port $ApiPort
    Fail "Port $ApiPort is already in use by $owner. Stop the existing FastAPI process or change API_PORT."
}
Write-Ok "Port $ApiPort is available"

if (Test-PortOpen -HostName "127.0.0.1" -Port $StreamlitPort) {
    $owner = Get-PortOwnerSummary -Port $StreamlitPort
    Fail "Port $StreamlitPort is already in use by $owner. Stop the existing Streamlit process or change STREAMLIT_PORT."
}
Write-Ok "Port $StreamlitPort is available"

if (Test-PortOpen -HostName "127.0.0.1" -Port $PostgresPort) {
    $owner = Get-PortOwnerSummary -Port $PostgresPort
    Write-Warn "Port $PostgresPort is already open by $owner. This is OK if it is the AVM Docker Postgres container; Docker Compose will verify it."
}

Invoke-Logged `
    -Description "Starting Postgres and Redis with Docker Compose" `
    -Command @("docker", "compose", "up", "-d", "postgres", "redis") `
    -LogFile $StartupLog

Wait-Postgres -TimeoutSeconds $PostgresTimeoutSeconds -PostgresUser $PostgresUser -PostgresDb $PostgresDb -LogFile $StartupLog

if (-not (Test-PortOpen -HostName "127.0.0.1" -Port $PostgresPort)) {
    Fail "Postgres is healthy in Docker but localhost:$PostgresPort is not reachable from Windows. Check POSTGRES_PORT and Docker port binding."
}
Write-Ok "Postgres responds on localhost:$PostgresPort"

Wait-Redis -TimeoutSeconds $RedisTimeoutSeconds -LogFile $StartupLog

Invoke-Logged `
    -Description "Running Alembic migrations" `
    -Command @($PythonExe, "-m", "alembic", "upgrade", "head") `
    -LogFile $StartupLog

Write-Step "Starting FastAPI and Streamlit in new PowerShell windows"
$ProjectRootLiteral = ConvertTo-SingleQuotedPowerShellLiteral -Value $ProjectRoot.Path
$PythonExeLiteral = ConvertTo-SingleQuotedPowerShellLiteral -Value (Resolve-Path $PythonExe).Path
$ApiLogLiteral = ConvertTo-SingleQuotedPowerShellLiteral -Value $ApiLog
$StreamlitLogLiteral = ConvertTo-SingleQuotedPowerShellLiteral -Value $StreamlitLog
$SchedulerLogLiteral = ConvertTo-SingleQuotedPowerShellLiteral -Value $SchedulerLog
$LocalApiBaseUrl = "http://127.0.0.1:$ApiPort"
$LocalApiBaseUrlLiteral = ConvertTo-SingleQuotedPowerShellLiteral -Value $LocalApiBaseUrl

$SchedulerEnvDefaults = [ordered]@{
    "SCHEDULER_ENABLE_DISCOVERY" = "false"
    "SCHEDULER_ENABLE_PORTAL" = "false"
    "SCHEDULER_STARTUP_CATCHUP_ENABLED" = "false"
    "SCHEDULER_STARTUP_REFRESH_ENABLED" = "true"
    "SCHEDULER_STARTUP_ALERTS_ENABLED" = "true"
    "SCHEDULER_STARTUP_MIN_STALE_HOURS" = "24"
    "SCHEDULER_DISCOVERY_CRON" = "0 10 * * *"
    "SCHEDULER_REFRESH_CRON" = "0 12 * * mon,wed,fri"
    "SCHEDULER_ALERTS_CRON" = "0 13 * * *"
    "SCHEDULER_REFRESH_LIMIT" = "5"
    "SCHEDULER_REFRESH_STALE_DAYS" = "30"
    "SCHEDULER_REFRESH_COOLDOWN_HOURS" = "24"
    "SCHEDULER_ALERTS_THRESHOLD_PCT" = "5.0"
    "SCHEDULER_ALERTS_LOOKBACK_DAYS" = "30"
    "PORTFOLIO_SNAPSHOTS_ENABLED" = "false"
    "PORTFOLIO_SNAPSHOTS_CRON" = "0 14 * * *"
    "PORTFOLIO_SNAPSHOTS_LIMIT_USERS" = "10"
    "PORTFOLIO_SNAPSHOTS_LIMIT_ITEMS_PER_USER" = "20"
    "PORTFOLIO_SNAPSHOTS_MIN_INTERVAL_HOURS" = "20"
    "PORTFOLIO_SNAPSHOTS_DRY_RUN" = "false"
    "PORTFOLIO_SNAPSHOTS_USER_ID" = ""
    "PORTFOLIO_SNAPSHOTS_STARTUP_CATCHUP_ENABLED" = "false"
}
$SchedulerEnvAssignments = foreach ($name in $SchedulerEnvDefaults.Keys) {
    $value = Get-EnvironmentOrDotEnvValue -Name $name -DefaultValue $SchedulerEnvDefaults[$name]
    $literal = ConvertTo-SingleQuotedPowerShellLiteral -Value $value
    "`$env:$name = $literal"
}
$SchedulerEnvBlock = $SchedulerEnvAssignments -join [Environment]::NewLine

$ApiRunnerContent = @"
`$ErrorActionPreference = "Continue"
`$Host.UI.RawUI.WindowTitle = "AVM API"
Set-Location -LiteralPath $ProjectRootLiteral
Write-Host "AVM API starting on http://127.0.0.1:$ApiPort"
Write-Host "Log file: $ApiLogLiteral"
Write-Host ""
& $PythonExeLiteral -m uvicorn api.main:app --reload --host 127.0.0.1 --port $ApiPort *> $ApiLogLiteral
if (`$LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "AVM API exited with code `$LASTEXITCODE. See log file above." -ForegroundColor Red
}
"@

$StreamlitRunnerContent = @"
`$ErrorActionPreference = "Continue"
`$Host.UI.RawUI.WindowTitle = "AVM Streamlit"
Set-Location -LiteralPath $ProjectRootLiteral
`$env:AVM_API_BASE_URL = $LocalApiBaseUrlLiteral
Write-Host "AVM Streamlit starting on http://localhost:$StreamlitPort"
Write-Host "AVM_API_BASE_URL=$LocalApiBaseUrl"
Write-Host "Log file: $StreamlitLogLiteral"
Write-Host ""
& $PythonExeLiteral -m streamlit run ui/app.py --server.port $StreamlitPort *> $StreamlitLogLiteral
if (`$LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "AVM Streamlit exited with code `$LASTEXITCODE. See log file above." -ForegroundColor Red
}
"@

$SchedulerRunnerContent = @"
`$ErrorActionPreference = "Continue"
`$Host.UI.RawUI.WindowTitle = "AVM Scheduler"
Set-Location -LiteralPath $ProjectRootLiteral
$SchedulerEnvBlock
Write-Host "AVM Scheduler starting"
Write-Host "Log file: $SchedulerLogLiteral"
Write-Host "Refresh limit: `$env:SCHEDULER_REFRESH_LIMIT"
Write-Host "Refresh cron:  `$env:SCHEDULER_REFRESH_CRON"
Write-Host "Alerts cron:   `$env:SCHEDULER_ALERTS_CRON"
Write-Host "Portfolio snapshots: `$env:PORTFOLIO_SNAPSHOTS_ENABLED"
Write-Host "Portfolio cron:      `$env:PORTFOLIO_SNAPSHOTS_CRON"
Write-Host "Catch-up:      `$env:SCHEDULER_STARTUP_CATCHUP_ENABLED"
Write-Host "Discovery:     `$env:SCHEDULER_ENABLE_DISCOVERY"
Write-Host "Portal:        `$env:SCHEDULER_ENABLE_PORTAL"
Write-Host ""
& $PythonExeLiteral -m workers.scheduler *> $SchedulerLogLiteral
if (`$LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "AVM Scheduler exited with code `$LASTEXITCODE. See log file above." -ForegroundColor Red
}
"@

Set-Content -Path $ApiRunner -Value $ApiRunnerContent -Encoding UTF8
Set-Content -Path $StreamlitRunner -Value $StreamlitRunnerContent -Encoding UTF8
Set-Content -Path $SchedulerRunner -Value $SchedulerRunnerContent -Encoding UTF8

$ApiRunnerArg = "-NoExit -ExecutionPolicy Bypass -File `"$ApiRunner`""
$StreamlitRunnerArg = "-NoExit -ExecutionPolicy Bypass -File `"$StreamlitRunner`""
$SchedulerRunnerArg = "-ExecutionPolicy Bypass -File `"$SchedulerRunner`""

Start-Process powershell.exe -WorkingDirectory $ProjectRoot -ArgumentList $ApiRunnerArg

Wait-HttpEndpoint `
    -Name "FastAPI" `
    -Url "http://127.0.0.1:$ApiPort/health" `
    -TimeoutSeconds 60 `
    -LogFile $ApiLog

Start-Process powershell.exe -WorkingDirectory $ProjectRoot -ArgumentList $StreamlitRunnerArg

if ($StartScheduler) {
    Write-Step "Starting optional scheduler"
    $SchedulerProcess = Start-Process `
        powershell.exe `
        -WorkingDirectory $ProjectRoot `
        -WindowStyle Hidden `
        -ArgumentList $SchedulerRunnerArg `
        -PassThru
    Set-Content -Path $SchedulerPidFile -Value $SchedulerProcess.Id
    Start-Sleep -Seconds 2

    $SchedulerStillRunning = Get-Process -Id $SchedulerProcess.Id -ErrorAction SilentlyContinue
    if (-not $SchedulerStillRunning -or $SchedulerProcess.HasExited) {
        Write-Host ""
        Write-Host "Last Scheduler log lines:" -ForegroundColor Yellow
        if (Test-Path $SchedulerLog) {
            Get-Content -Path $SchedulerLog -Tail 80
        }
        else {
            Write-Host "Log file not found: $SchedulerLog" -ForegroundColor Yellow
        }
        Fail "Scheduler did not stay alive. See log: $SchedulerLog"
    }

    Write-Ok "Scheduler started. PID: $($SchedulerProcess.Id)"
    Write-Ok "Scheduler log: $SchedulerLog"
    Write-Ok "Scheduler PID file: $SchedulerPidFile"
}
else {
    Write-Ok "Scheduler disabled. Set AVM_START_SCHEDULER=true to start it with local startup."
}

Write-Host ""
Write-Host "AVM-v2 is starting." -ForegroundColor Green
Write-Host "FastAPI docs: http://127.0.0.1:$ApiPort/docs"
Write-Host "Streamlit:     http://localhost:$StreamlitPort"
if ($StartScheduler) {
    Write-Host "Scheduler:     PID $($SchedulerProcess.Id)"
}
else {
    Write-Host "Scheduler:     disabled"
}
Write-Host ""
Write-Host "Logs:"
Write-Host "  Startup:   $StartupLog"
Write-Host "  FastAPI:   $ApiLog"
Write-Host "  Streamlit: $StreamlitLog"
if ($StartScheduler) {
    Write-Host "  Scheduler: $SchedulerLog"
    Write-Host ""
    Write-Host "Stop scheduler: Stop-Process -Id $($SchedulerProcess.Id)"
}
