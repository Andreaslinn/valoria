param(
  [switch]$NoFrontend,
  [switch]$NoBackend,
  [switch]$WithStreamlit,
  [switch]$NoBrowser,
  [switch]$SkipInstall,
  [switch]$DryRun,
  [int]$PostgresTimeoutSeconds = 60,
  [int]$RedisTimeoutSeconds = 30,
  [int]$BackendTimeoutSeconds = 60,
  [int]$FrontendTimeoutSeconds = 90
)

$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$LogDir = Join-Path $Root "logs\startup"
$StartupLog = Join-Path $LogDir "valoria-startup-$Timestamp.log"

function Write-Line {
  param([string]$Message)
  Write-Host $Message
  if (Test-Path $LogDir) {
    Add-Content -Path $StartupLog -Value $Message
  }
}

function Write-Step { param([string]$Message) Write-Line ""; Write-Line "== $Message" }
function Write-Ok { param([string]$Message) Write-Line "[OK] $Message" }
function Write-Warn { param([string]$Message) Write-Line "[WARN] $Message" }
function Write-Fail { param([string]$Message) Write-Line "[FAIL] $Message" }

function Invoke-Checked {
  param(
    [string]$FilePath,
    [string[]]$ArgumentList,
    [string]$WorkingDirectory,
    [string]$Description
  )

  $display = "$FilePath $($ArgumentList -join ' ')"
  if ($Description) {
    Write-Line $Description
  }

  if ($DryRun) {
    Write-Line "[DRYRUN] $display"
    return
  }

  $previousLocation = Get-Location
  try {
    Set-Location $WorkingDirectory
    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
      throw "Command failed with exit code $LASTEXITCODE`: $display"
    }
  } finally {
    Set-Location $previousLocation
  }
}

function Test-PortOpen {
  param([int]$Port)
  $client = New-Object System.Net.Sockets.TcpClient
  try {
    $async = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
    if (-not $async.AsyncWaitHandle.WaitOne(500, $false)) {
      return $false
    }
    $client.EndConnect($async)
    return $true
  } catch {
    return $false
  } finally {
    $client.Close()
  }
}

function ConvertTo-SingleQuotedPowerShellLiteral {
  param([string]$Value)
  return "'" + ($Value -replace "'", "''") + "'"
}

function ConvertTo-CmdQuoted {
  param([string]$Value)
  return '"' + ($Value -replace '"', '""') + '"'
}

function Get-PortOwnerSummary {
  param([int]$Port)
  $lines = netstat -ano -p tcp | Select-String ":$Port\s"
  if (-not $lines) {
    return "no TCP owner found"
  }

  $pids = @()
  foreach ($line in $lines) {
    $parts = ($line.ToString() -split "\s+") | Where-Object { $_ }
    if ($parts.Count -ge 5) {
      $pids += $parts[$parts.Count - 1]
    }
  }

  $pids = $pids | Sort-Object -Unique
  $summaries = @()
  foreach ($ownerPid in $pids) {
    try {
      $proc = Get-Process -Id ([int]$ownerPid) -ErrorAction Stop
      $summaries += "$($proc.ProcessName) PID $ownerPid"
    } catch {
      $summaries += "PID $ownerPid"
    }
  }

  if ($summaries.Count -eq 0) {
    return "owner unknown"
  }
  return ($summaries -join ", ")
}

function Invoke-HttpGet {
  param([string]$Uri)
  try {
    return Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec 3
  } catch {
    return $null
  }
}

function Test-HttpOk {
  param([string]$Uri)
  $response = Invoke-HttpGet -Uri $Uri
  return ($response -and [int]$response.StatusCode -ge 200 -and [int]$response.StatusCode -lt 500)
}

function Test-FrontendLooksLikeNext {
  param([string]$Uri)
  $response = Invoke-HttpGet -Uri $Uri
  if (-not $response) {
    return $false
  }
  $content = [string]$response.Content
  $headers = [string]($response.Headers | Out-String)
  return ($content -match "_next|__next|Next.js" -or $headers -match "x-nextjs|next")
}

function Wait-HttpOk {
  param(
    [string]$Uri,
    [int]$TimeoutSeconds,
    [string]$Name
  )

  if ($DryRun) {
    Write-Line "[DRYRUN] Wait up to $TimeoutSeconds seconds for $Name at $Uri"
    return $true
  }

  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  while ((Get-Date) -lt $deadline) {
    if (Test-HttpOk -Uri $Uri) {
      Write-Ok "$Name is responding at $Uri"
      return $true
    }
    Start-Sleep -Seconds 2
  }

  Write-Warn "$Name did not respond at $Uri within $TimeoutSeconds seconds"
  return $false
}

function Read-DotEnvValue {
  param(
    [string]$Name,
    [string]$Default
  )

  $envPath = Join-Path $Root ".env"
  if (-not (Test-Path $envPath)) {
    return $Default
  }

  $line = Get-Content $envPath | Where-Object { $_ -match "^\s*$([regex]::Escape($Name))\s*=" } | Select-Object -First 1
  if (-not $line) {
    return $Default
  }

  $value = ($line -split "=", 2)[1].Trim()
  $value = $value.Trim("'").Trim('"')
  if ([string]::IsNullOrWhiteSpace($value)) {
    return $Default
  }
  return $value
}

function Assert-RequiredPath {
  param([string]$RelativePath)
  $path = Join-Path $Root $RelativePath
  if (-not (Test-Path $path)) {
    throw "Required path not found: $RelativePath"
  }
}

function Write-RunnerScript {
  param(
    [string]$Name,
    [string[]]$Lines
  )

  $runnerPath = Join-Path $LogDir "$Name-$Timestamp.ps1"
  if ($DryRun) {
    Write-Line "[DRYRUN] Would write runner script $runnerPath"
    return $runnerPath
  }
  Set-Content -Path $runnerPath -Value $Lines -Encoding ASCII
  return $runnerPath
}

function Start-RunnerWindow {
  param(
    [string]$Title,
    [string]$RunnerPath
  )

  if ($DryRun) {
    Write-Line "[DRYRUN] Would open PowerShell window: $Title"
    return
  }

  Start-Process -FilePath "powershell.exe" -ArgumentList @(
    "-NoExit",
    "-ExecutionPolicy", "Bypass",
    "-File", "`"$RunnerPath`""
  )
}

function Ensure-FrontendEnvLocal {
  $frontendEnv = Join-Path $Root "frontend\.env.local"
  if (Test-Path $frontendEnv) {
    Write-Ok "frontend\.env.local already exists; leaving it unchanged"
    return
  }

  if ($DryRun) {
    Write-Line "[DRYRUN] Would create frontend\.env.local with NEXT_PUBLIC_API_BASE_URL=http://localhost:8000"
    return
  }

  Set-Content -Path $frontendEnv -Value "NEXT_PUBLIC_API_BASE_URL=http://localhost:8000" -Encoding ASCII
  Write-Ok "Created frontend\.env.local"
}

function Start-Backend {
  Write-Step "Backend FastAPI"

  if (Test-PortOpen -Port 8000) {
    if ((Test-HttpOk -Uri "http://127.0.0.1:8000/health") -and (Test-HttpOk -Uri "http://127.0.0.1:8000/api/v1/health")) {
      Write-Ok "Backend already running and healthy on 127.0.0.1:8000"
      return
    }
    Write-Fail "Port 8000 is occupied by $(Get-PortOwnerSummary -Port 8000), but backend health did not pass. Not killing it."
    throw "Port 8000 occupied by non-healthy service"
  }

  $python = Join-Path $Root ".venv-win\Scripts\python.exe"
  if (-not (Test-Path $python)) {
    throw "Python virtualenv not found at .venv-win\Scripts\python.exe"
  }

  $apiLog = Join-Path $LogDir "valoria-api-$Timestamp.log"
  $rootLiteral = ConvertTo-SingleQuotedPowerShellLiteral -Value $Root
  $apiLogLiteral = ConvertTo-SingleQuotedPowerShellLiteral -Value $apiLog
  $pythonCmd = ConvertTo-CmdQuoted -Value $python
  $apiLogCmd = ConvertTo-CmdQuoted -Value $apiLog
  $uvicornCmdLine = "$pythonCmd -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload 1>> $apiLogCmd 2>>&1"
  $uvicornCmdLineLiteral = ConvertTo-SingleQuotedPowerShellLiteral -Value $uvicornCmdLine
  $runner = Write-RunnerScript -Name "valoria-api-runner" -Lines @(
    "`$ErrorActionPreference = 'Stop'",
    "Set-Location $rootLiteral",
    "Write-Host 'Starting Valoria FastAPI on http://127.0.0.1:8000'",
    "Write-Host 'Log: $apiLog'",
    "Add-Content -Path $apiLogLiteral -Value ('--- Valoria FastAPI starting at ' + (Get-Date -Format o) + ' ---')",
    "`$cmdLine = $uvicornCmdLineLiteral",
    "& cmd.exe /d /s /c `$cmdLine",
    "`$exitCode = `$LASTEXITCODE",
    "if (`$exitCode -ne 0) {",
    "  Add-Content -Path $apiLogLiteral -Value ('FastAPI exited with code ' + `$exitCode + ' at ' + (Get-Date -Format o))",
    "  Write-Host ('FastAPI exited with code ' + `$exitCode + '. See log: $apiLog') -ForegroundColor Red",
    "  exit `$exitCode",
    "}",
    "Add-Content -Path $apiLogLiteral -Value ('FastAPI exited normally at ' + (Get-Date -Format o))"
  )
  Start-RunnerWindow -Title "Valoria API" -RunnerPath $runner
  [void](Wait-HttpOk -Uri "http://127.0.0.1:8000/health" -TimeoutSeconds $BackendTimeoutSeconds -Name "Backend /health")
  [void](Wait-HttpOk -Uri "http://127.0.0.1:8000/api/v1/health" -TimeoutSeconds 10 -Name "Backend /api/v1/health")
}

function Start-Frontend {
  Write-Step "Frontend Next.js"
  Ensure-FrontendEnvLocal

  $frontendRoot = Join-Path $Root "frontend"
  $nodeModules = Join-Path $frontendRoot "node_modules"
  if (-not (Test-Path $nodeModules)) {
    if ($SkipInstall) {
      Write-Warn "frontend\node_modules is missing and -SkipInstall was provided"
    } else {
      Invoke-Checked -FilePath "npm.cmd" -ArgumentList @("install") -WorkingDirectory $frontendRoot -Description "Installing frontend dependencies"
    }
  } else {
    Write-Ok "frontend\node_modules exists"
  }

  if (Test-PortOpen -Port 3000) {
    if (Test-FrontendLooksLikeNext -Uri "http://127.0.0.1:3000") {
      Write-Ok "Frontend already running and looks like Next.js on 127.0.0.1:3000"
      return
    }
    Write-Fail "Port 3000 is occupied by $(Get-PortOwnerSummary -Port 3000), but it does not look like Next.js. Not killing it."
    throw "Port 3000 occupied by non-Next service"
  }

  $frontendLog = Join-Path $LogDir "valoria-frontend-$Timestamp.log"
  $runner = Write-RunnerScript -Name "valoria-frontend-runner" -Lines @(
    "`$ErrorActionPreference = 'Stop'",
    "Set-Location '$frontendRoot'",
    "Write-Host 'Starting Valoria Next.js on http://127.0.0.1:3000'",
    "Write-Host 'Log: $frontendLog'",
    "& npm.cmd run dev -- -H 127.0.0.1 -p 3000 *> '$frontendLog'"
  )
  Start-RunnerWindow -Title "Valoria Frontend" -RunnerPath $runner
  [void](Wait-HttpOk -Uri "http://127.0.0.1:3000" -TimeoutSeconds $FrontendTimeoutSeconds -Name "Frontend")
}

function Start-Streamlit {
  Write-Step "Optional Streamlit legacy UI"
  if (Test-PortOpen -Port 8501) {
    Write-Warn "Port 8501 is already occupied by $(Get-PortOwnerSummary -Port 8501). Not killing it."
    return
  }

  $python = Join-Path $Root ".venv-win\Scripts\python.exe"
  $streamlitApp = Join-Path $Root "ui\app.py"
  if (-not (Test-Path $python)) {
    throw "Python virtualenv not found at .venv-win\Scripts\python.exe"
  }
  if (-not (Test-Path $streamlitApp)) {
    throw "Streamlit app not found at ui\app.py"
  }

  $streamlitLog = Join-Path $LogDir "valoria-streamlit-$Timestamp.log"
  $runner = Write-RunnerScript -Name "valoria-streamlit-runner" -Lines @(
    "`$ErrorActionPreference = 'Stop'",
    "Set-Location '$Root'",
    "Write-Host 'Starting legacy Streamlit on http://127.0.0.1:8501'",
    "Write-Host 'Log: $streamlitLog'",
    "& '$python' -m streamlit run '$streamlitApp' --server.port 8501 *> '$streamlitLog'"
  )
  Start-RunnerWindow -Title "Valoria Streamlit" -RunnerPath $runner
}

try {
  if (-not (Test-Path $LogDir)) {
    if ($DryRun) {
      Write-Host "[DRYRUN] Would create $LogDir"
    } else {
      New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
    }
  }

  Write-Line "Valoria local startup"
  Write-Line "Root: $Root"
  Write-Line "DryRun: $DryRun"

  Write-Step "Preflight"
  Assert-RequiredPath "docker-compose.yml"
  Assert-RequiredPath "api\main.py"
  Assert-RequiredPath "frontend\package.json"
  Write-Ok "Required project files found"
  Write-Warn "This launcher does not run scraper, refresh jobs, scheduler, migrations, deploys, or engine changes."

  if (-not $NoBackend) {
    Write-Step "Docker dependencies"
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
      throw "Docker CLI not found in PATH"
    }
    Invoke-Checked -FilePath "docker" -ArgumentList @("info") -WorkingDirectory $Root -Description "Checking Docker daemon"
    Invoke-Checked -FilePath "docker" -ArgumentList @("compose", "up", "-d", "postgres", "redis") -WorkingDirectory $Root -Description "Starting Docker services: postgres redis"

    $postgresUser = Read-DotEnvValue -Name "POSTGRES_USER" -Default "avm"
    $postgresDb = Read-DotEnvValue -Name "POSTGRES_DB" -Default "avm"
    if ($DryRun) {
      Write-Line "[DRYRUN] Would wait up to $PostgresTimeoutSeconds seconds for Postgres pg_isready"
      Write-Line "[DRYRUN] Would wait up to $RedisTimeoutSeconds seconds for Redis ping"
    } else {
      $pgDeadline = (Get-Date).AddSeconds($PostgresTimeoutSeconds)
      do {
        docker compose exec -T postgres pg_isready -U $postgresUser -d $postgresDb | Out-Null
        if ($LASTEXITCODE -eq 0) { Write-Ok "Postgres is ready"; break }
        Start-Sleep -Seconds 2
      } while ((Get-Date) -lt $pgDeadline)
      if ($LASTEXITCODE -ne 0) { throw "Postgres did not become ready" }

      $redisDeadline = (Get-Date).AddSeconds($RedisTimeoutSeconds)
      do {
        $redisPing = docker compose exec -T redis redis-cli ping 2>$null
        if ($redisPing -match "PONG") { Write-Ok "Redis is ready"; break }
        Start-Sleep -Seconds 2
      } while ((Get-Date) -lt $redisDeadline)
      if ($redisPing -notmatch "PONG") { throw "Redis did not become ready" }
    }

    Start-Backend
  } else {
    Write-Warn "Skipping backend because -NoBackend was provided"
  }

  if (-not $NoFrontend) {
    Start-Frontend
  } else {
    Write-Warn "Skipping frontend because -NoFrontend was provided"
  }

  if ($WithStreamlit) {
    Start-Streamlit
  }

  Write-Step "URLs"
  Write-Line "Backend health:  http://127.0.0.1:8000/health"
  Write-Line "API health:      http://127.0.0.1:8000/api/v1/health"
  Write-Line "Frontend:        http://127.0.0.1:3000"
  if ($WithStreamlit) {
    Write-Line "Streamlit:       http://127.0.0.1:8501"
  }

  if (-not $NoBrowser -and -not $NoFrontend -and -not $DryRun) {
    Start-Process "http://127.0.0.1:3000"
  } elseif ($NoBrowser) {
    Write-Ok "Browser auto-open skipped by -NoBrowser"
  }

  Write-Ok "Valoria local startup finished"
} catch {
  Write-Fail $_.Exception.Message
  exit 1
}
