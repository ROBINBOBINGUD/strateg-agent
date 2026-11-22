#!/bin/sh
# Запуск хука на подходящем интерпретаторе: Python 3.10+ под именем python3 или python.
# Использование (из .claude/settings.json): sh "${CLAUDE_PROJECT_DIR}/tools/hooks/run.sh" guard.py
# Событие Claude Code приходит хуку в stdin; проверка версии stdin не читает.
# Если подходящего Python нет, хук молча пропускается: сеанс не должен падать из-за учёта и журнала.
hook="$1"
for py in python3 python; do
  if command -v "$py" >/dev/null 2>&1 && "$py" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
    exec "$py" "${CLAUDE_PROJECT_DIR}/tools/hooks/${hook}"
  fi
done
exit 0
