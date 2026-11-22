#!/bin/sh
# Неинтерактивный заход агента: sh runs/run.sh <метка> <модель> "<запрос>"
# Запускать из корня репозитория (на Windows — в Git Bash).
#
# Разрешения передаются флагами, поэтому диалог доверия к папке не нужен.
# Личные настройки и MCP-серверы пользователя не подключаются: расход контекста меньше, результат воспроизводимее.
# Сырой ответ сохраняется в runs/raw/ (не попадает в git), обезличенная сводка — в runs/<метка>.json,
# точная стоимость захода записывается в активный проект.
label="$1"; model="$2"; prompt="$3"
py=python; command -v python >/dev/null 2>&1 || py=python3
mkdir -p runs/raw
start=$(date +%s)
claude -p "$prompt" --model "$model" \
  --setting-sources project,local --strict-mcp-config \
  --permission-mode acceptEdits \
  --allowedTools "Bash(python tools/strateg.py *)" "Bash(python3 tools/strateg.py *)" \
    "Bash(python projects/*/analysis/*.py)" "Bash(python3 projects/*/analysis/*.py)" \
    "PowerShell(python tools/strateg.py *)" "PowerShell(python projects/*/analysis/*.py)" \
    "WebSearch" "WebFetch" \
  --output-format json > "runs/raw/$label.json" 2> "runs/raw/$label.err"
code=$?
end=$(date +%s)
echo "$label: код $code, $((end-start)) c" | tee -a runs/timing.txt
if [ "$code" -ne 0 ]; then
  echo "ОШИБКА: claude завершился с кодом $code, см. runs/raw/$label.err" >&2
  exit "$code"
fi
"$py" runs/summarize.py "$label" || exit 1
"$py" tools/strateg.py cost import "runs/raw/$label.json" --label "$label" || exit 1
