"""Сборка docs/Описание.pdf из docs/Описание.md.

Markdown -> HTML (пакет markdown) -> PDF (Playwright, Chromium). Картинки берутся из docs/img/.
Запуск: python docs/build/make_pdf.py
Пакеты markdown и playwright нужны только для сборки описания; агенту они не нужны.
"""
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

DOCS = Path(__file__).resolve().parents[1]
SOURCE = DOCS / "Описание.md"
TARGET = DOCS / "Описание.pdf"

CSS = """
@page { size: A4; margin: 16mm 15mm 16mm 15mm; }
body { font-family: 'Segoe UI', 'Noto Sans', Arial, sans-serif; font-size: 10.4pt; line-height: 1.45; color: #1c2128; }
h1 { font-size: 21pt; margin: 0 0 6pt; color: #0b3d5c; }
h2 { font-size: 14.5pt; margin: 18pt 0 6pt; color: #0b3d5c; border-bottom: 1.5pt solid #d0d7de; padding-bottom: 3pt;
     break-after: avoid; }
h3 { font-size: 11.6pt; margin: 12pt 0 4pt; color: #24292f; break-after: avoid; }
p { margin: 0 0 6pt; }
ul, ol { margin: 0 0 6pt 16pt; padding: 0; }
li { margin-bottom: 2pt; }
table { border-collapse: collapse; width: 100%; margin: 6pt 0 9pt; font-size: 9.2pt; }
th, td { border: 0.6pt solid #c4ccd4; padding: 3.5pt 5pt; vertical-align: top; text-align: left; }
th { background: #eef2f6; }
tr { break-inside: avoid; }
code { font-family: 'Cascadia Mono', Consolas, monospace; font-size: 8.9pt; background: #f1f3f5; padding: 0 2pt;
       border-radius: 2pt; }
pre { background: #f6f8fa; border: 0.6pt solid #d0d7de; border-radius: 4pt; padding: 6pt 8pt; font-size: 8.3pt;
      line-height: 1.38; white-space: pre-wrap; word-break: break-word; break-inside: avoid; }
pre code { background: none; padding: 0; font-size: inherit; }
img { max-width: 100%; display: block; margin: 5pt auto 3pt; border: 0.6pt solid #d0d7de; border-radius: 4pt; }
figure { margin: 0 0 9pt; break-inside: avoid; }
figcaption, p.cap { font-size: 8.8pt; color: #57606a; text-align: center; margin: 0 0 9pt; }
blockquote { margin: 5pt 0 8pt; padding: 3pt 10pt; border-left: 2.5pt solid #0b3d5c; background: #f3f7fa; color: #24292f; }
.lead { font-size: 11pt; color: #3d444d; }
hr { border: 0; border-top: 0.6pt solid #d0d7de; margin: 10pt 0; }
"""


def main() -> None:
    import markdown
    from playwright.sync_api import sync_playwright

    text = SOURCE.read_text(encoding="utf-8")
    body = markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists", "attr_list"])
    html = f"<!doctype html><html lang='ru'><head><meta charset='utf-8'><style>{CSS}</style></head><body>{body}</body></html>"
    page_file = DOCS / "build" / "_opisanie.html"
    page_file.write_text(html, encoding="utf-8")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(DOCS.as_uri() + "/build/_opisanie.html")
        # картинки лежат в docs/img, а страница — в docs/build: подставляем базовый адрес docs/
        page.set_content(html.replace("<head>", f"<head><base href='{DOCS.as_uri()}/'>"), wait_until="load")
        page.pdf(path=str(TARGET), format="A4", print_background=True,
                 display_header_footer=True, header_template="<span></span>",
                 footer_template="<div style='font-size:8px;color:#8c959f;width:100%;text-align:center'>"
                                 "Стратег — описание работы · стр. <span class='pageNumber'></span> из "
                                 "<span class='totalPages'></span></div>")
        browser.close()
    page_file.unlink(missing_ok=True)
    print("готово:", TARGET, f"{TARGET.stat().st_size // 1024} КБ")


if __name__ == "__main__":
    main()
