"""Сборка итогового ролика из записи окна с воспроизведением сеансов.

Ждёт конца воспроизведения (файл docs/video/raw/replay.done), останавливает запись, добавляет титры
в начале и в конце и кодирует 1920x1080, 30 кадров в секунду. Если ролик длиннее 9 мин 50 с,
равномерно ускоряет его и пишет коэффициент в титр.

Запуск: python docs/build/final_video.py     (нужен ffmpeg 6+)
"""
import json
import subprocess
import sys
import time
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "docs" / "video" / "raw"
OUT = ROOT / "docs" / "video" / "strateg-demo.mp4"
FONT = "C\\:/Windows/Fonts/segoeui.ttf"
FONT_BOLD = "C\\:/Windows/Fonts/segoeuib.ttf"
LIMIT = 9 * 60 + 50
INTRO, OUTRO, SKIP = 7, 6, 4.0


def run(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, check=check)


def duration(path: Path) -> float:
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)])
    return float(out.stdout.decode().strip())


def textfile(name: str, text: str) -> str:
    path = RAW / name
    path.write_text(text, encoding="utf-8")
    return str(path).replace("\\", "/").replace(":", "\\:")


def card(label: str, seconds: int, title: str, body: str) -> str:
    return (f"color=c=0x0f1318:s=1920x1080:d={seconds}:r=30,"
            f"drawtext=fontfile='{FONT_BOLD}':textfile='{textfile(label + '-t.txt', title)}':fontcolor=white:"
            f"fontsize=58:x=(w-text_w)/2:y=330,"
            f"drawtext=fontfile='{FONT}':textfile='{textfile(label + '-b.txt', body)}':fontcolor=0xb8c4d0:"
            f"fontsize=32:line_spacing=18:x=(w-text_w)/2:y=470,format=yuv420p[{label}]")


def main() -> None:
    deadline = time.time() + 15 * 60
    while not (RAW / "replay.done").exists() and time.time() < deadline:
        time.sleep(4)
    time.sleep(5)
    info = json.loads((RAW / "zapis.json").read_text(encoding="utf-8-sig"))
    subprocess.run(["taskkill", "/PID", str(info["pid"]), "/F"], capture_output=True)
    time.sleep(2)
    source = Path(info["file"])
    fixed = RAW / "replay-fixed.mkv"
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source), "-c", "copy", str(fixed)])
    length = duration(fixed) - SKIP
    budget = LIMIT - INTRO - OUTRO
    speed = max(1.0, length / budget)
    note = "" if speed < 1.01 else f"\nЗапись равномерно ускорена в {speed:.2f} раза, чтобы уложиться в 10 минут."
    intro = card("intro", INTRO, "Стратег — ИИ-агент руководителя продукта",
                 "Демонстрационный проект по брифу МегаФона: от запроса до стратегии и после решения\n"
                 "Воспроизведение транскриптов настоящих сеансов Claude Code и Codex, 22–23 ноября 2026\n"
                 "Время слева — московское время каждого действия; паузы между действиями сжаты" + note)
    outro = card("outro", OUTRO, "github.com/ROBINBOBINGUD/strateg-agent",
                 "README.md — запуск за три команды\ndocs/Описание.pdf — архитектура, расходы, ошибки, сравнение\n"
                 "projects/family-multisim/outputs/STRATEGIYA.md — итоговый документ")
    body = (f"[0:v]trim=start={SKIP},setpts=(PTS-STARTPTS)/{speed:.5f},fps=30,"
            "scale=1920:1080:force_original_aspect_ratio=decrease:flags=lanczos,"
            "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0x0c0c0c,setsar=1,format=yuv420p[main]")
    graph = RAW / "final-filter.txt"
    graph.write_text(";\n".join([intro, outro, body, "[intro][main][outro]concat=n=3:v=1:a=0[out]"]), encoding="utf-8")
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(fixed), "-/filter_complex", str(graph),
         "-map", "[out]", "-c:v", "libx264", "-preset", "medium", "-crf", "24", "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", str(OUT)])
    size = OUT.stat().st_size / 1_000_000
    print(f"готово: {OUT.name}, {duration(OUT) / 60:.2f} мин, {size:.1f} МБ, ускорение {speed:.2f}")
    if size > 24:      # версия для вложения в письмо: 720p, 15 кадров в секунду
        small = OUT.with_name("strateg-demo-720p.mp4")
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(OUT), "-vf", "scale=1280:720:flags=lanczos,fps=15",
             "-c:v", "libx264", "-preset", "slow", "-crf", "29", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(small)])
        print(f"версия для письма: {small.name}, {small.stat().st_size / 1_000_000:.1f} МБ")


if __name__ == "__main__":
    main()
