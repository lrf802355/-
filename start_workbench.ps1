$ErrorActionPreference = 'Stop'
$base = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python314\pythonw.exe'
$script = Join-Path $base 'ams_proxy.py'
$pidFile = Join-Path $base '.workbench.pid'
$url = 'http://localhost:8899/'

function Test-Workbench {
    try {
        $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8899/api/status' -UseBasicParsing -TimeoutSec 1
        return $r.StatusCode -eq 200
    } catch { return $false }
}

Set-Location $base
if (-not (Test-Path $python)) {
    [System.Windows.Forms.MessageBox]::Show('没有找到 Python，请先安装 Python。', '工作台启动失败', 'OK', 'Error') | Out-Null
    exit 1
}

if (-not (Test-Workbench)) {
    $p = Start-Process -FilePath $python -ArgumentList @($script) -WorkingDirectory $base -WindowStyle Hidden -PassThru
    Set-Content -LiteralPath $pidFile -Value $p.Id -Encoding ASCII
    $ready = $false
    1..20 | ForEach-Object {
        Start-Sleep -Milliseconds 500
        if (Test-Workbench) { $ready = $true; return }
    }
    if (-not $ready) {
        [System.Windows.Forms.MessageBox]::Show('工作台服务启动超时，请检查工作台目录中的日志或重新启动。', '工作台启动失败', 'OK', 'Error') | Out-Null
        exit 1
    }
}

# 明确调用 Edge，避免隐藏启动时默认浏览器关联失效
$edgePaths = @(
    "$env:ProgramFiles(x86)\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
    "$env:LOCALAPPDATA\Microsoft\Edge\Application\msedge.exe"
)
$edge = $edgePaths | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($edge) {
    Start-Process -FilePath $edge -ArgumentList @('--new-window', $url)
} else {
    Start-Process -FilePath "$env:WINDIR\explorer.exe" -ArgumentList $url
}
