"""Снимки реального вывода команд для описания работы.

Запускает команды в корне репозитория, вставляет их настоящий вывод в окно «терминала» (HTML)
и снимает PNG через Playwright. Ничего не рисуется вручную: что напечатала команда, то и на снимке.

Запуск: python docs/build/shots.py
Нужен пакет playwright с установленным Chromium (только для сборки описания; агенту он не нужен).
"""
import html
import subprocess
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "img"

PAGE = """<!doctype html><html><head><meta charset="utf-8"><style>
body{{margin:0;padding:18px;background:#e9ecef;font-family:'Segoe UI',Arial,sans-serif}}
.win{{width:{width}px;border-radius:8px;overflow:hidden;box-shadow:0 4px 18px rgba(0,0,0,.25)}}
.bar{{background:#2b2f36;color:#c9d1d9;font-size:13px;padding:8px 14px}}
pre{{margin:0;background:#161b22;color:#e6edf3;font:13px/1.45 'Cascadia Mono',Consolas,'Courier New',monospace;
padding:14px 16px;white-space:pre-wrap;word-break:break-word}}
.cmd{{color:#7ee787}}
</style></head><body><div class="win" id="win"><div class="bar">{title}</div><pre>{body}</pre></div></body></html>"""


def run(command: list[str], limit: int | None = None) -> str:
    result = subprocess.run(command, cwd=ROOT, capture_output=True)
    text = (result.stdout + result.stderr).decode("utf-8", "replace").rstrip()
    lines = text.splitlines()
    if limit and len(lines) > limit:
        lines = lines[:limit] + [f"… (ещё {len(lines) - limit} строк)"]
    return "\n".join(lines)


def shot(page, name: str, title: str, blocks: list[tuple[str, str]], width: int = 1040) -> None:
    body = "\n\n".join(f'<span class="cmd">$ {html.escape(cmd)}</span>\n{html.escape(out)}' for cmd, out in blocks)
    page.set_content(PAGE.format(width=width, title=html.escape(title), body=body))
    page.locator("#win").screenshot(path=str(OUT / f"{name}.png"))
    print("снимок:", name)


def text_shot(page, name: str, title: str, text: str, width: int = 1040) -> None:
    page.set_content(PAGE.format(width=width, title=html.escape(title), body=html.escape(text)))
    page.locator("#win").screenshot(path=str(OUT / f"{name}.png"))
    print("снимок:", name)


def head(path: Path, count: int) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    more = [f"… (ещё {len(lines) - count} строк)"] if len(lines) > count else []
    return "\n".join(lines[:count] + more)


def main() -> None:
    from playwright.sync_api import sync_playwright

    OUT.mkdir(parents=True, exist_ok=True)
    py = sys.executable
    cli = [py, "tools/strateg.py"]
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1120, "height": 800}, device_scale_factor=2)
        shot(page, "01-tests", "Проверка установки: тесты CLI и хуков",
             [("python -m unittest discover -s tools/tests -v",
               run([py, "-m", "unittest", "discover", "-s", "tools/tests", "-v"]))])
        shot(page, "02-status", "Состояние проекта: шаги, решение человека, расходы",
             [("python tools/strateg.py status", run(cli + ["status"]))])
        shot(page, "03-journal", "Журнал: что агент делал",
             [("python tools/strateg.py journal --tail 28", run(cli + ["journal", "--tail", "28"]))], width=1100)
        shot(page, "04-check", "Проверка ссылок на источники",
             [("python tools/strateg.py check", run(cli + ["check"], limit=28))])
        shot(page, "05-cost", "Время и стоимость по сеансам",
             [("python tools/strateg.py cost", run(cli + ["cost"]))])
        shot(page, "06-decisions", "Журнал решений и что пора пересмотреть",
             [("python tools/strateg.py decisions list", run(cli + ["decisions", "list"], limit=18)),
              ("python tools/strateg.py decisions due", run(cli + ["decisions", "due"], limit=14))])
        shot(page, "07-search", "Поиск по методикам, памяти и утверждениям",
             [("python tools/strateg.py search \"удержание оплаченные месяцы\"",
               run(cli + ["search", "удержание оплаченные месяцы"], limit=16))])
        tree = run(["git", "ls-files", "--", ".claude", "AGENTS.md", "CLAUDE.md", "knowledge", "tools", "memory"])
        text_shot(page, "08-tree", "Состав агента: инструкции, процедуры, субагенты, знания, инструменты", tree, width=760)
        for name, title, path, count in [
            ("09-agents-md", "AGENTS.md — постоянные правила (начало)", ROOT / "AGENTS.md", 34),
            ("10-skill-research", ".claude/skills/research/SKILL.md — процедура шага", ROOT / ".claude/skills/research/SKILL.md", 40),
            ("11-agent-researcher", ".claude/agents/researcher.md — субагент", ROOT / ".claude/agents/researcher.md", 36),
        ]:
            text_shot(page, name, title, head(path, count))
        browser.close()


if __name__ == "__main__":
    main()
