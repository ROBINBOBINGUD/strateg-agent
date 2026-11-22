"""SessionStart: кладёт в контекст статус активного проекта, чтобы новый чат продолжил с сохранённого места."""
from _common import active_project, read_event, strateg


def main() -> None:
    event = read_event()
    module = strateg()
    project = active_project()
    lines = []
    if module is None:
        lines.append("Стратег: не найден tools/strateg.py — выполни проверку установки по README.md.")
    elif project is None:
        lines.append("Стратег: активного проекта нет. Новый запрос начни командой /strateg или "
                     "`python tools/strateg.py new <id> --title \"…\"`. Материалы человека лежат в inbox/.")
    else:
        lines.append("Стратег: есть активный проект. Продолжай с шага «следующее действие», "
                     "выполненные шаги не повторяй. Статус на момент старта сеанса:")
        try:
            lines.append(module.status_text(project))
        except Exception as error:  # статус не должен мешать старту
            lines.append(f"(не удалось прочитать статус: {error}; выполни `python tools/strateg.py status`)")
        try:
            module.append_journal(project, {
                "session": event.get("session_id", ""),
                "event": "note",
                "tool": "SessionStart",
                "target": event.get("source", ""),
                "note": "Начат сеанс; статус проекта передан агенту",
            })
        except Exception:
            pass
    print("\n".join(lines))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
