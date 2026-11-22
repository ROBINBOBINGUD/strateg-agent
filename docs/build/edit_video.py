"""Монтаж записи работы агента в ролик до 10 минут.

Ничего не вырезается: моменты, где человек вводит запрос или принимает решение, идут в обычной
скорости, а периоды самостоятельной работы агента ускоряются и подписываются («×12 · Исследование»).
Границы берутся из журнала проекта (начало сеанса, вопрос человеку, ответ, смена шага), поэтому
монтаж воспроизводим.

Запуск: python docs/build/edit_video.py <запись.mkv> <время начала записи ISO> <id проекта> [выход.mp4]
Нужен ffmpeg 6+ в PATH.
"""
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
FONT = "C\\:/Windows/Fonts/segoeui.ttf" if sys.platform == "win32" else "DejaVuSans"
TARGET_SECONDS = 9 * 60 + 30
TITLE_SECONDS = 6
STEP_NAMES = {
    "intake": "Постановка задачи", "collect": "Сбор материалов", "research": "Исследование",
    "options": "Варианты", "product": "Продуктовая стратегия", "comms": "Коммуникационная стратегия",
    "testplan": "План проверки", "final": "Сборка и самопроверка", "support": "Поддержка решения",
}


def probe_duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True)
    return float(out.stdout.strip())


def journal(project: Path) -> list[dict]:
    rows = []
    for line in (project / "journal.jsonl").read_bytes().splitlines():
        try:
            rows.append(json.loads(line.decode("utf-8")))
        except Exception:
            continue
    return rows


def build_segments(rows: list[dict], start: datetime, duration: float) -> list[dict]:
    """Список отрезков: human (скорость 1) и work (ускоряется), с подписью текущего шага."""
    def offset(row: dict) -> float:
        return (datetime.fromisoformat(row["ts"]) - start).total_seconds()

    human = [(0.0, 45.0), (max(0.0, duration - 50.0), duration)]
    steps = []
    for row in rows:
        try:
            t = offset(row)
        except Exception:
            continue
        if not 0 <= t <= duration:
            continue
        if row.get("event") == "gate":
            human.append((t - 40, t + 12))          # вопрос агента на экране, ответ человека
        elif row.get("event") == "note" and row.get("tool") == "SessionStart":
            human.append((t - 25, t + 35))          # новый чат: запуск и первая реплика
        elif row.get("event") == "step":
            steps.append((t, str(row.get("tool") or row.get("target") or "")))
    human = sorted((max(0.0, a), min(duration, b)) for a, b in human if b > 0 and a < duration)
    merged = []
    for a, b in human:
        if merged and a <= merged[-1][1] + 4:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))

    def step_at(moment: float) -> str:
        current = ""
        for t, name in steps:
            if t <= moment:
                current = name
        return STEP_NAMES.get(current, current)

    segments, cursor = [], 0.0
    for a, b in merged:
        if a > cursor + 0.5:
            segments.append({"a": cursor, "b": a, "kind": "work", "step": step_at((cursor + a) / 2)})
        segments.append({"a": a, "b": b, "kind": "human", "step": step_at(a)})
        cursor = b
    if cursor < duration - 0.5:
        segments.append({"a": cursor, "b": duration, "kind": "work", "step": step_at(cursor)})
    return segments


def main() -> None:
    raw = Path(sys.argv[1])
    start = datetime.fromisoformat(sys.argv[2])
    project = ROOT / "projects" / sys.argv[3]
    target = Path(sys.argv[4]) if len(sys.argv) > 4 else ROOT / "docs" / "video" / "strateg-demo.mp4"
    duration = probe_duration(raw)
    segments = build_segments(journal(project), start, duration)
    human_total = sum(s["b"] - s["a"] for s in segments if s["kind"] == "human")
    work_total = sum(s["b"] - s["a"] for s in segments if s["kind"] == "work")
    budget = TARGET_SECONDS - 2 * TITLE_SECONDS - human_total
    speed = max(1.0, work_total / max(budget, 30.0))
    print(f"запись {duration / 60:.1f} мин; без ускорения {human_total / 60:.1f} мин; "
          f"работа агента {work_total / 60:.1f} мин ускоряется в {speed:.1f} раза")

    work_dir = target.parent / "_edit"
    work_dir.mkdir(parents=True, exist_ok=True)
    filters, labels = [], []

    def caption(index: int, text: str) -> str:
        path = work_dir / f"cap{index}.txt"
        path.write_text(text, encoding="utf-8")
        return str(path).replace("\\", "/").replace(":", "\\:")

    base = ("scale=1920:1080:force_original_aspect_ratio=decrease:flags=lanczos,"
            "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0x101418,setsar=1,fps=30")
    intro = caption(1000, "Стратег: агент руководителя продукта\nДемонстрационный проект по брифу МегаФона\n"
                          "Claude Code · Opus 5.5 ведёт, Sonnet 5.5 исследует и считает")
    outro = caption(1001, "Периоды самостоятельной работы агента ускорены и подписаны.\n"
                          "Ввод человека и ответы агента показаны без ускорения.\nРепозиторий: README.md")
    for name, text_file in (("intro", intro), ("outro", outro)):
        filters.append(f"color=c=0x101418:s=1920x1080:d={TITLE_SECONDS}:r=30,"
                       f"drawtext=fontfile='{FONT}':textfile='{text_file}':fontcolor=white:fontsize=46:"
                       f"line_spacing=22:x=(w-text_w)/2:y=(h-text_h)/2[{name}]")
    labels.append("[intro]")
    for index, seg in enumerate(segments):
        factor = speed if seg["kind"] == "work" else 1.0
        text = (f"×{factor:.0f} · {seg['step']}" if seg["kind"] == "work" else seg["step"]) or " "
        cap = caption(index, text)
        color = "0xffd166" if seg["kind"] == "work" else "0x9fb3c8"
        filters.append(
            f"[0:v]trim=start={seg['a']:.2f}:end={seg['b']:.2f},setpts=(PTS-STARTPTS)/{factor:.4f},{base},"
            f"drawbox=x=0:y=1030:w=1920:h=50:color=0x101418@0.85:t=fill,"
            f"drawtext=fontfile='{FONT}':textfile='{cap}':fontcolor={color}:fontsize=30:x=28:y=1039[v{index}]")
        labels.append(f"[v{index}]")
    labels.append("[outro]")
    filters.append("".join(labels) + f"concat=n={len(labels)}:v=1:a=0[out]")
    script = work_dir / "filter.txt"
    script.write_text(";\n".join(filters), encoding="utf-8")
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-stats", "-y", "-i", str(raw),
               "-filter_complex_script", str(script), "-map", "[out]",
               "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-pix_fmt", "yuv420p",
               "-movflags", "+faststart", str(target)]
    subprocess.run(command, check=True)
    print("готово:", target, f"{probe_duration(target) / 60:.2f} мин,", f"{target.stat().st_size // 1_000_000} МБ")


if __name__ == "__main__":
    main()
