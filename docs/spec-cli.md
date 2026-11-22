# Спецификация CLI `tools/strateg.py`

Один файл, только стандартная библиотека Python 3.10+. Работает на Windows, macOS, Linux. Все файлы читать и писать в UTF-8. В начале `main()` на Windows: `sys.stdout.reconfigure(encoding="utf-8")` и то же для stderr. Сообщения пользователю — по-русски. Код возврата 0 — успех, 1 — найдены ошибки (`check`), 2 — неверный вызов.

Запуск: `python tools/strateg.py <команда> ...` из корня репозитория или из любой его подпапки.

## Расположение данных

- Корень репозитория — ближайший вверх каталог с файлом `AGENTS.md` (функция `find_root()`); если задана переменная окружения `CLAUDE_PROJECT_DIR` и в ней есть `AGENTS.md` — она.
- `projects/ACTIVE` — текстовый файл с идентификатором активного проекта.
- `projects/_template/` — шаблон проекта (копируется командой `new`; если шаблона нет — создать структуру самому).
- `projects/<id>/`:
  - `state.json` — состояние задачи;
  - `sources.jsonl` — реестр источников; `evidence.jsonl` — реестр утверждений; `decisions.jsonl` — журнал решений;
  - `journal.jsonl` — журнал действий; `costs.jsonl` — расходы по сеансам;
  - `materials/` — исходные материалы; `outputs/` — результаты (`*.md`); `analysis/` — расчёты;
  - `sources.md`, `evidence.md`, `STATUS.md` — читаемые представления, их пересоздаёт CLI.
- `memory/notes.jsonl` — память между проектами. `knowledge/*.md` — методические карточки.

## Форматы

`state.json`:
```json
{"id": "demo", "title": "…", "created": "ISO", "updated": "ISO", "current_step": "intake",
 "steps": [{"id": "intake", "title": "Постановка задачи", "status": "pending", "started": null, "finished": null, "outputs": [], "note": ""}],
 "waiting_for_human": null,
 "gates": []}
```
Шаги по умолчанию (id → название): `intake` Постановка задачи; `collect` Сбор материалов; `research` Исследование и картина ситуации; `options` Варианты; `product` Продуктовая стратегия; `comms` Коммуникационная стратегия; `testplan` План проверки; `final` Сборка и самопроверка; `support` Поддержка решения. Статусы шага: `pending`, `in_progress`, `done`, `blocked`.
`waiting_for_human`: `null` или `{"question": "…", "options": ["…"], "step": "options", "since": "ISO"}`. `gates` — история: `{"step", "question", "options", "answer", "asked", "answered"}`.

`sources.jsonl`, по объекту в строке: `{"id": "S-001", "type": "document|table|site|interview|synthetic|calc", "title": "…", "ref": "URL или путь", "publisher": "…", "published": "дата или ''", "accessed": "YYYY-MM-DD", "reliability": "A|B|C", "note": "…"}`.

`evidence.jsonl`: `{"id": "E-001", "kind": "fact|hypothesis|forecast|assumption|synthetic", "text": "…", "sources": ["S-001"], "confidence": "high|medium|low", "status": "active|revoked", "updated": "YYYY-MM-DD", "note": "…"}`.

`decisions.jsonl`: `{"id": "D-001", "date": "YYYY-MM-DD", "decision": "…", "owner": "…", "metric": "…", "review_condition": "…", "review_date": "YYYY-MM-DD или ''", "based_on": ["E-001"], "status": "active|revised|cancelled"}`.

`journal.jsonl`: `{"ts": "ISO", "session": "…", "event": "tool|step|gate|escalation|error|injection|note|cost", "tool": "…", "target": "…", "note": "…"}`.

`costs.jsonl`: `{"ts": "ISO", "session": "…", "source": "headless|stop-hook|manual", "label": "…", "duration_s": 0, "cost_usd": 0.0, "models": {"<model>": {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "cost_usd": 0.0}}}`. Записи с тем же `session` заменяются (upsert), а не дублируются.

`memory/notes.jsonl`: `{"id": "M-001", "date": "YYYY-MM-DD", "kind": "lesson|pattern|agent-conclusion", "text": "…", "origin": "…", "status": "active|revoked", "revoked_reason": ""}`.

Идентификаторы выдаёт CLI: следующий номер после максимального, три цифры.

## Команды

- `new <id> --title "…"` — создать проект из шаблона, записать `projects/ACTIVE`, шаг `intake` → `in_progress`. Ошибка, если проект уже есть.
- `use <id>` — сделать проект активным. `projects` — список проектов с текущим шагом.
- `status [--json]` — заголовок, таблица шагов с отметками, вопрос к человеку (если ждём ответа), «следующее действие» (первый шаг не в `done`), число источников / утверждений по видам / решений, суммарные расходы и время. Также перезаписывает `STATUS.md`.
- `step <step-id> start|done|block [--note "…"] [--outputs a.md,b.md]` — сменить статус, проставить время, записать событие `step` в журнал. `done` для шага запрещён, пока `waiting_for_human` относится к этому шагу. `start` для уже выполненного шага требует `--redo` (защита от незаметного повтора) и пишет в журнал причину.
- `gate ask "<вопрос>" [--options "A|B|C"] [--step <id>]` — записать вопрос человеку (существенный выбор). `gate answer "<ответ>"` — записать ответ, очистить ожидание, событие `gate` в журнал.
- `source add --type T --title "…" --ref "…" [--publisher P] [--published D] [--reliability A|B|C] [--note N]` — добавить источник, напечатать его id. Если источник с таким `ref` уже есть — напечатать существующий id и не дублировать.
- `evidence add --kind K --text "…" --sources S-001,S-002 [--confidence C] [--note N]` — добавить утверждение (агент может и дописывать `evidence.jsonl` напрямую пачкой — тогда `check` проверит формат).
- `revoke <E-id> --reason "…"` — пометить утверждение отозванным (текст не удалять), событие в журнал.
- `check` — проверка проекта:
  1. каждая строка JSONL разбирается, обязательные поля есть, значения из допустимых списков, id уникальны;
  2. у `fact` есть хотя бы один источник, и не все его источники типа `synthetic`; `synthetic`-утверждения ссылаются только на `synthetic`-источники;
  3. все `S-…` в `evidence.jsonl` существуют;
  4. во всех `outputs/*.md` каждая ссылка вида `[E-012]` или `[S-003]` (допустимы списки `[E-001, E-002]`) существует; ссылка на отозванное утверждение — ошибка;
  5. предупреждения (не ошибки): строка в `outputs/*.md` с числом (цифры рядом с %, руб, тыс, млн или число от трёх цифр) без единой ссылки в этом же абзаце и без слова «допущение»; источник, на который никто не ссылается; решение с `review_date` в прошлом.
  Печатает список «ОШИБКА / ПРЕДУПРЕЖДЕНИЕ: файл:строка — текст», итог, и пересоздаёт `sources.md`, `evidence.md` (таблицы markdown, отозванные — зачёркнуты), `STATUS.md`. Код возврата 1 при ошибках.
- `impact <S-id|E-id>` — что зависит от источника или утверждения: утверждения, опирающиеся на источник; строки `outputs/*.md` (файл:номер: текст до 160 символов), где они упомянуты; решения, у которых они в `based_on`.
- `decisions add --decision "…" --owner "…" --metric "…" --review-condition "…" [--review-date D] [--based-on E-001,E-002]`; `decisions list`; `decisions due` — решения, у которых прошла `review_date` или среди `based_on` есть отозванное утверждение (с объяснением причины).
- `journal [--tail N]` — последние N событий (по умолчанию 30) в читаемом виде. `log <event> "<note>"` — добавить событие вручную (например, `escalation`, `error`).
- `cost` — таблица расходов по сеансам и итог (USD, минуты). `cost add --label "…" --usd X --duration-s N [--session ID] [--source S]` — добавить вручную. `cost import <файл.json>` — взять результат `claude -p --output-format json` (поля `session_id`, `total_cost_usd`, `duration_ms`, `modelUsage` с `inputTokens`, `outputTokens`, `cacheReadInputTokens`, `cacheCreationInputTokens`, `costUSD`) и записать с `source: headless`; параметр `--label`.
- `memory add --kind K --text "…" [--origin O]`; `memory revoke <M-id> --reason "…"`; `memory list`.
- `search "<запрос>"` — поиск по `knowledge/*.md` (по абзацам), `memory/notes.jsonl` (только `active`) и `evidence.jsonl` активного проекта. Оценка — совпадение слов без учёта регистра, с усечением слова до первых 5 букв (простейшая морфология для русского). Вывод: до 10 результатов «тип | файл или id | фрагмент». У результатов из памяти — пометка «заметка агента, не факт».

## Функции для импорта (их используют хуки)

`find_root() -> Path`, `active_project() -> Path | None`, `append_journal(project: Path, event: dict) -> None` (сам добавляет `ts`), `status_text(project: Path) -> str` (то же, что печатает `status`, не длиннее 2500 символов), `upsert_cost(project: Path, record: dict) -> None`.

## Тесты

`tools/tests/test_strateg.py` на `unittest`: во временной папке создать корень с `AGENTS.md`, пройти сценарий `new → step → source add → evidence add → check (ошибка на несуществующую ссылку) → revoke → impact → decisions due → cost import → search`. Запуск: `python -m unittest discover -s tools/tests`.
