# Остановка записи демонстрации, начатой docs/video/start.ps1.
# Запись идёт в контейнер Matroska: он остаётся читаемым, даже если процесс завершён принудительно.
param([string]$Repo = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)))
$info = Get-Content (Join-Path $Repo 'docs\video\raw\zapis.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$proc = Get-Process -Id $info.pid -ErrorAction SilentlyContinue
if ($proc) { Stop-Process -Id $info.pid -Force; Start-Sleep -Seconds 2 }
$size = [math]::Round((Get-Item $info.file).Length / 1MB, 1)
$duration = & ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 $info.file
"Запись остановлена: $($info.file), $size МБ, длительность $duration с, начало $($info.start)"
