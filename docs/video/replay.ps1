# Окно для записи воспроизведения сеансов агента. Запускается Claude; ffmpeg записывает только это окно.
$host.UI.RawUI.WindowTitle = 'Strateg-demo'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = 'utf-8'
Set-Location (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
function prompt { 'strateg> ' }
Clear-Host
Start-Sleep -Seconds 6
python docs/video/replay.py --minutes 8.3
