# Окно для записи демонстрации. Запускается Claude; заголовок окна нужен, чтобы ffmpeg записывал только его.
$host.UI.RawUI.WindowTitle = 'Strateg-demo'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
function prompt { 'strateg> ' }   # короткое приглашение: в записи не видно локальных путей
Clear-Host
Write-Host ''
Write-Host '  Стратег: запись демонстрации' -ForegroundColor Cyan
Write-Host '  Окно записывается. Не сворачивайте его и не меняйте размер.' -ForegroundColor DarkGray
Write-Host ''
Write-Host '  Команда запуска агента:' -ForegroundColor DarkGray
Write-Host '  claude --setting-sources project,local --strict-mcp-config --model opus'
Write-Host ''
