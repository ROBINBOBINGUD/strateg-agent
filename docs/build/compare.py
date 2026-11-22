"""Числа для сравнения «обычный чат» против агента на одном брифе.

Обычный чат: один запрос к той же сильной модели без репозитория (runs/baseline-chat.json, текст — runs/baseline-chat.md).
Агент: проект в projects/<id>/. Скрипт только считает; оценочные строки сравнения пишет человек.

Запуск: python docs/build/compare.py [id проекта]
"""
import json
import re
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]


def rows(path: Path) -> list[dict]:
    out = []
    if path.exists():
        for line in path.read_bytes().splitlines():
            try:
                out.append(json.loads(line.decode("utf-8")))
            except Exception:
                pass
    return out


def words(text: str) -> int:
    return len(re.findall(r"\w+", text))


def main() -> None:
    project_id = sys.argv[1] if len(sys.argv) > 1 else (ROOT / "projects" / "ACTIVE").read_text(encoding="utf-8").strip()
    project = ROOT / "projects" / project_id
    base_json = json.loads((ROOT / "runs" / "baseline-chat.json").read_text(encoding="utf-8"))
    base = base_json.get("result", "")
    final = (project / "outputs" / "STRATEGIYA.md")
    final_text = final.read_text(encoding="utf-8") if final.exists() else ""
    outputs_text = "\n".join(p.read_text(encoding="utf-8") for p in sorted((project / "outputs").glob("*.md")))
    sources = rows(project / "sources.jsonl")
    evidence = rows(project / "evidence.jsonl")
    costs = rows(project / "costs.jsonl")
    cited = set(re.findall(r"[ES]-\d{3}", final_text))
    kinds = {}
    for item in evidence:
        kinds[item.get("kind")] = kinds.get(item.get("kind"), 0) + 1
    types = {}
    for item in sources:
        types[item.get("type")] = types.get(item.get("type"), 0) + 1
    report = {
        "обычный чат": {
            "слов": words(base),
            "ссылок на внешние источники (URL)": len(re.findall(r"https?://", base)),
            "ссылок на реестр [E-…]/[S-…]": 0,
            "упоминаний «гипотез»": len(re.findall(r"(?i)гипотез", base)),
            "упоминаний «допущен»": len(re.findall(r"(?i)допущен", base)),
            "время, мин": round(base_json.get("duration_ms", 0) / 60000, 1),
            "стоимость, USD": round(base_json.get("total_cost_usd", 0), 2),
            "ходов модели": base_json.get("num_turns"),
        },
        "агент": {
            "слов в итоговом документе": words(final_text),
            "слов во всех результатах": words(outputs_text),
            "источников в реестре": len(sources),
            "источников по типам": types,
            "из них внешних сайтов": types.get("site", 0),
            "утверждений в реестре": len(evidence),
            "утверждений по видам": kinds,
            "ссылок на реестр в итоговом документе": len(re.findall(r"[ES]-\d{3}", final_text)),
            "разных утверждений и источников, на которые ссылается итог": len(cited),
            "расчётных скриптов": len(list((project / "analysis").glob("*.py"))),
            "время, мин": round(sum(c.get("duration_s", 0) for c in costs) / 60, 1),
            "стоимость, USD": round(sum(c.get("cost_usd", 0) for c in costs), 2),
            "сеансов": len(costs),
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
