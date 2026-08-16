$base = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $base '.workbench.pid'
$port = 8899

# 1) 按端口停止实际监听进程
$listeners = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
foreach ($c in $listeners) {
    if ($c.OwningProcess -gt 0) { Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue }
}

# 2) pid 文件中的启动器进程兜底（避免遗留）
if (Test-Path $pidFile) {
    $id = (Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    if ($id -match '^[0-9]+$') { Stop-Process -Id ([int]$id) -Force -ErrorAction SilentlyContinue }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}
