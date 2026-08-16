$ErrorActionPreference = 'Stop'
$base = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python314\python.exe'
if (-not (Test-Path $python)) { $python = (Get-Command python -ErrorAction SilentlyContinue).Source }
$pythonw = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python314\pythonw.exe'
if (-not (Test-Path $pythonw)) { $pythonw = (Get-Command pythonw -ErrorAction SilentlyContinue).Source }
$proxy = Join-Path $base 'ams_proxy.py'
$logDir = Join-Path $base 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir ('auto_update_' + (Get-Date -Format 'yyyyMMdd') + '.log')

function Log([string]$msg) { Add-Content -LiteralPath $log -Value ("[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg) -Encoding UTF8 }
function ServiceReady {
    try { return (Invoke-WebRequest -Uri 'http://127.0.0.1:8899/api/status' -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200 } catch { return $false }
}

try {
    Set-Location $base
    $env:PYTHONIOENCODING = 'utf-8'
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    if (-not (Test-Path $python)) { throw 'Python not found' }
    if (-not (ServiceReady)) {
        Log 'Starting local service.'
        Start-Process -FilePath $pythonw -ArgumentList @($proxy) -WorkingDirectory $base -WindowStyle Hidden | Out-Null
        $ready = $false
        for ($i = 0; $i -lt 30; $i++) {
            Start-Sleep -Seconds 1
            if (ServiceReady) { $ready = $true; break }
        }
        if (-not $ready) { throw 'Local service start timeout' }
    }

    $task = $args[0]
    $maxAttempts = 3
    $exitCode = 1
    for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
        if ($task -eq 'residents') {
            $date = Get-Date -Format 'yyyy-MM-dd'
            Log ('Residents update {0}, attempt {1}/{2}' -f $date, $attempt, $maxAttempts)
            & $python (Join-Path $base 'fetch_daily_residents.py') $date 2>&1 | ForEach-Object { Log (('' + $_).TrimEnd()) }
        } elseif ($task -eq 'income') {
            $today = Get-Date
            $start = $today.AddDays(-1).ToString('yyyy-MM-dd')
            $end = $today.ToString('yyyy-MM-dd')
            Log ('Income update {0} ~ {1}, attempt {2}/{3}' -f $start, $end, $attempt, $maxAttempts)
            & $python (Join-Path $base 'fetch_income_flow_range.py') $start $end 2>&1 | ForEach-Object { Log (('' + $_).TrimEnd()) }
        } elseif ($task -eq 'board') {
            Log ('AMS board update, attempt {0}/{1}' -f $attempt, $maxAttempts)
            & $python (Join-Path $base 'update_ams_board.py') 2>&1 | ForEach-Object { Log (('' + $_).TrimEnd()) }
        } else {
            throw ('Unknown task type: ' + $task)
        }
        $exitCode = $LASTEXITCODE
        if ($exitCode -eq 0) { Log ('Task succeeded on attempt {0}' -f $attempt); break }
        Log ('Task failed with exit code {0}' -f $exitCode)
        if ($attempt -lt $maxAttempts) { Log 'Retrying in 10 minutes'; Start-Sleep -Seconds 600 }
    }
    if ($exitCode -ne 0) { Log ('Failed after {0} attempts; existing data preserved' -f $maxAttempts); exit $exitCode }
} catch {
    Log ('Task failed: ' + $_.Exception.Message)
    exit 1
}


