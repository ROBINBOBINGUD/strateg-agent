#!/bin/sh
# Неинтерактивный заход агента: runs/run.sh <метка> <модель> "<запрос>"
# Разрешения передаются флагами, поэтому диалог доверия к папке не нужен.
# Личные настройки и MCP-серверы пользователя не подключаются: расход контекста меньше, результат воспроизводимее.
label="$1"; model="$2"; prompt="$3"
start=$(date +%s)
claude -p "$prompt" --model "$model" \
  --setting-sources project,local --strict-mcp-config \
  --permission-mode acceptEdits \
  --allowedTools "Bash(python tools/strateg.py *)" "Bash(python projects/*)" "PowerShell(python tools/strateg.py *)" "PowerShell(python projects/*)" "WebSearch" "WebFetch" \
  --output-format json > "runs/$label.json" 2> "runs/$label.err"
code=$?
end=$(date +%s)
echo "$label: exit=$code, $((end-start)) c" | tee -a runs/timing.txt
python tools/strateg.py cost import "runs/$label.json" --label "$label" 2>&1 | tail -n 2
