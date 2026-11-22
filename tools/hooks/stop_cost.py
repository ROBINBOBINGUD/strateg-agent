"""Stop и PreToolUse(Bash): сохраняет токены, оценку стоимости и длительность сеанса в costs.jsonl проекта.

При остановке — всегда; перед командами `strateg.py cost` и `strateg.py status` — чтобы отчёт агента
о расходах включал текущий сеанс, а не только завершённые.

Источник — транскрипт сеанса Claude Code (путь приходит в событии). Сообщения считаются по одному разу
(по id), учитываются и транскрипты субагентов, если они лежат рядом. Стоимость — оценка по tools/prices.json;
точную сумму даёт `claude -p --output-format json` (команда `strateg.py cost import`).
"""
import json
from datetime import datetime
from pathlib import Path

from _common import TOOLS_DIR, active_project, read_event, strateg


def load_prices() -> dict:
    try:
        return json.loads((TOOLS_DIR / "prices.json").read_text(encoding="utf-8")).get("models", {})
    except Exception:
        return {}


def price_for(model: str, prices: dict):
    best = None
    for prefix, price in prices.items():
        if model.startswith(prefix) and (best is None or len(prefix) > len(best[0])):
            best = (prefix, price)
    return best[1] if best else None


def collect(paths) -> tuple:
    seen = {}
    first = last = None
    for path in paths:
        try:
            handle = path.open(encoding="utf-8", errors="replace")
        except OSError:
            continue
        with handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                stamp = row.get("timestamp")
                if stamp:
                    first = first or stamp
                    last = stamp
                message = row.get("message") or {}
                usage = message.get("usage")
                if not usage or message.get("role") != "assistant":
                    continue
                key = message.get("id") or row.get("uuid")
                seen[key] = (message.get("model", "unknown"), usage)
    return seen, first, last


def main() -> None:
    event = read_event()
    if event.get("hook_event_name") == "PreToolUse":
        # Перед командами cost и status обновляем запись текущего сеанса, чтобы агент видел живые числа.
        command = str((event.get("tool_input") or {}).get("command", ""))
        if "strateg.py cost" not in command and "strateg.py status" not in command:
            return
    project = active_project()
    module = strateg()
    transcript = event.get("transcript_path")
    if project is None or module is None or not transcript:
        return
    main_path = Path(transcript)
    side_dir = main_path.with_suffix("")
    paths = [main_path] + sorted(side_dir.glob("**/*.jsonl")) if side_dir.is_dir() else [main_path]
    seen, first, last = collect(paths)
    if not seen:
        return
    prices = load_prices()
    models = {}
    for model, usage in seen.values():
        if model.startswith("<"):
            continue
        entry = models.setdefault(model, {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "cost_usd": 0.0})
        entry["input"] += usage.get("input_tokens", 0) or 0
        entry["output"] += usage.get("output_tokens", 0) or 0
        entry["cache_read"] += usage.get("cache_read_input_tokens", 0) or 0
        entry["cache_write"] += usage.get("cache_creation_input_tokens", 0) or 0
    total = 0.0
    priced = True
    for model, entry in models.items():
        price = price_for(model, prices)
        if price is None:
            priced = False
            continue
        cost = (entry["input"] * price["input"] + entry["output"] * price["output"]
                + entry["cache_read"] * price["cache_read"] + entry["cache_write"] * price["cache_write"]) / 1_000_000
        entry["cost_usd"] = round(cost, 4)
        total += cost
    duration = 0
    try:
        start = datetime.fromisoformat(first.replace("Z", "+00:00"))
        end = datetime.fromisoformat(last.replace("Z", "+00:00"))
        duration = int((end - start).total_seconds())
    except Exception:
        pass
    module.upsert_cost(project, {
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "session": event.get("session_id", main_path.stem),
        "source": "stop-hook",
        "label": "сеанс Claude Code (оценка по токенам)" + ("" if priced else "; для части моделей нет цены"),
        "duration_s": duration,
        "cost_usd": round(total, 4),
        "models": models,
    })


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
