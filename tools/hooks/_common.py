"""Общие функции хуков. Хуки никогда не должны ронять сеанс: любая ошибка -> тихий выход 0."""
import json
import os
import re
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

TOOLS_DIR = Path(__file__).resolve().parent.parent
ROOT = TOOLS_DIR.parent
sys.path.insert(0, str(TOOLS_DIR))


def read_event() -> dict:
    """JSON события из stdin (Claude Code передаёт его каждому хуку)."""
    try:
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        return json.loads(raw) if raw.strip() else {}
    except Exception:
        return {}


def strateg():
    """Модуль CLI; None, если его не удалось импортировать."""
    try:
        os.environ.setdefault("CLAUDE_PROJECT_DIR", str(ROOT))
        import strateg as module  # noqa: WPS433
        return module
    except Exception:
        return None


def active_project():
    module = strateg()
    if module is None:
        return None
    try:
        return module.active_project()
    except Exception:
        return None


def emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    sys.stdout.flush()


def scrub(text: str) -> str:
    """Убирает из текста абсолютный путь к репозиторию и домашнюю папку: в журнал они не попадают."""
    if not text:
        return ""
    result = str(text)
    roots = [str(ROOT), os.environ.get("CLAUDE_PROJECT_DIR", "")]
    homes = [str(Path.home()), os.environ.get("USERPROFILE", ""), os.environ.get("HOME", "")]
    for marker, group in ((".", roots), ("~", homes)):
        for raw in sorted({value for value in group if len(value) > 3}, key=len, reverse=True):
            for variant in {raw, raw.replace("\\", "/"), raw.replace("\\", "\\\\")}:
                result = re.sub(re.escape(variant), lambda _match: marker, result, flags=re.IGNORECASE)
    return result


def rel(path_text: str) -> str:
    """Путь относительно корня репозитория с прямыми слэшами (для журнала и проверок)."""
    if not path_text:
        return ""
    try:
        return Path(path_text).resolve().relative_to(ROOT).as_posix()
    except Exception:
        return scrub(path_text).replace("\\", "/")
