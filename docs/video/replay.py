"""Воспроизведение настоящих сеансов агента по транскриптам Claude Code.

Что показывает: реплики человека, сообщение хука при старте сеанса, каждое действие агента и субагентов
(поиск, чтение, запись, команды CLI, расчёты) с исходным московским временем и ответы агента.
Ничего не добавлено и не переставлено: источник — транскрипты сеансов демонстрационного проекта,
журнал проекта и сводки заходов. Паузы между действиями сжаты, чтобы весь путь уложился в ролик.

Транскрипты лежат у автора локально (~/.claude/projects/...) и в репозиторий не входят: в них служебные
идентификаторы и локальные пути. Скрипт приложен, чтобы было видно, как собран ролик.

Запуск: python docs/video/replay.py [--minutes 8.3] [--project family-multisim]
"""
import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
MSK = timezone(timedelta(hours=3))
DIM, CYAN, YELLOW, GREEN, MAGENTA, BOLD, RESET = "\x1b[90m", "\x1b[36m", "\x1b[33m", "\x1b[32m", "\x1b[35m", "\x1b[1m", "\x1b[0m"
WIDTH = 112

SESSIONS = [
    ("2c3d44a5", "zahod-1-postanovka", "Запрос руководителя и постановка задачи", ""),
    ("c5e91cea", "zahod-2-issledovanie-varianty", "Сбор материалов, исследование, варианты", ""),
    ("4dbcc56f", "zahod-3-strategii-sborka", "Выбор человека, продуктовая и коммуникационная стратегии",
     "Сеанс оборвался: закончился лимит использования. Агент успел сохранить состояние."),
    ("a34284db", "zahod-4-proverka-sborka", "Продолжение после перерыва: план проверки и итоговый документ",
     "ПЕРЕРЫВ 4 ЧАСА. Новый чат не видел прежней переписки. Человек написал одно слово."),
    ("92999ff1", "zahod-5-priemka", "Приёмка", ""),
]
STEP_NAMES = {"intake": "Постановка задачи", "collect": "Сбор материалов", "research": "Исследование и картина ситуации",
              "options": "Варианты", "product": "Продуктовая стратегия", "comms": "Коммуникационная стратегия",
              "testplan": "План проверки", "final": "Сборка и самопроверка", "support": "Поддержка решения"}
MODELS = {"claude-opus-5-5": "Opus 5.5", "claude-sonnet-5-5": "Sonnet 5.5", "claude-haiku-5-5": "Haiku 5.5"}


def scrub(text: str) -> str:
    home = str(Path.home())
    for marker, raw in ((".", str(ROOT)), ("~", home)):
        for variant in {raw, raw.replace("\\", "/"), raw.replace("\\", "\\\\")}:
            text = re.sub(re.escape(variant), lambda _m: marker, text, flags=re.IGNORECASE)
    return text.replace("./", "").replace(".\\", "")


def load(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def stamp(row: dict):
    try:
        return datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00")).astimezone(MSK)
    except Exception:
        return None


def tool_line(name: str, data: dict) -> str | None:
    if name in ("PowerShell", "Bash"):
        command = " ".join(scrub(str(data.get("command", ""))).split())   # многострочную команду — в одну строку
        return f"{YELLOW}команда {RESET} {command}"
    if name == "Read":
        return f"{DIM}чтение  {RESET} {scrub(str(data.get('file_path', '')))}"
    if name in ("Write", "Edit", "MultiEdit"):
        verb = "запись  " if name == "Write" else "правка  "
        return f"{GREEN}{verb}{RESET} {scrub(str(data.get('file_path', '')))}"
    if name == "WebSearch":
        return f"{CYAN}поиск   {RESET} {data.get('query', '')}"
    if name == "WebFetch":
        return f"{CYAN}страница{RESET} {data.get('url', '')}"
    if name in ("Agent", "Task"):
        return f"{MAGENTA}субагент{RESET} {data.get('subagent_type', '')}: {data.get('description', '')}"
    if name == "Skill":
        return f"{MAGENTA}процедура{RESET} {data.get('skill', '')}"
    return None


def session_events(transcript: Path) -> tuple[list[dict], str, str]:
    """События сеанса по времени: действия основного агента и субагентов, тексты агента."""
    events, human, hook = [], "", ""
    for row in load(transcript):
        ts = stamp(row)
        kind = row.get("type")
        if kind == "attachment":
            att = row.get("attachment") or {}
            if att.get("hookEvent") == "SessionStart" and not hook:
                hook = str(att.get("content", ""))
            continue
        message = row.get("message") or {}
        content = message.get("content")
        if kind == "user" and isinstance(content, str) and not human:
            args = re.search(r"<command-args>(.*?)</command-args>", content, re.S)
            name = re.search(r"<command-name>(.*?)</command-name>", content, re.S)
            human = (f"{name.group(1)} " if name else "") + (args.group(1) if args else content)
        if kind != "assistant" or not isinstance(content, list) or ts is None:
            continue
        for block in content:
            if block.get("type") == "text" and block.get("text", "").strip():
                events.append({"ts": ts, "kind": "text", "text": block["text"].strip()})
            elif block.get("type") == "tool_use":
                line = tool_line(block.get("name", ""), block.get("input") or {})
                if line:
                    events.append({"ts": ts, "kind": "tool", "line": line})
    side = transcript.with_suffix("") / "subagents"
    for sub in sorted(side.glob("*.jsonl")) if side.is_dir() else []:
        meta_path = sub.with_name(sub.stem + ".meta.json")
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        label = f"{meta.get('agentType', 'субагент')} ({MODELS.get(meta.get('model', ''), meta.get('model', ''))})"
        for row in load(sub):
            ts = stamp(row)
            content = (row.get("message") or {}).get("content")
            if row.get("type") != "assistant" or not isinstance(content, list) or ts is None:
                continue
            for block in content:
                if block.get("type") == "tool_use":
                    line = tool_line(block.get("name", ""), block.get("input") or {})
                    if line:
                        events.append({"ts": ts, "kind": "sub", "line": f"{DIM}└ {label}{RESET} {line}"})
    events.sort(key=lambda event: event["ts"])
    texts = [event for event in events if event["kind"] == "text"]
    if texts:
        texts[-1]["kind"] = "final"
    return events, human.strip(), hook


def clip(line: str, limit: int = WIDTH) -> str:
    visible = re.sub(r"\x1b\[[0-9;]*m", "", line)
    if len(visible) <= limit:
        return line
    cut = len(line) - (len(visible) - limit) - 1
    return line[:max(cut, 20)] + "…" + RESET


def say(text: str = "", pause: float = 0.0) -> None:
    sys.stdout.write(text + "\n")
    sys.stdout.flush()
    if pause > 0:
        time.sleep(pause)


def type_out(prefix: str, text: str, rate: float = 90.0) -> None:
    sys.stdout.write(prefix)
    for index in range(0, len(text), 3):
        sys.stdout.write(text[index:index + 3])
        sys.stdout.flush()
        time.sleep(3 / rate)
    sys.stdout.write("\n")


def steps_table(project: Path, moment: datetime) -> list[str]:
    status = {key: "ожидает" for key in STEP_NAMES}
    marks = {"✓": "готово", "▶": "в работе", "■": "заблокирован"}
    for row in load(project / "journal.jsonl"):
        if row.get("event") != "step":
            continue
        try:
            when = datetime.fromisoformat(row["ts"])
        except Exception:
            continue
        if when > moment:
            break
        text = f"{row.get('target', '')} {row.get('note', '')}"
        step = next((key for key in STEP_NAMES if re.search(rf"\b{key}\b", text)), None)
        mark = next((value for key, value in marks.items() if key in text), None)
        if step and mark:
            status[step] = mark
    lines = []
    for key, name in STEP_NAMES.items():
        color = GREEN if status[key] == "готово" else (YELLOW if status[key] == "в работе" else DIM)
        lines.append(f"   {color}{status[key]:<9}{RESET} {name}")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--minutes", type=float, default=8.3)
    parser.add_argument("--project", default="family-multisim")
    parser.add_argument("--transcripts", default=str(Path.home() / ".claude" / "projects" / "C--Users-Vladimir-pc-Desktop-mgimo-strateg"))
    parser.add_argument("--fast", action="store_true", help="без пауз: проверка содержания перед записью")
    options = parser.parse_args()
    if options.fast:
        time.sleep = lambda *_args: None
    project = ROOT / "projects" / options.project
    base = Path(options.transcripts)
    sessions = []
    for prefix, label, title, note in SESSIONS:
        found = sorted(base.glob(prefix + "*.jsonl"))
        if not found:
            continue
        events, human, hook = session_events(found[0])
        summary_path = ROOT / "runs" / f"{label}.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
        sessions.append({"title": title, "note": note, "events": events, "human": human, "hook": hook, "summary": summary})

    # Сколько экранного времени уйдёт на неизменяемое: заголовки, реплики, ответы агента.
    fixed = 16.0
    gaps = []
    for session in sessions:
        fixed += 9.0 + min(len(session["human"]) / 90.0, 7.0)
        previous = None
        for event in session["events"]:
            if previous is not None:
                gaps.append((event["ts"] - previous).total_seconds())
            previous = event["ts"]
            if event["kind"] == "final":
                fixed += 7.0 + event["text"].count("\n") * 0.045
            elif event["kind"] == "text":
                fixed += 0.5
    budget = max(options.minutes * 60 - fixed, 60.0)
    low, high = 1.0, 5000.0
    for _ in range(40):                      # подбор сжатия пауз под заданную длину ролика
        speed = (low + high) / 2
        total = sum(min(max(gap / speed, 0.03), 0.9) for gap in gaps)
        if total > budget:
            low = speed
        else:
            high = speed
    speed = high
    shown = sum(min(max(gap / speed, 0.03), 0.9) for gap in gaps)
    ratio = sum(gaps) / shown if shown else 1.0      # во сколько раз сжато время работы агента
    if options.fast:
        print(f"оценка длительности: {(shown + fixed) / 60:.1f} мин; работа агента {sum(gaps) / 60:.0f} мин "
              f"сжата в {ratio:.1f} раза", file=sys.stderr)

    say()
    say(f"{BOLD}  Стратег: путь демонстрационного проекта по брифу МегаФона{RESET}")
    say(f"{DIM}  Воспроизведение транскриптов настоящих сеансов Claude Code, 22–23 ноября 2026.{RESET}")
    say(f"{DIM}  Слева — московское время каждого действия. Паузы между действиями сжаты: время работы агента короче примерно в {ratio:.0f} раз,{RESET}")
    say(f"{DIM}  реплики человека и ответы агента показаны целиком. Каждый сеанс — новый чат без истории.{RESET}", 4.0)

    for number, session in enumerate(sessions, 1):
        events = session["events"]
        if not events:
            continue
        start = events[0]["ts"]
        say()
        if session["note"] and number > 1:
            say(f"{YELLOW}{BOLD}  {session['note']}{RESET}", 1.2)
            if "ПЕРЕРЫВ" in session["note"]:
                say(f"{DIM}  Состояние проекта в файлах на момент возвращения:{RESET}")
                for line in steps_table(project, start):
                    say(line, 0.12)
                time.sleep(1.5)
        say(f"{BOLD}{CYAN}━━ Сеанс {number} из {len(sessions)} · {start:%d.%m %H:%M} МСК · {session['title']} ━━{RESET}", 0.8)
        hook_lines = [line for line in session["hook"].splitlines() if line.strip()]
        if hook_lines:
            picked = [hook_lines[0]] + [line for line in hook_lines if line.startswith(("Вопрос к человеку", "Следующее действие"))]
            for line in picked[:3]:
                say(clip(f"{DIM}хук при старте ▸ {scrub(line)}{RESET}"), 0.5)
        type_out(f"{BOLD}Человек ▸ {RESET}", session["human"])
        time.sleep(1.4)
        previous = start
        for event in events:
            gap = (event["ts"] - previous).total_seconds()
            previous = event["ts"]
            time.sleep(min(max(gap / speed, 0.03), 0.9))
            clock = f"{DIM}{event['ts']:%H:%M:%S}{RESET} "
            if event["kind"] in ("tool", "sub"):
                say(clip(clock + event["line"]))
            elif event["kind"] == "text":
                first = event["text"].splitlines()[0]
                say(clip(clock + f"{DIM}агент: {first}{RESET}"), 0.35)
            else:
                say()
                say(f"{BOLD}Агент ▸{RESET}", 0.3)
                for line in scrub(event["text"]).splitlines():
                    say("  " + line, 0.045)
                time.sleep(5.0)
        summary = session["summary"]
        if summary:
            models = ", ".join(f"{MODELS.get(name, name)} {usage['cost_usd']:.2f}".replace(".", ",")
                               for name, usage in summary.get("models", {}).items())
            say(f"{DIM}итог сеанса: {summary.get('duration_min', 0):.1f} мин · {summary.get('cost_usd', 0):.2f} USD в ценах API "
                f"({models}) · ходов {summary.get('turns')}{RESET}".replace(".", ","), 1.6)

    answer = ROOT / "runs" / "codex-perenos-otvet.md"
    prompt = ROOT / "runs" / "codex-portability-prompt.txt"
    if answer.exists() and prompt.exists():
        say()
        say(f"{BOLD}{CYAN}━━ Другая среда · Codex CLI (gpt-6.2-sol) · тот же проект, новые данные после решения ━━{RESET}", 0.8)
        say(f"{DIM}В Codex нет хуков и skills: он читает AGENTS.md и файлы процедур как обычный текст.{RESET}", 0.8)
        type_out(f"{BOLD}Человек ▸ {RESET}", prompt.read_text(encoding="utf-8").strip())
        time.sleep(1.2)
        log = ROOT / "runs" / "raw" / "codex-portability.log"
        if log.exists():
            lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
            shown = 0
            for index, line in enumerate(lines[:-1]):
                if line.strip() == "exec" and "strateg.py" in lines[index + 1] and shown < 14:
                    command = re.search(r"(python\S*\s+tools[\\/]+strateg\.py[^'\"]*)", lines[index + 1])
                    if command:
                        say(clip(f"{YELLOW}команда {RESET} {scrub(command.group(1)).strip()}"), 0.4)
                        shown += 1
        say()
        say(f"{BOLD}Codex ▸{RESET}", 0.3)
        for line in answer.read_text(encoding="utf-8").strip().splitlines()[:60]:
            say("  " + line, 0.05)
        time.sleep(5.0)

    say()
    say(f"{BOLD}{CYAN}━━ Сейчас: команды в папке проекта ━━{RESET}", 0.6)
    for command in (["status"], ["cost"], ["decisions", "due"]):
        say(f"{BOLD}strateg> {RESET}python tools/strateg.py {' '.join(command)}", 0.5)
        result = subprocess.run([sys.executable, str(ROOT / "tools" / "strateg.py"), *command], cwd=ROOT, capture_output=True)
        for line in result.stdout.decode("utf-8", "replace").splitlines():
            say("  " + line, 0.04)
        time.sleep(2.5)
    say()
    say(f"{DIM}  Конец воспроизведения. Репозиторий, итоговый документ и описание работы — по ссылкам в заявке.{RESET}", 3.0)
    marker = ROOT / "docs" / "video" / "raw" / "replay.done"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(datetime.now().astimezone().isoformat(timespec="seconds"), encoding="utf-8")


if __name__ == "__main__":
    main()
