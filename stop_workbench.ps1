$base = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $base '.workbench.pid'
if (Test-Path $pidFile) {
    $id = (Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    if ($id -match '^[0-9]+$') { Stop-Process -Id ([int]$id) -Force -ErrorAction SilentlyContinue }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}
