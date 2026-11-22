"""Обезличенная сводка неинтерактивного захода.

Сырой ответ `claude -p --output-format json` лежит в runs/raw/ и в git не попадает: в нём есть
локальные пути и служебные идентификаторы. Сводка оставляет то, что нужно для проверки:
ответ агента, время, стоимость, токены по моделям, отказы в разрешениях.

Запуск: python runs/summarize.py <метка>
"""
import json
import re
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

RUNS = Path(__file__).resolve().parent
ROOT = RUNS.parent


def scrub(text: str) -> str:
    home = str(Path.home())
    for marker, raw in ((".", str(ROOT)), ("~", home)):
        for variant in {raw, raw.replace("\\", "/"), raw.replace("\\", "\\\\")}:
            text = re.sub(re.escape(variant), lambda _m: marker, text, flags=re.IGNORECASE)
    return text


def main() -> int:
    label = sys.argv[1]
    raw_path = RUNS / "raw" / f"{label}.json"
    try:
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(f"ОШИБКА: не удалось прочитать {raw_path.name}: {error}", file=sys.stderr)
        return 1
    usage = {}
    for model, item in (raw.get("modelUsage") or {}).items():
        usage[model] = {
            "input": item.get("inputTokens", 0),
            "output": item.get("outputTokens", 0),
            "cache_read": item.get("cacheReadInputTokens", 0),
            "cache_write": item.get("cacheCreationInputTokens", 0),
            "web_search": item.get("webSearchRequests", 0),
            "cost_usd": round(item.get("costUSD", 0.0), 4),
        }
    denials = []
    for item in raw.get("permission_denials") or []:
        tool_input = item.get("tool_input") or {}
        denials.append({"tool": item.get("tool_name", ""),
                        "what": scrub(str(tool_input.get("command") or tool_input.get("file_path") or ""))[:300]})
    summary = {
        "label": label,
        "is_error": bool(raw.get("is_error")),
        "duration_min": round(raw.get("duration_ms", 0) / 60000, 2),
        "turns": raw.get("num_turns"),
        "cost_usd": round(raw.get("total_cost_usd", 0.0), 4),
        "models": usage,
        "permission_denials": denials,
        "result": scrub(raw.get("result") or ""),
    }
    (RUNS / f"{label}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{label}: {summary['duration_min']} мин, {summary['cost_usd']} USD, ходов {summary['turns']}, "
          f"отказов в разрешениях {len(denials)}")
    return 1 if summary["is_error"] else 0


if __name__ == "__main__":
    sys.exit(main())
