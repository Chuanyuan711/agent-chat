$ErrorActionPreference = 'Stop'
$path = 'C:\Users\sthn\agent-chat\pumpkin_notifications.jsonl'
if (-not (Test-Path $path)) {
    Write-Output 'NOFILE'
    exit 0
}
$content = Get-Content -Raw -Path $path
if ($content -eq $null -or $content.Trim().Length -eq 0) {
    Write-Output 'EMPTY'
    exit 0
}
Write-Output $content.Trim()
