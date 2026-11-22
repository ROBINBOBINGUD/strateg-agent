"""Достаёт итоговый ответ Codex из журнала `codex exec` и сохраняет его без служебных строк.

Запуск: python runs/codex_answer.py <журнал> <файл ответа>
"""
import re
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    log = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
    marker = "\ncodex\n"
    start = log.rfind(marker)
    answer = log[start + len(marker):] if start >= 0 else log[-6000:]
    end = answer.find("\ntokens used")
    tokens = ""
    if end >= 0:
        found = re.search(r"tokens used\s*\n\s*([\d\s ]+)", answer[end:])
        tokens = found.group(1).strip() if found else ""
        answer = answer[:end]
    home = str(Path.home())
    for marker_text, raw in ((".", str(ROOT)), ("~", home)):
        for variant in {raw, raw.replace("\\", "/"), raw.replace("\\", "\\\\")}:
            answer = re.sub(re.escape(variant), lambda _m: marker_text, answer, flags=re.IGNORECASE)
    Path(sys.argv[2]).write_text(answer.strip() + "\n", encoding="utf-8")
    print(f"ответ Codex: {len(answer)} символов, токенов: {tokens or 'нет данных'} -> {sys.argv[2]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
