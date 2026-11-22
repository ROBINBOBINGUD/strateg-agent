# Подготовка записи демонстрации (запускает Claude, не человек).
# 1) делает чистую копию репозитория — как у жюри после git clone;
# 2) открывает в ней окно терминала с заголовком Strateg-demo;
# 3) включает запись только этого окна через ffmpeg (gfxcapture).
# Остановка записи: docs/video/stop.ps1
param(
    [string]$Repo = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$Demo = (Join-Path (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))) 'strateg-demo')
)
$ErrorActionPreference = 'Stop'
$raw = Join-Path $Repo 'docs\video\raw'
New-Item -ItemType Directory -Force $raw | Out-Null
if (Test-Path $Demo) { throw "Папка $Demo уже есть: удалите её или укажите другую" }
git clone --quiet $Repo $Demo
Start-Process powershell -ArgumentList "-NoExit -ExecutionPolicy Bypass -File `"$Demo\docs\video\okno.ps1`""
Start-Sleep -Seconds 4
$stamp = Get-Date
$file = Join-Path $raw ("zapis-" + $stamp.ToString('HHmmss') + ".mkv")
$filter = "gfxcapture=window_title='(?i)strateg-demo':max_framerate=8"
$ffArgs = "-hide_banner -loglevel error -y -f lavfi -i `"$filter`" -vf `"hwdownload,format=bgra,scale=1920:-2:flags=lanczos,format=yuv420p`" -c:v libx264 -preset veryfast -crf 23 -g 40 -t 7200 `"$file`""
$proc = Start-Process ffmpeg -ArgumentList $ffArgs -WindowStyle Hidden -PassThru
Start-Sleep -Seconds 3
if ($proc.HasExited) { throw "ffmpeg не начал запись (код $($proc.ExitCode))" }
@{ pid = $proc.Id; file = $file; start = $stamp.ToString('o'); demo = $Demo } | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $raw 'zapis.json')
"Запись идёт: $file (ffmpeg PID $($proc.Id)), окно Strateg-demo, копия репозитория: $Demo"
