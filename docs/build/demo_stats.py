"""Таблицы времени, стоимости и состава демонстрационного проекта для описания работы.

Числа берутся из сводок заходов runs/*.json и реестров проекта, руками не вводятся.
Запуск: python docs/build/demo_stats.py [id проекта]
"""
import json
import re
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
SHORT = {"claude-opus-5-5": "Opus 5.5", "claude-sonnet-5-5": "Sonnet 5.5", "claude-haiku-5-5": "Haiku 5.5",
         "claude-fable-5-2": "Fable 5.2"}


def rows(path: Path) -> list[dict]:
    out = []
    if path.exists():
        for line in path.read_bytes().splitlines():
            try:
                out.append(json.loads(line.decode("utf-8")))
            except Exception:
                pass
    return out


def num(value: float, digits: int = 2) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def main() -> None:
    project_id = sys.argv[1] if len(sys.argv) > 1 else (ROOT / "projects" / "ACTIVE").read_text(encoding="utf-8").strip()
    project = ROOT / "projects" / project_id
    runs = sorted((ROOT / "runs").glob("zahod-*.json"))
    total_min = total_usd = 0.0
    by_model: dict[str, float] = {}
    print("| Заход | Время, мин | Стоимость, USD | Ходов | Отказов в разрешениях |")
    print("|---|---|---|---|---|")
    for path in runs:
        data = json.loads(path.read_text(encoding="utf-8"))
        total_min += data["duration_min"]
        total_usd += data["cost_usd"]
        for model, usage in data["models"].items():
            by_model[model] = by_model.get(model, 0.0) + usage["cost_usd"]
        print(f"| `{data['label']}` | {num(data['duration_min'], 1)} | {num(data['cost_usd'])} | {data['turns']} | "
              f"{len(data['permission_denials'])} |")
    print(f"| **Итого** | **{num(total_min, 1)}** | **{num(total_usd)}** | | |")
    print()
    print("| Модель | Стоимость, USD | Доля |")
    print("|---|---|---|")
    for model, cost in sorted(by_model.items(), key=lambda item: -item[1]):
        share = cost / total_usd * 100 if total_usd else 0
        print(f"| {SHORT.get(model, model)} | {num(cost)} | {num(share, 0)} % |")
    print()
    sources = rows(project / "sources.jsonl")
    evidence = rows(project / "evidence.jsonl")
    decisions = rows(project / "decisions.jsonl")
    journal = rows(project / "journal.jsonl")
    types: dict[str, int] = {}
    for item in sources:
        types[item.get("type", "?")] = types.get(item.get("type", "?"), 0) + 1
    kinds: dict[str, int] = {}
    revoked = 0
    for item in evidence:
        kinds[item.get("kind", "?")] = kinds.get(item.get("kind", "?"), 0) + 1
        revoked += item.get("status") == "revoked"
    tools: dict[str, int] = {}
    for item in journal:
        if item.get("event") == "tool":
            tools[item.get("tool", "?")] = tools.get(item.get("tool", "?"), 0) + 1
    final = project / "outputs" / "STRATEGIYA.md"
    text = final.read_text(encoding="utf-8") if final.exists() else ""
    print("Источников:", len(sources), types)
    print("Утверждений:", len(evidence), kinds, "отозвано:", revoked)
    print("Решений в журнале:", len(decisions))
    print("Действий в журнале:", sum(tools.values()), dict(sorted(tools.items(), key=lambda item: -item[1])))
    print("События:", {e: sum(1 for r in journal if r.get("event") == e) for e in ("gate", "error", "injection", "escalation")})
    print("Расчётных скриптов:", len(list((project / "analysis").glob("*.py"))))
    print("Итоговый документ: слов", len(re.findall(r"\w+", text)), "| ссылок на реестр", len(re.findall(r"[ES]-\d{3}", text)),
          "| разных", len(set(re.findall(r"[ES]-\d{3}", text))))


if __name__ == "__main__":
    main()
