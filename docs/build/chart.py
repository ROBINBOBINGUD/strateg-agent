"""График для описания: стоимость и время заходов демонстрационного проекта по моделям.

Одна ось (USD), время подписано текстом у конца строки. Цвета — три первых слота категориальной палитры
в фиксированном порядке (синий, оранжевый, аква), проверены валидатором палитры на различимость.
График статичный, для PDF: значения продублированы таблицей в тексте описания.

Запуск: python docs/build/chart.py   ->  docs/img/rashody.svg
"""
import json
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
SERIES = [("claude-opus-5-5", "Opus 5.5 — основной агент и критик", "#2a78d6"),
          ("claude-sonnet-5-5", "Sonnet 5.5 — исследователи и аналитик", "#eb6834"),
          ("claude-haiku-5-5", "Haiku 5.5 — веб-инструменты и респонденты", "#1baf7a")]
NAMES = {
    "zahod-1-postanovka": "1. Постановка",
    "zahod-2-issledovanie-varianty": "2. Сбор, исследование, варианты",
    "zahod-3-strategii-sborka": "3. Стратегии, план проверки, сборка",
    "zahod-4-priemka": "4. Приёмка и журнал решений",
}
INK, MUTED, GRID, SURFACE = "#1c2128", "#57606a", "#e3e7eb", "#ffffff"


def num(value: float, digits: int = 2) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def main() -> None:
    runs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((ROOT / "runs").glob("zahod-*.json"))]
    if not runs:
        raise SystemExit("нет сводок заходов в runs/")
    width, left, right, top, row, bar = 1000, 300, 190, 64, 46, 22
    plot = width - left - right
    peak = max(r["cost_usd"] for r in runs)
    step = 1 if peak <= 6 else 2
    axis_max = (int(peak / step) + 1) * step
    scale = plot / axis_max
    height = top + row * len(runs) + 78
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
           f'font-family="\'Segoe UI\', \'Noto Sans\', Arial, sans-serif" font-size="13" fill="{INK}">',
           f'<rect width="{width}" height="{height}" fill="{SURFACE}"/>',
           f'<text x="20" y="26" font-size="15" font-weight="600">Стоимость заходов по моделям, USD в ценах API</text>',
           f'<text x="20" y="45" fill="{MUTED}" font-size="12">У конца строки — сумма и время захода</text>']
    base = top + row * len(runs)
    for tick in range(0, axis_max + 1, step):
        x = left + tick * scale
        out.append(f'<line x1="{x:.1f}" y1="{top - 6}" x2="{x:.1f}" y2="{base}" stroke="{GRID}" stroke-width="1"/>')
        out.append(f'<text x="{x:.1f}" y="{base + 18}" text-anchor="middle" fill="{MUTED}" font-size="12">{tick}</text>')
    for index, run in enumerate(runs):
        y = top + index * row + (row - bar) / 2
        label = NAMES.get(run["label"], run["label"])
        out.append(f'<text x="{left - 12}" y="{y + bar / 2 + 4.5:.1f}" text-anchor="end">{label}</text>')
        x = float(left)
        parts = [(color, run["models"].get(model, {}).get("cost_usd", 0.0)) for model, _, color in SERIES]
        parts = [(color, value) for color, value in parts if value > 0]
        for position, (color, value) in enumerate(parts):
            w = value * scale
            last = position == len(parts) - 1
            gap = 0 if last else 2          # зазор цвета поверхности между сегментами
            w_draw = max(w - gap, 1.0)
            if last:                        # скругление только у свободного конца строки
                r = min(4.0, w_draw / 2)
                out.append(f'<path d="M{x:.1f} {y:.1f} h{w_draw - r:.1f} a{r} {r} 0 0 1 {r} {r} v{bar - 2 * r:.1f} '
                           f'a{r} {r} 0 0 1 -{r} {r} h-{w_draw - r:.1f} z" fill="{color}"/>')
            else:
                out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w_draw:.1f}" height="{bar}" fill="{color}"/>')
            x += w
        out.append(f'<text x="{x + 10:.1f}" y="{y + bar / 2 + 4.5:.1f}">{num(run["cost_usd"])} USD · '
                   f'{num(run["duration_min"], 1)} мин</text>')
    out.append(f'<line x1="{left}" y1="{top - 6}" x2="{left}" y2="{base}" stroke="#8c959f" stroke-width="1"/>')
    lx = 20
    for _, name, color in SERIES:
        out.append(f'<rect x="{lx}" y="{base + 40}" width="12" height="12" rx="2" fill="{color}"/>')
        out.append(f'<text x="{lx + 18}" y="{base + 51}" fill="{MUTED}" font-size="12.5">{name}</text>')
        lx += 30 + len(name) * 7.1
    out.append("</svg>")
    target = ROOT / "docs" / "img" / "rashody.svg"
    target.write_text("\n".join(out), encoding="utf-8")
    print("готово:", target, "| заходов:", len(runs), "| максимум оси:", axis_max)


if __name__ == "__main__":
    main()
