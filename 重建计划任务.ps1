# 重建工作台定时任务（2026-08-16 更新版）
# 用法：右键此文件 → “使用 PowerShell 运行”（或管理员 PowerShell 中执行）
$ErrorActionPreference = 'Stop'
$base = Split-Path -Parent $MyInvocation.MyCommand.Path
$auto = Join-Path $base '自动更新.ps1'
$arg = '-NoProfile -ExecutionPolicy Bypass -File "' + $auto + '" '

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 2) -MultipleInstances IgnoreNew

# 1. 在住快照：每天 7:00
Register-ScheduledTask -TaskName 'WorkBench Residents Auto Update' -Action (New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ($arg + 'residents')) -Trigger (New-ScheduledTaskTrigger -Daily -At '07:00') -Settings $settings -Description '每日 7:00 抓取在住快照' -Force | Out-Null

# 2. 收入流水：每天 3 次（单任务多触发器）
$incomeTriggers = @(
    New-ScheduledTaskTrigger -Daily -At '08:00'
    New-ScheduledTaskTrigger -Daily -At '14:00'
    New-ScheduledTaskTrigger -Daily -At '23:30'
)
Register-ScheduledTask -TaskName 'WorkBench Income Update' -Action (New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ($arg + 'income')) -Trigger $incomeTriggers -Settings $settings -Description '每日 3 次增量拉取收入流水' -Force | Out-Null

# 3. AMS 看板：每月 1 日 8:30（本机 PowerShell 不支持 -Monthly 触发器，用命令行创建）
schtasks /Create /TN "WorkBench Board Monthly Update" /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$auto`" board" /SC MONTHLY /D 1 /ST 08:30 /F | Out-Null
try {
    $t = Get-ScheduledTask -TaskName 'WorkBench Board Monthly Update'
    if ($t) { $t.Settings.StartWhenAvailable = $true; Set-ScheduledTask -InputObject $t | Out-Null }
} catch { Write-Host '提示：每月任务的补跑选项未能自动开启，可在任务计划程序中手动勾选。' }

# 清理旧版本的单独收入任务名（如果存在）
foreach ($old in @('WorkBench Income Update 08AM', 'WorkBench Income Update 02PM', 'WorkBench Income Update 1130PM')) {
    schtasks /Delete /TN $old /F 2>$null | Out-Null
}

Write-Host ''
Write-Host '全部完成。可在“任务计划程序”中查看，或执行: schtasks /query /fo LIST /v | findstr WorkBench'
