"""Командная строка для ведения проектов Стратега."""

import argparse
from datetime import date, datetime
import json
import math
import os
from pathlib import Path
import random
import re
import shutil
import sys
import tempfile
import time
from uuid import uuid4


DEFAULT_STEPS = (
    ("intake", "Постановка задачи"),
    ("collect", "Сбор материалов"),
    ("research", "Исследование и картина ситуации"),
    ("options", "Варианты"),
    ("product", "Продуктовая стратегия"),
    ("comms", "Коммуникационная стратегия"),
    ("testplan", "План проверки"),
    ("final", "Сборка и самопроверка"),
    ("support", "Поддержка решения"),
)
SOURCE_TYPES = ("document", "table", "site", "interview", "synthetic", "calc")
RELIABILITIES = ("A", "B", "C")
EVIDENCE_KINDS = ("fact", "hypothesis", "forecast", "assumption", "synthetic")
CONFIDENCES = ("high", "medium", "low")
EVIDENCE_STATUSES = ("active", "revoked")
DECISION_STATUSES = ("active", "revised", "cancelled")
EVENTS = ("tool", "step", "gate", "escalation", "error", "injection", "note", "cost")
COST_SOURCES = ("headless", "stop-hook", "manual")
MEMORY_KINDS = ("lesson", "pattern", "agent-conclusion")
MODEL_FIELDS = {
    "inputTokens": "input",
    "outputTokens": "output",
    "cacheReadInputTokens": "cache_read",
    "cacheCreationInputTokens": "cache_write",
    "costUSD": "cost_usd",
}
REGISTRIES = ("sources", "evidence", "decisions", "journal", "costs")
STEP_STATUSES = {
    "pending": "○ Ожидает",
    "in_progress": "▶ В работе",
    "done": "✓ Готово",
    "blocked": "■ Заблокирован",
}
REFERENCE_ID = r"[ES]-[0-9]{3,}"
CITATION = re.compile(rf"\[[ \t]*({REFERENCE_ID}(?:[ \t]*[,;][ \t]*{REFERENCE_ID})*)[ \t]*\]")
CITATION_MARKER = re.compile(r"\[[ \t]*[ES]-[^\[\]\r\n]*\]")
REFERENCE_MENTION = re.compile(rf"\b{REFERENCE_ID}\b")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
INLINE_CODE = re.compile(r"(?<!`)(`+)(?!`).*?(?<!`)\1(?!`)", re.DOTALL)
NUMBER = re.compile(r"[0-9]{3,}|[0-9]\s*(?:%|руб|тыс|млн)", re.IGNORECASE)
ASSUMPTION = re.compile(r"\bдопущение\b", re.IGNORECASE)
WORD = re.compile(r"[^\W_]+")


class CliError(Exception):
    """Ошибка, которую можно показать пользователю."""


class LockTimeout(CliError):
    """Файл остался заблокирован по истечении срока ожидания."""


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def find_root() -> Path:
    configured = os.environ.get("CLAUDE_PROJECT_DIR")
    if configured:
        try:
            path = Path(configured).expanduser()
            if (path / "AGENTS.md").is_file():
                return path.resolve()
        except (OSError, ValueError, RuntimeError):
            pass
    script_root = Path(__file__).resolve().parents[1]
    if (script_root / "AGENTS.md").is_file():
        return script_root
    current = Path.cwd().resolve()
    for path in (current, *current.parents):
        if (path / "AGENTS.md").is_file():
            return path
    raise CliError("Не найден корень репозитория с файлом AGENTS.md.")


def selected_project() -> Path | None:
    projects = find_root() / "projects"
    active = projects / "ACTIVE"
    if not active.is_file():
        return None
    project_id = active.read_text(encoding="utf-8-sig").strip()
    if not valid_project_id(project_id):
        return None
    project = projects / project_id
    return project if project.is_dir() else None


def active_project() -> Path | None:
    project = selected_project()
    return project if project is not None and (project / "state.json").is_file() else None


def require_project() -> Path:
    project = active_project()
    if project is None:
        raise CliError("Нет активного проекта. Выберите его командой use или создайте командой new.")
    return project


def valid_project_id(value: str) -> bool:
    return (
        bool(value)
        and value.casefold() not in {"_template", "active", ".", ".."}
        and value == value.strip()
        and not value.endswith(".")
        and not re.search(r'[<>:"/\\|?*\x00-\x1f]', value)
        and not re.fullmatch(r"(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\..*)?", value, re.I)
    )


def project_path(project_id: str) -> Path:
    if not valid_project_id(project_id):
        raise CliError(f"Недопустимый идентификатор проекта: {project_id!r}.")
    return find_root() / "projects" / project_id


def invalid_constant(value: str):
    raise ValueError(f"недопустимое значение JSON {value}")


def json_text(value, *, indent=None) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, indent=indent)


def read_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"), parse_constant=invalid_constant)
    except json.JSONDecodeError as exc:
        raise CliError(f"{path}:{exc.lineno} — некорректный JSON (столбец {exc.colno}).") from exc
    except UnicodeError as exc:
        raise CliError(f"{path} — требуется кодировка UTF-8.") from exc
    except ValueError as exc:
        raise CliError(f"{path} — {exc}.") from exc
    if not isinstance(value, dict):
        raise CliError(f"{path} — ожидается объект JSON.")
    return value


def write_text(path: Path, content: str) -> None:
    write_bytes(path, content.encode("utf-8"))


def write_bytes(path: Path, content: bytes) -> None:
    with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, delete=False) as temporary:
        temporary_path = Path(temporary.name)
        try:
            temporary.write(content)
            temporary.close()
            temporary_path.replace(path)
        finally:
            temporary.close()
            temporary_path.unlink(missing_ok=True)


def write_object(path: Path, value: dict) -> None:
    write_text(path, json_text(value, indent=2) + "\n")


def decode_row(raw: bytes, line: int) -> dict:
    try:
        encoding = "utf-8-sig" if line == 1 else "utf-8"
        record = json.loads(raw.decode(encoding), parse_constant=invalid_constant)
    except UnicodeError as exc:
        raise ValueError("требуется кодировка UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"некорректный JSON (столбец {exc.colno})") from exc
    if not isinstance(record, dict):
        raise ValueError("ожидается объект JSON")
    return record


def read_rows(path: Path, report=None) -> list[tuple[int, dict]]:
    if not path.exists():
        return []
    rows = []
    with path.open("rb") as stream:
        for line, raw in enumerate(stream, 1):
            try:
                record = decode_row(raw, line)
            except ValueError as exc:
                if report is None:
                    raise CliError(f"{path}:{line} — {exc}.") from exc
                report(path, line, str(exc))
            else:
                rows.append((line, record))
    return rows


def records(path: Path) -> list[dict]:
    return [record for _, record in read_rows(path)]


def tolerant_records(path: Path, problems: list | None = None) -> list[dict]:
    """Чтение журнала и расходов: повреждённая строка пропускается и попадает в список замечаний,
    а не останавливает команду. Реестры источников и утверждений читаются строго (`records`)."""
    def report(file: Path, line: int, problem: str) -> None:
        if problems is not None:
            problems.append(f"{file.name}:{line} — {problem}")
    return [record for _, record in read_rows(path, report)]


class file_lock:
    """Межпроцессная блокировка файла реестра.

    Хуки Claude Code запускаются отдельными процессами; когда несколько субагентов работают
    параллельно, они дописывают журнал одновременно. Без блокировки строки JSONL перемешиваются.
    Блокировка — соседний файл `<имя>.lock`, создаваемый атомарно; зависшая (старше 30 секунд) снимается.
    """

    def __init__(self, path: Path, timeout: float = 5.0):
        self.lock = path.with_name(path.name + ".lock")
        self.timeout = timeout
        self.held = False

    def __enter__(self):
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                os.close(os.open(self.lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                self.held = True
                return self
            except FileExistsError:
                try:
                    if time.time() - self.lock.stat().st_mtime > 30:
                        self.lock.unlink(missing_ok=True)
                        continue
                except FileNotFoundError:
                    pass
                except PermissionError:
                    pass
            if time.monotonic() >= deadline:
                raise LockTimeout(f"Файл {self.lock.name.removesuffix('.lock')} занят. Повторите команду.")
            time.sleep(0.02 + random.random() * 0.03)

    def __exit__(self, *exc):
        if self.held:
            try:
                self.lock.unlink(missing_ok=True)
            except OSError:
                pass
        return False


def append_record(path: Path, record: dict) -> None:
    with file_lock(path):
        append_unlocked(path, record)


def append_unlocked(path: Path, record: dict) -> None:
    payload = (json_text(record) + "\n").encode("utf-8")
    with path.open("a+b") as stream:
        if stream.tell():
            stream.seek(-1, os.SEEK_END)
            if stream.read(1) != b"\n":
                payload = b"\n" + payload
        stream.write(payload)


def write_records(path: Path, rows: list[dict]) -> None:
    write_text(path, "".join(json_text(row) + "\n" for row in rows))


def append_journal(project: Path, event: dict) -> None:
    record = {"ts": now(), "session": "", "tool": "", "target": "", "note": "", **event}
    project_dir = project.resolve()
    root = next(
        (parent for parent in project_dir.parents if (parent / "AGENTS.md").is_file()),
        project_dir.parent.parent,
    )
    root_path = re.compile(re.escape(root.as_posix()).replace("/", r"[/\\]"), re.IGNORECASE)
    for field in ("target", "note"):
        if isinstance(record[field], str):
            record[field] = root_path.sub(".", record[field])
    path = project / "journal.jsonl"
    try:
        append_record(path, record)
    except LockTimeout:
        append_unlocked(path, record)


def upsert_cost(project: Path, record: dict) -> None:
    path = project / "costs.jsonl"
    session = record["session"]
    record = {"ts": now(), **record}
    with file_lock(path):
        lines = []
        inserted = False
        payload = (json_text(record) + "\n").encode("utf-8")
        if path.exists():
            with path.open("rb") as stream:
                for number, raw in enumerate(stream, 1):
                    try:
                        existing = decode_row(raw, number)
                    except ValueError:
                        lines.append(raw)
                        continue
                    if existing.get("session") != session:
                        lines.append(raw)
                        continue
                    if existing.get("source") == "headless" and record.get("source") == "stop-hook":
                        return
                    if not inserted:
                        lines.append(payload)
                        inserted = True
        if not inserted:
            index = len(lines)
            if lines and not lines[-1].endswith(b"\n"):
                index -= 1
            lines.insert(index, payload)
        write_bytes(path, b"".join(lines))


def next_id(rows: list[dict], prefix: str) -> str:
    numbers = []
    for row in rows:
        identifier = row.get("id")
        if not isinstance(identifier, str):
            continue
        match = re.fullmatch(rf"{prefix}-([0-9]{{3,}})", identifier)
        if match:
            numbers.append(int(match[1]))
    return f"{prefix}-{max(numbers, default=0) + 1:03d}"


def csv_items(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def new_state(project_id: str, title: str, timestamp: str) -> dict:
    return {
        "id": project_id, "title": title, "created": timestamp, "updated": timestamp,
        "current_step": "intake",
        "steps": [
            {"id": step_id, "title": step_title, "status": "pending", "started": None,
             "finished": None, "outputs": [], "note": ""}
            for step_id, step_title in DEFAULT_STEPS
        ],
        "waiting_for_human": None, "gates": [],
    }


def save_state(project: Path, state: dict, timestamp: str) -> None:
    state["updated"] = timestamp
    write_object(project / "state.json", state)


def new_project(args) -> None:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", args.id):
        raise CliError("Идентификатор проекта должен содержать от 1 до 40 строчных латинских букв, "
                       "цифр или дефисов и начинаться с буквы или цифры.")
    project = project_path(args.id)
    projects = project.parent
    projects.mkdir(exist_ok=True)
    template = projects / "_template"
    active = projects / "ACTIVE"
    with file_lock(active):
        if project.exists() or any(
            path.is_dir() and path.name.casefold() == args.id for path in projects.iterdir()
        ):
            raise CliError(f"Проект {args.id} уже существует.")
        timestamp = now()
        with tempfile.TemporaryDirectory(dir=projects) as temporary:
            staging = Path(temporary) / project.name
            if template.is_dir():
                shutil.copytree(template, staging)
            else:
                staging.mkdir()
            for name in REGISTRIES:
                path = staging / f"{name}.jsonl"
                if not path.exists():
                    path.write_text("", encoding="utf-8")
            for name in ("materials", "outputs", "analysis"):
                path = staging / name
                if not path.exists():
                    path.mkdir()
                    (path / ".gitkeep").write_text("", encoding="utf-8")
            state_file = staging / "state.json"
            with file_lock(state_file):
                state = read_object(state_file) if state_file.is_file() else new_state(args.id, args.title, timestamp)
                state.update(id=args.id, title=args.title, created=timestamp, current_step="intake")
                find_step(state, "intake").update(status="in_progress", started=timestamp, finished=None)
                save_state(staging, state, timestamp)
            staging.rename(project)
        write_text(active, args.id + "\n")
    print(f"Создан проект {args.id}.")


def use_project(args) -> None:
    project = project_path(args.id)
    if not (project / "state.json").is_file():
        raise CliError(f"Проект {args.id} не найден.")
    active = project.parent / "ACTIVE"
    with file_lock(active):
        write_text(active, args.id + "\n")
    print(f"Активный проект: {args.id}.")


def list_projects(args) -> None:
    active = active_project()
    projects = find_root() / "projects"
    found = False
    for project in sorted(projects.glob("*/state.json")):
        if not valid_project_id(project.parent.name):
            continue
        state = read_object(project)
        marker = "*" if project.parent == active else " "
        print(f"{marker} {state['id']} | {state['title']} | {state['current_step']}")
        found = True
    if not found:
        print("Проектов пока нет.")


def find_step(state: dict, step_id: str) -> dict:
    for step in state["steps"]:
        if step["id"] == step_id:
            return step
    raise CliError(f"Шаг {step_id} не найден.")


def next_step(state: dict) -> dict | None:
    return next((step for step in state["steps"] if step["status"] != "done"), None)


def change_step(args) -> None:
    project = require_project()
    state_file = project / "state.json"
    with file_lock(state_file):
        state = read_object(state_file)
        step = find_step(state, args.step_id)
        waiting = state["waiting_for_human"]
        if args.action == "done":
            if step["status"] != "in_progress":
                raise CliError(f"Шаг {args.step_id} нельзя завершить. Текущий статус: {step['status']}.")
            if waiting and waiting["step"] == args.step_id:
                raise CliError("Шаг ожидает ответа человека. Запишите ответ командой gate answer.")
        if args.action == "start" and waiting and waiting["step"] != args.step_id:
            raise CliError(f"Сначала ответьте на открытый вопрос шага {waiting['step']} командой gate answer.")
        redo = args.action == "start" and (step["finished"] is not None or step["status"] == "done")
        if redo and not args.redo:
            raise CliError("Шаг уже выполнен. Для повторного запуска укажите --redo.")
        if args.outputs is not None:
            outputs = csv_items(args.outputs)
            missing = [
                item for item in outputs
                if Path(item).anchor or not (project / item).resolve().is_relative_to(project.resolve())
                or not (project / item).exists()
            ]
            if missing:
                raise CliError(f"Отсутствуют в каталоге проекта: {', '.join(missing)}.")
            step["outputs"] = outputs
        timestamp = now()
        if args.action == "start":
            step.update(status="in_progress", started=timestamp)
        elif args.action == "done":
            step.update(status="done", finished=timestamp)
        else:
            step.update(status="blocked")
        if args.note is not None:
            step["note"] = args.note
        following = next_step(state) if args.action == "done" else None
        state["current_step"] = following["id"] if following else args.step_id
        save_state(project, state, timestamp)
    label = STEP_STATUSES[step["status"]]
    note = f"Повторный запуск: {args.note or 'запрошен явно через --redo'}" if redo else label
    if args.note and not redo:
        note += f" — {args.note}"
    append_journal(project, {"event": "step", "tool": "step", "target": args.step_id, "note": note})
    print(f"{args.step_id} | {label}")


def ask_gate(args) -> None:
    project = require_project()
    state_file = project / "state.json"
    with file_lock(state_file):
        state = read_object(state_file)
        if state["waiting_for_human"] is not None:
            raise CliError("Уже есть вопрос без ответа. Сначала запишите ответ командой gate answer.")
        step_id = args.step or state["current_step"]
        find_step(state, step_id)
        options = [part.strip() for part in args.options.split("|") if part.strip()]
        timestamp = now()
        state["waiting_for_human"] = {
            "question": args.question, "options": options, "step": step_id, "since": timestamp,
        }
        save_state(project, state, timestamp)
    print(f"Записан вопрос для шага {step_id}.")


def answer_gate(args) -> None:
    project = require_project()
    state_file = project / "state.json"
    with file_lock(state_file):
        state = read_object(state_file)
        waiting = state["waiting_for_human"]
        if waiting is None:
            print("Нет открытого вопроса.")
            if state["gates"]:
                print(f"Последний записанный ответ: {state['gates'][-1]['answer']}")
            return
        timestamp = now()
        state["gates"].append({
            "step": waiting["step"], "question": waiting["question"], "options": waiting["options"],
            "answer": args.answer, "asked": waiting["since"], "answered": timestamp,
        })
        state["waiting_for_human"] = None
        save_state(project, state, timestamp)
    append_journal(project, {
        "event": "gate", "tool": "gate", "target": waiting["step"],
        "note": f"{waiting['question']} — {args.answer}",
    })
    print("Ответ записан.")


def add_source(args) -> None:
    path = require_project() / "sources.jsonl"
    with file_lock(path):
        rows = records(path)
        existing = next((row for row in rows if row["ref"] == args.ref), None)
        if existing is not None:
            print(existing["id"])
            return
        identifier = next_id(rows, "S")
        append_unlocked(path, {
            "id": identifier, "type": args.type, "title": args.title, "ref": args.ref,
            "publisher": args.publisher, "published": args.published, "accessed": date.today().isoformat(),
            "reliability": args.reliability, "note": args.note,
        })
    print(identifier)


def add_evidence(args) -> None:
    path = require_project() / "evidence.jsonl"
    with file_lock(path):
        identifier = next_id(records(path), "E")
        append_unlocked(path, {
            "id": identifier, "kind": args.kind, "text": args.text, "sources": csv_items(args.sources),
            "confidence": args.confidence, "status": "active", "updated": date.today().isoformat(),
            "note": args.note,
        })
    print(identifier)


def find_record(rows: list[dict], identifier: str) -> dict:
    for row in rows:
        if row["id"] == identifier:
            return row
    raise CliError(f"Запись {identifier} не найдена.")


def revoke_evidence(args) -> None:
    project = require_project()
    path = project / "evidence.jsonl"
    with file_lock(path):
        rows = records(path)
        record = find_record(rows, args.id)
        record.update(status="revoked", updated=date.today().isoformat())
        write_records(path, rows)
    append_journal(project, {"event": "note", "tool": "revoke", "target": args.id, "note": args.reason})
    print(f"Утверждение {args.id} отозвано.")


def table_cell(value) -> str:
    text = " ".join(str(value).splitlines())
    return text.replace("\\", "\\\\").replace("|", "\\|")


def markdown_table(headers, rows) -> str:
    def line(fields):
        return "| " + " | ".join(table_cell(field) for field in fields) + " |"
    return "\n".join([line(headers), line("---" for _ in headers), *(line(row) for row in rows)])


def clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit - 1] + "…"


def cost_totals(rows: list[dict]) -> tuple[float, float]:
    return sum(row["cost_usd"] for row in rows), sum(row["duration_s"] for row in rows)


def cost_summary(amount: float, duration: float) -> str:
    return f"{amount:.6f} USD, {duration / 60:.2f} мин"


def status_data(project: Path, registries: dict | None = None) -> dict:
    state = read_object(project / "state.json")
    if registries is None:
        registries = {
            name: records(project / f"{name}.jsonl")
            for name in ("sources", "evidence", "decisions")
        }
        registries["costs"] = cost_rows(project / "costs.jsonl")
    evidence = registries["evidence"]
    following = next_step(state)
    amount, duration = cost_totals(registries["costs"])
    return {
        **state,
        "next_action": following["id"] if following else None,
        "source_count": len(registries["sources"]),
        "evidence_counts": {kind: sum(row["kind"] == kind for row in evidence) for kind in EVIDENCE_KINDS},
        "decision_count": len(registries["decisions"]),
        "cost_usd": amount,
        "duration_s": duration,
    }


def format_status(data: dict) -> str:
    steps = (
        (step["id"], step["title"], STEP_STATUSES[step["status"]])
        for step in data["steps"]
    )
    lines = [
        f"# {clip(table_cell(data['title']), 300)}",
        "",
        markdown_table(("Шаг", "Название", "Статус"), steps),
    ]
    waiting = data["waiting_for_human"]
    if waiting is not None:
        question = clip(table_cell(waiting["question"]), 480)
        lines.extend(("", f"Вопрос к человеку ({waiting['step']}): {question}"))
        if waiting["options"]:
            options = clip("; ".join(map(table_cell, waiting["options"])), 300)
            lines.append(f"Варианты ответа: {options}")
    following = data["next_action"]
    action = f"{following} — {find_step(data, following)['title']}" if following else "все шаги завершены"
    counts = ", ".join(f"{kind}: {count}" for kind, count in data["evidence_counts"].items())
    lines.extend((
        "", f"Следующее действие: {action}.", "",
        f"Источников: {data['source_count']}. Утверждений: {sum(data['evidence_counts'].values())} ({counts}).",
        f"Решений: {data['decision_count']}. Расходы и время: {cost_summary(data['cost_usd'], data['duration_s'])}.",
    ))
    return clip("\n".join(lines), 2500)


def status_text(project: Path) -> str:
    return format_status(status_data(project))


def show_status(args) -> None:
    project = require_project()
    data = status_data(project)
    rendered = format_status(data)
    write_text(project / "STATUS.md", rendered + "\n")
    print(json_text(data, indent=2) if args.json else rendered)


def is_date(value) -> bool:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def is_timestamp(value) -> bool:
    if not isinstance(value, str):
        return False
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    return parsed.utcoffset() is not None


def is_amount(value) -> bool:
    return type(value) in (int, float) and value >= 0 and (type(value) is int or math.isfinite(value))


def is_token_count(value) -> bool:
    return type(value) is int and value >= 0


MODEL_SCHEMA = {
    "input": is_token_count, "output": is_token_count,
    "cache_read": is_token_count, "cache_write": is_token_count, "cost_usd": is_amount,
}


def valid_models(value) -> bool:
    return isinstance(value, dict) and all(
        isinstance(usage, dict) and all(test(usage.get(field)) for field, test in MODEL_SCHEMA.items())
        for usage in value.values()
    )


def id_test(prefix: str):
    pattern = re.compile(rf"{prefix}-[0-9]{{3,}}")
    return lambda value: isinstance(value, str) and pattern.fullmatch(value) is not None


def id_list_test(prefix: str):
    test_id = id_test(prefix)
    return lambda value: isinstance(value, list) and all(map(test_id, value))


SCHEMAS = {
    "sources": {
        "id": id_test("S"), "type": SOURCE_TYPES, "title": str, "ref": str,
        "publisher": str, "published": str, "accessed": is_date,
        "reliability": RELIABILITIES, "note": str,
    },
    "evidence": {
        "id": id_test("E"), "kind": EVIDENCE_KINDS, "text": str, "sources": id_list_test("S"),
        "confidence": CONFIDENCES, "status": EVIDENCE_STATUSES, "updated": is_date, "note": str,
    },
    "decisions": {
        "id": id_test("D"), "date": is_date, "decision": str, "owner": str, "metric": str,
        "review_condition": str, "review_date": lambda value: value == "" or is_date(value),
        "based_on": id_list_test("E"), "status": DECISION_STATUSES,
    },
    "journal": {
        "ts": is_timestamp, "session": str, "event": EVENTS, "tool": str, "target": str, "note": str,
    },
    "costs": {
        "ts": is_timestamp, "session": str, "source": COST_SOURCES, "label": str,
        "duration_s": is_amount, "cost_usd": is_amount, "models": valid_models,
    },
}


def record_problems(record: dict, schema: dict):
    for field, test in schema.items():
        if field not in record:
            yield f"отсутствует поле «{field}»"
            continue
        value = record[field]
        if test is str:
            if not isinstance(value, str):
                yield f"поле «{field}» должно быть строкой"
        elif isinstance(test, tuple):
            if value not in test:
                yield f"недопустимое значение поля «{field}». Допустимо: {', '.join(test)}"
        elif not test(value):
            yield f"неверный формат поля «{field}»"


def checked_rows(path: Path, schema: dict, report) -> list[tuple[int, dict]]:
    rows = []
    seen = set()
    key = "id" if "id" in schema else "session" if path.stem == "costs" else None
    for line, record in read_rows(path, report):
        problems = list(record_problems(record, schema))
        identifier = record.get(key)
        duplicate = key is not None and isinstance(identifier, str) and identifier in seen
        if duplicate:
            label = "идентификатор" if key == "id" else "сеанс"
            problems.append(f"повторяется {label} {identifier}")
        elif key is not None and isinstance(identifier, str):
            seen.add(identifier)
        for problem in problems:
            report(path, line, problem)
        if not problems:
            rows.append((line, record))
    return rows


def cost_rows(path: Path) -> list[dict]:
    def warn(file, line, problem):
        print(f"ПРЕДУПРЕЖДЕНИЕ: {file.name}:{line} — {problem}", file=sys.stderr)

    return [row for _, row in checked_rows(path, SCHEMAS["costs"], warn)]


def read_state(path: Path) -> dict:
    state = read_object(path)

    def validate(record, schema, location):
        if not isinstance(record, dict):
            raise CliError(f"{path} — в {location} ожидается объект JSON.")
        problem = next(record_problems(record, schema), None)
        if problem:
            raise CliError(f"{path} — {location}: {problem}.")

    def strings(value):
        return isinstance(value, list) and all(isinstance(item, str) for item in value)

    def optional_timestamp(value):
        return value is None or is_timestamp(value)

    validate(state, {
        "id": str, "title": str, "created": is_timestamp, "updated": is_timestamp,
        "current_step": str, "steps": lambda value: isinstance(value, list) and bool(value),
        "waiting_for_human": lambda value: value is None or isinstance(value, dict),
        "gates": lambda value: isinstance(value, list),
    }, "состояние проекта")
    step_ids = set()
    for index, step in enumerate(state["steps"], 1):
        location = f"steps, запись {index}"
        validate(step, {
            "id": str, "title": str, "status": tuple(STEP_STATUSES), "started": optional_timestamp,
            "finished": optional_timestamp, "outputs": strings, "note": str,
        }, location)
        if step["id"] in step_ids:
            raise CliError(f"{path} — {location}: повторяется шаг {step['id']}.")
        step_ids.add(step["id"])
    if state["current_step"] not in step_ids:
        raise CliError(f"{path} — поле «current_step» ссылается на неизвестный шаг {state['current_step']}.")

    gate_schema = {"step": lambda value: isinstance(value, str) and value in step_ids,
                   "question": str, "options": strings}
    if state["waiting_for_human"] is not None:
        validate(state["waiting_for_human"], {**gate_schema, "since": is_timestamp}, "waiting_for_human")
    for index, gate in enumerate(state["gates"], 1):
        validate(gate, {**gate_schema, "answer": str, "asked": is_timestamp, "answered": is_timestamp},
                 f"gates, запись {index}")
    return state


def paragraphs(lines):
    paragraph = []
    for number, line in enumerate(lines, 1):
        if line.strip():
            paragraph.append((number, line))
        elif paragraph:
            yield paragraph
            paragraph = []
    if paragraph:
        yield paragraph


def citations(line: str) -> set[str]:
    return {identifier.strip() for group in CITATION.findall(line) for identifier in re.split("[,;]", group)}


def markdown_paragraphs(lines):
    fence = None
    prose = []
    for line in lines:
        marker = FENCE.match(line)
        if fence is not None:
            if (marker and marker[1].startswith(fence) and not marker[2].strip()):
                fence = None
            prose.append("")
        elif marker and (marker[1][0] == "~" or "`" not in marker[2]):
            fence = marker[1]
            prose.append("")
        else:
            prose.append(line)
    for paragraph in paragraphs(prose):
        text = "\n".join(line for _, line in paragraph)
        text = INLINE_CODE.sub(lambda match: re.sub(r"[^\n]", " ", match[0]), text)
        yield list(zip((number for number, _ in paragraph), text.split("\n")))


def output_files(project: Path):
    return sorted(path for path in (project / "outputs").glob("*.md") if path.is_file())


def check_outputs(project: Path, sources: dict, evidence: dict, error, warning) -> set[str]:
    used = set()
    for path in output_files(project):
        try:
            lines = path.read_text(encoding="utf-8-sig").splitlines()
        except UnicodeDecodeError as exc:
            error(path, exc.object[:exc.start].count(b"\n") + 1, "требуется кодировка UTF-8")
            continue
        for paragraph in markdown_paragraphs(lines):
            has_ref = False
            synthetic = None
            for number, line in paragraph:
                for marker in CITATION_MARKER.findall(line):
                    if not CITATION.fullmatch(marker):
                        error(path, number, f"неверный формат ссылки {marker}")
                for identifier in sorted(citations(line)):
                    has_ref = True
                    if identifier.startswith("S-"):
                        used.add(identifier)
                    registry = sources if identifier.startswith("S-") else evidence
                    if identifier not in registry:
                        error(path, number, f"ссылка на несуществующую запись {identifier}")
                        continue
                    record = registry[identifier]
                    if record.get("status") == "revoked":
                        error(path, number, f"ссылка на отозванное утверждение {identifier}")
                    if synthetic is None and (record.get("kind") == "synthetic" or record.get("type") == "synthetic"):
                        synthetic = number, identifier
            if synthetic and not any("синтет" in lines[number - 1].casefold() for number, _ in paragraph):
                number, identifier = synthetic
                error(path, number, f"синтетика без пометки ({identifier})")
            if not has_ref and not any(ASSUMPTION.search(line) for _, line in paragraph):
                for number, line in paragraph:
                    if NUMBER.search(line):
                        warning(path, number, "число в абзаце без ссылки или пометки «допущение»")
    return used


def check_evidence(path: Path, rows: list[tuple[int, dict]], sources: dict, error) -> set[str]:
    used = set()
    for line, row in rows:
        references = row["sources"]
        used.update(references)
        for identifier in dict.fromkeys(references):
            if identifier not in sources:
                error(path, line, f"источник {identifier} не существует")
        types = {sources[identifier]["type"] for identifier in references if identifier in sources}
        if row["kind"] == "fact" and not references:
            error(path, line, "у факта должен быть хотя бы один источник")
        elif row["kind"] == "fact" and types == {"synthetic"} and all(ref in sources for ref in references):
            error(path, line, "факт опирается только на синтетические источники")
        if row["kind"] == "synthetic" and types - {"synthetic"}:
            error(path, line, "синтетическое утверждение ссылается на несинтетический источник")
    return used


def render_registries(project: Path, registries: dict) -> None:
    status = format_status(status_data(project, registries))
    source_columns = ("id", "type", "title", "ref", "publisher", "published", "accessed", "reliability", "note")
    source_rows = ([row[field] for field in source_columns] for row in registries["sources"])
    source_table = markdown_table(
        ("ID", "Тип", "Название", "Ссылка", "Издатель", "Публикация", "Обращение", "Надёжность", "Заметка"),
        source_rows,
    )
    evidence_rows = []
    for row in registries["evidence"]:
        fields = (
            row["id"], row["kind"], row["text"], ", ".join(row["sources"]),
            row["confidence"], row["status"], row["updated"], row["note"],
        )
        if row["status"] == "revoked":
            fields = tuple(f"~~{value}~~" if value else "" for value in fields)
        evidence_rows.append(fields)
    evidence_table = markdown_table(
        ("ID", "Вид", "Утверждение", "Источники", "Уверенность", "Статус", "Обновлено", "Заметка"),
        evidence_rows,
    )
    write_text(project / "sources.md", f"# Источники\n\n{source_table}\n")
    write_text(project / "evidence.md", f"# Утверждения\n\n{evidence_table}\n")
    write_text(project / "STATUS.md", status + "\n")


def past_review(row: dict, today: str) -> bool:
    return bool(row["review_date"]) and row["review_date"] < today


def check_project(args) -> int:
    project = selected_project()
    if project is None:
        raise CliError("Нет активного проекта. Выберите его командой use или создайте командой new.")
    diagnostics = []

    def error(path, line, message):
        diagnostics.append(("ОШИБКА", path, line, message))

    def warning(path, line, message):
        diagnostics.append(("ПРЕДУПРЕЖДЕНИЕ", path, line, message))

    rows = {}
    for name in REGISTRIES:
        path = project / f"{name}.jsonl"
        if name in ("journal", "costs"):
            rows[name] = checked_rows(path, SCHEMAS[name], warning)
        elif path.is_file():
            rows[name] = checked_rows(path, SCHEMAS[name], error)
        else:
            error(path, None, "ожидается файл" if path.exists() else "файл не найден")
            rows[name] = []
    can_render = not any(severity == "ОШИБКА" for severity, *_ in diagnostics)
    state_file = project / "state.json"
    if state_file.is_file():
        try:
            read_state(state_file)
        except CliError as exc:
            diagnostics.append(("ОШИБКА", None, None, str(exc)))
            can_render = False
    else:
        error(state_file, None, "ожидается файл" if state_file.exists() else "файл не найден")
        can_render = False
    sources = {row["id"]: row for _, row in rows["sources"]}
    evidence = {row["id"]: row for _, row in rows["evidence"]}
    used = check_evidence(project / "evidence.jsonl", rows["evidence"], sources, error)
    used.update(check_outputs(project, sources, evidence, error, warning))
    for line, row in rows["sources"]:
        if row["id"] not in used:
            warning(project / "sources.jsonl", line, f"на источник {row['id']} нет ссылок")
    today = date.today().isoformat()
    for line, row in rows["decisions"]:
        for identifier in dict.fromkeys(row["based_on"]):
            if identifier not in evidence:
                error(project / "decisions.jsonl", line, f"основание {identifier} не существует в evidence.jsonl")
        if past_review(row, today):
            warning(project / "decisions.jsonl", line, f"просрочен пересмотр решения {row['id']} ({row['review_date']})")
    if can_render:
        render_registries(project, {name: [row for _, row in entries] for name, entries in rows.items()})
    for severity, path, line, message in diagnostics:
        if path is not None:
            location = path.relative_to(project).as_posix()
            if line is not None:
                location += f":{line}"
            message = f"{location} — {message}"
        print(f"{severity}: {message}")
    errors = sum(severity == "ОШИБКА" for severity, *_ in diagnostics)
    print(f"Итог: ошибок — {errors}, предупреждений — {len(diagnostics) - errors}.")
    return int(errors > 0)


def impact(args) -> None:
    project = require_project()
    if not re.fullmatch(REFERENCE_ID, args.id):
        raise CliError("Укажите идентификатор источника S-… или утверждения E-….")
    registry = "sources" if args.id.startswith("S-") else "evidence"
    find_record(records(project / f"{registry}.jsonl"), args.id)
    identifiers = {args.id}
    found = False
    if args.id.startswith("S-"):
        for row in records(project / "evidence.jsonl"):
            if args.id in row["sources"]:
                identifiers.add(row["id"])
                print(f"Утверждение {row['id']}: {row['text']}")
                found = True
    for path in output_files(project):
        for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            if identifiers.intersection(REFERENCE_MENTION.findall(line)):
                print(f"{path.relative_to(project).as_posix()}:{number}: {clip(line.strip(), 160)}")
                found = True
    for row in records(project / "decisions.jsonl"):
        if identifiers.intersection(row["based_on"]):
            print(f"Решение {row['id']}: {row['decision']}")
            found = True
    if not found:
        print("Зависимости не найдены.")


def add_decision(args) -> None:
    path = require_project() / "decisions.jsonl"
    with file_lock(path):
        identifier = next_id(records(path), "D")
        append_unlocked(path, {
            "id": identifier, "date": date.today().isoformat(), "decision": args.decision,
            "owner": args.owner, "metric": args.metric, "review_condition": args.review_condition,
            "review_date": args.review_date, "based_on": csv_items(args.based_on), "status": "active",
        })
    print(identifier)


def list_decisions(args) -> None:
    rows = records(require_project() / "decisions.jsonl")
    if not rows:
        print("Решений пока нет.")
        return
    print(markdown_table(
        ("ID", "Дата", "Решение", "Ответственный", "Метрика", "Условие пересмотра", "Дата пересмотра", "Основания", "Статус"),
        (
            (row["id"], row["date"], row["decision"], row["owner"], row["metric"], row["review_condition"],
             row["review_date"], ", ".join(row["based_on"]), row["status"])
            for row in rows
        ),
    ))


def due_decisions(args) -> None:
    project = require_project()
    revoked = {row["id"] for row in records(project / "evidence.jsonl") if row["status"] == "revoked"}
    today = date.today().isoformat()
    found = False
    for row in records(project / "decisions.jsonl"):
        if row["status"] != "active":
            continue
        reasons = []
        if row["review_date"] and row["review_date"] <= today:
            reasons.append(f"наступила дата пересмотра {row['review_date']}")
        revoked_refs = sorted(revoked.intersection(row["based_on"]))
        if revoked_refs:
            reasons.append(f"отозваны утверждения {', '.join(revoked_refs)}")
        if reasons:
            print(f"{row['id']} | {row['decision']} | {', '.join(reasons)}")
            found = True
    if not found:
        print("Решений для пересмотра нет.")


def show_journal(args) -> None:
    problems: list = []
    rows = tolerant_records(require_project() / "journal.jsonl", problems)
    for problem in problems:
        print(f"ПРЕДУПРЕЖДЕНИЕ: пропущена повреждённая строка журнала: {problem}", file=sys.stderr)
    for row in (rows[-args.tail:] if args.tail else []):
        fields = (row[key] for key in ("ts", "session", "event", "tool", "target", "note"))
        print(" | ".join(field for field in fields if field))


def log_event(args) -> None:
    append_journal(require_project(), {"event": args.event, "tool": "log", "note": args.note})
    print("Событие записано.")


def print_cost(args) -> None:
    rows = cost_rows(require_project() / "costs.jsonl")
    print(markdown_table(
        ("Сеанс", "Метка", "Источник", "USD", "Минуты"),
        ((row["session"], row["label"], row["source"], f"{row['cost_usd']:.6f}",
          f"{row['duration_s'] / 60:.2f}") for row in rows),
    ))
    print(f"Итого: {cost_summary(*cost_totals(rows))}.")


def add_cost(args) -> None:
    project = require_project()
    session = args.session if args.session is not None else str(uuid4())
    upsert_cost(project, {
        "ts": now(), "session": session, "source": args.source, "label": args.label,
        "duration_s": args.duration_s, "cost_usd": args.usd, "models": {},
    })
    print(f"Расходы записаны для сеанса {session}.")


def import_cost(args) -> None:
    project = require_project()
    result = read_object(args.file)
    if result.get("is_error") is True and not args.force:
        raise CliError(f"Файл {args.file} содержит результат с ошибкой. Для импорта укажите --force.")
    session = result.get("session_id")
    amount = result.get("total_cost_usd")
    duration = result.get("duration_ms")
    usage = result.get("modelUsage", {})
    if not isinstance(session, str) or not session.strip():
        raise CliError("В файле импорта требуется строка session_id.")
    if not is_amount(amount) or not is_amount(duration):
        raise CliError("Поля total_cost_usd и duration_ms должны содержать неотрицательные числа.")
    if not isinstance(usage, dict) or not all(isinstance(value, dict) for value in usage.values()):
        raise CliError("Поле modelUsage должно содержать объекты расходов по моделям.")
    models = {
        model: {target: values.get(source, 0) for source, target in MODEL_FIELDS.items()}
        for model, values in usage.items()
    }
    if not valid_models(models):
        raise CliError("Некорректные значения расходов или числа токенов в modelUsage.")
    upsert_cost(project, {
        "ts": now(), "session": session, "source": "headless", "label": args.label,
        "duration_s": duration / 1000, "cost_usd": amount, "models": models,
    })
    print(f"Расходы импортированы для сеанса {session}.")


def memory_path() -> Path:
    return find_root() / "memory" / "notes.jsonl"


def add_memory(args) -> None:
    path = memory_path()
    path.parent.mkdir(exist_ok=True)
    with file_lock(path):
        identifier = next_id(records(path), "M")
        append_unlocked(path, {
            "id": identifier, "date": date.today().isoformat(), "kind": args.kind,
            "text": args.text, "origin": args.origin, "status": "active", "revoked_reason": "",
        })
    print(identifier)


def revoke_memory(args) -> None:
    path = memory_path()
    with file_lock(path):
        rows = records(path)
        record = find_record(rows, args.id)
        record.update(status="revoked", revoked_reason=args.reason)
        write_records(path, rows)
    print(f"Заметка {args.id} отозвана.")


def list_memory(args) -> None:
    rows = records(memory_path())
    if not rows:
        print("Заметок пока нет.")
        return
    for row in rows:
        fields = [row[key] for key in ("id", "date", "kind", "text", "origin", "status", "revoked_reason")]
        print(" | ".join(field for field in fields if field))


def word_prefixes(text: str) -> set[str]:
    return {match[0].casefold()[:5] for match in WORD.finditer(text)}


def search_entries(root: Path):
    for path in sorted((root / "knowledge").glob("*.md")):
        if path.is_file():
            for paragraph in paragraphs(path.read_text(encoding="utf-8-sig").splitlines()):
                yield "знания", path.relative_to(root).as_posix(), " ".join(line for _, line in paragraph)
    for row in records(root / "memory" / "notes.jsonl"):
        if row["status"] == "active":
            yield "память (заметка агента, не факт)", row["id"], row["text"]
    project = active_project()
    if project is not None:
        for row in records(project / "evidence.jsonl"):
            if row["status"] != "revoked":
                yield "утверждение", row["id"], row["text"]


def search(args) -> None:
    root = find_root()
    query = word_prefixes(args.query)
    matches = []
    for kind, location, text in search_entries(root):
        score = len(query & word_prefixes(text))
        if score:
            normalized = " ".join(text.split())
            first = next(match.start() for match in WORD.finditer(normalized) if match[0].casefold()[:5] in query)
            start = max(0, first - 60) if first >= 200 else 0
            fragment = clip(("…" if start else "") + normalized[start:], 240)
            matches.append((score, kind, location, fragment))
    matches.sort(key=lambda item: item[0], reverse=True)
    for _, kind, location, fragment in matches[:10]:
        print(f"{kind} | {location} | {fragment}")
    if not matches:
        print("Совпадений нет.")


class RussianParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, add_help=False, **kwargs)
        self._positionals.title = "Позиционные аргументы"
        self._optionals.title = "Параметры"
        self.add_argument("-h", "--help", action="help", help="показать справку и выйти")

    def format_usage(self):
        return super().format_usage().replace("usage: ", "Использование: ", 1)

    def format_help(self):
        return super().format_help().replace("usage: ", "Использование: ", 1)

    def error(self, message):
        required = "the following arguments are required: "
        unknown = "unrecognized arguments: "
        if message.startswith(required):
            message = "Обязательные аргументы: " + message[len(required):]
        elif message.startswith(unknown):
            message = "Неизвестные аргументы: " + message[len(unknown):]
        elif message.startswith("argument "):
            name, _, details = message[len("argument "):].partition(": ")
            if details.startswith("invalid choice: "):
                value, _, choices = details[len("invalid choice: "):].partition(" (choose from ")
                message = f"Недопустимое значение {value} для {name}. Допустимо: {choices.removesuffix(')')}."
            elif details.startswith("expected "):
                message = f"Для аргумента {name} требуется значение."
            else:
                message = f"Неверное значение аргумента {name}. {details}"
        else:
            message = "Неверный вызов. Список команд и параметров доступен через --help."
        self.print_usage(sys.stderr)
        self.exit(2, f"ОШИБКА: {message}\n")


def nonnegative_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        number = -1
    if number < 0:
        raise argparse.ArgumentTypeError("Укажите целое неотрицательное число.")
    return number


def nonnegative_number(value: str) -> float:
    try:
        number = float(value)
    except ValueError:
        number = -1
    if not is_amount(number):
        raise argparse.ArgumentTypeError("Укажите конечное неотрицательное число.")
    return number


def review_date(value: str) -> str:
    if value and not is_date(value):
        raise argparse.ArgumentTypeError("Укажите дату в формате ГГГГ-ММ-ДД.")
    return value


def command(parsers, name, description, handler=None):
    parser = parsers.add_parser(name, help=description, description=description)
    if handler is not None:
        parser.set_defaults(handler=handler)
    return parser


def subcommands(parser):
    return parser.add_subparsers(title="Команды", metavar="команда", required=True)


def make_parser():
    parser = RussianParser(prog="strateg.py", description="Управление проектами Стратега.")
    commands = subcommands(parser)

    new = command(commands, "new", "Создать проект и сделать его активным.", new_project)
    new.add_argument("id", metavar="идентификатор")
    new.add_argument("--title", required=True, metavar="название")
    use = command(commands, "use", "Сделать проект активным.", use_project)
    use.add_argument("id", metavar="идентификатор")
    command(commands, "projects", "Показать проекты и их текущие шаги.", list_projects)
    status = command(commands, "status", "Показать состояние проекта и обновить STATUS.md.", show_status)
    status.add_argument("--json", action="store_true", help="вывести данные в формате JSON")

    step = command(commands, "step", "Изменить статус шага.", change_step)
    step.add_argument("step_id", metavar="шаг")
    step.add_argument("action", choices=("start", "done", "block"))
    step.add_argument("--note", metavar="заметка")
    step.add_argument("--outputs", metavar="файл,файл")
    step.add_argument("--redo", action="store_true", help="разрешить повторный запуск выполненного шага")

    gate = subcommands(command(commands, "gate", "Записать вопрос человеку или его ответ."))
    ask = command(gate, "ask", "Записать вопрос.", ask_gate)
    ask.add_argument("question", metavar="вопрос")
    ask.add_argument("--options", default="", metavar="А|Б|В")
    ask.add_argument("--step", metavar="шаг")
    answer = command(gate, "answer", "Записать ответ.", answer_gate)
    answer.add_argument("answer", metavar="ответ")

    source = subcommands(command(commands, "source", "Работать с источниками."))
    add = command(source, "add", "Добавить источник.", add_source)
    add.add_argument("--type", choices=SOURCE_TYPES, required=True)
    add.add_argument("--title", required=True, metavar="название")
    add.add_argument("--ref", required=True, metavar="ссылка")
    add.add_argument("--publisher", default="", metavar="издатель")
    add.add_argument("--published", default="", metavar="дата")
    add.add_argument("--reliability", choices=RELIABILITIES, default="B")
    add.add_argument("--note", default="", metavar="заметка")

    evidence = subcommands(command(commands, "evidence", "Работать с утверждениями."))
    add = command(evidence, "add", "Добавить утверждение.", add_evidence)
    add.add_argument("--kind", choices=EVIDENCE_KINDS, required=True)
    add.add_argument("--text", required=True, metavar="текст")
    add.add_argument("--sources", required=True, metavar="S-001,S-002")
    add.add_argument("--confidence", choices=CONFIDENCES, default="medium")
    add.add_argument("--note", default="", metavar="заметка")
    revoke = command(commands, "revoke", "Отозвать утверждение.", revoke_evidence)
    revoke.add_argument("id", metavar="E-001")
    revoke.add_argument("--reason", required=True, metavar="причина")
    command(commands, "check", "Проверить проект и обновить представления Markdown.", check_project)
    impact_parser = command(commands, "impact", "Показать зависимости от источника или утверждения.", impact)
    impact_parser.add_argument("id", metavar="S-001|E-001")

    decisions = subcommands(command(commands, "decisions", "Работать с решениями."))
    add = command(decisions, "add", "Добавить решение.", add_decision)
    add.add_argument("--decision", required=True, metavar="решение")
    add.add_argument("--owner", required=True, metavar="ответственный")
    add.add_argument("--metric", required=True, metavar="метрика")
    add.add_argument("--review-condition", required=True, metavar="условие")
    add.add_argument("--review-date", default="", type=review_date, metavar="дата")
    add.add_argument("--based-on", default="", metavar="E-001,E-002")
    command(decisions, "list", "Показать решения.", list_decisions)
    command(decisions, "due", "Показать решения, требующие пересмотра.", due_decisions)

    journal = command(commands, "journal", "Показать последние события.", show_journal)
    journal.add_argument("--tail", default=30, type=nonnegative_int, metavar="число")
    log = command(commands, "log", "Добавить событие вручную.", log_event)
    log.add_argument("event", choices=EVENTS)
    log.add_argument("note", metavar="заметка")

    cost = command(commands, "cost", "Показать или записать расходы по сеансам.", print_cost)
    cost_commands = cost.add_subparsers(title="Команды", metavar="команда")
    add = command(cost_commands, "add", "Записать расходы вручную.", add_cost)
    add.add_argument("--label", required=True, metavar="метка")
    add.add_argument("--usd", required=True, type=nonnegative_number, metavar="сумма")
    add.add_argument("--duration-s", required=True, type=nonnegative_number, metavar="секунды")
    add.add_argument("--session", metavar="сеанс")
    add.add_argument("--source", choices=COST_SOURCES, default="manual")
    importer = command(cost_commands, "import", "Импортировать расходы из результата Claude.", import_cost)
    importer.add_argument("file", type=Path, metavar="файл.json")
    importer.add_argument("--label", default="", metavar="метка")
    importer.add_argument("--force", action="store_true", help="импортировать результат с ошибкой")

    memory = subcommands(command(commands, "memory", "Работать с заметками между проектами."))
    add = command(memory, "add", "Добавить заметку.", add_memory)
    add.add_argument("--kind", choices=MEMORY_KINDS, required=True)
    add.add_argument("--text", required=True, metavar="текст")
    add.add_argument("--origin", default="", metavar="источник")
    revoke = command(memory, "revoke", "Отозвать заметку.", revoke_memory)
    revoke.add_argument("id", metavar="M-001")
    revoke.add_argument("--reason", required=True, metavar="причина")
    command(memory, "list", "Показать заметки.", list_memory)
    query = command(commands, "search", "Поискать по знаниям, памяти и утверждениям.", search)
    query.add_argument("query", metavar="запрос")
    return parser


def main(argv=None) -> int:
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    args = make_parser().parse_args(argv)
    try:
        return args.handler(args) or 0
    except CliError as exc:
        message = str(exc)
    except FileExistsError as exc:
        message = f"Файл или каталог уже существует: {exc.filename}."
    except FileNotFoundError as exc:
        message = f"Файл или каталог не найден: {exc.filename}."
    except OSError as exc:
        message = f"Ошибка доступа к файлу или каталогу: {exc.filename or 'путь не указан'} (код {exc.errno})."
    except UnicodeError:
        message = "Для файлов и вывода требуется корректный текст в UTF-8."
    except (KeyError, TypeError, ValueError, OverflowError):
        message = "Некорректная структура данных. Для проверки реестров запустите check."
    print(f"ОШИБКА: {message}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
