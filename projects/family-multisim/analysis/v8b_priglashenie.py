"""v8b: вторая проверка пилота B — новый экран приглашения, напоминание и подсказка к первому действию.

Запуск: python projects/family-multisim/analysis/v8b_priglashenie.py
Результат печатается и сохраняется в analysis/v8b_priglashenie.md. Только стандартная библиотека.

Единица — новая созданная группа (рандомизация по организатору при создании группы).
Показатель — доля групп, активированных за 14 дней (определение брифа, E-009): знаменатель — все созданные группы.
"""
import sys
from math import ceil, sqrt
from pathlib import Path
from statistics import NormalDist

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

SCEN = ("осторожное", "основное", "сильное")
P0 = 0.45                                # E-010: активация за 14 дней без изменений
LIFTS = (0.03, 0.05, 0.065, 0.10)        # п.п.; 6,5 п.п. — основной прогноз B (E-049)
GROUP_CREATED_H2 = (2000, 2500, 3000)    # допущение v6: групп создаётся за 2-е полугодие (26 недель)
# Экран приглашения, напоминание и подсказка не зависят от права передачи интернета,
# поэтому проверяются на всех новых группах, а не только на подходящих тарифах.
SHARE_ELIG = (1.0, 1.0, 1.0)
RECRUIT_WEEKS = {"конец 2-го кв.": 5 - 2, "конец 3-го кв.": 5 + 13 - 2}  # минус 14 дней наблюдения
ALPHA, POWER = 0.05, 0.8

za = NormalDist().inv_cdf(1 - ALPHA / 2)
zb = NormalDist().inv_cdf(POWER)


def n_arm(p1, p2):
    pb = (p1 + p2) / 2
    return ceil((za * sqrt(2 * pb * (1 - pb)) + zb * sqrt(p1 * (1 - p1) + p2 * (1 - p2))) ** 2 / (p1 - p2) ** 2)


def mde_up(n, p1):
    lo, hi = 1e-6, 1 - p1 - 1e-6
    for _ in range(100):
        mid = (lo + hi) / 2
        if n_arm(p1, p1 + mid) > n:
            lo = mid
        else:
            hi = mid
    return hi


def f(x, d=1):
    return f"{x:,.{d}f}".replace(",", " ").replace(".", ",")


OUT = []


def emit(s=""):
    print(s)
    OUT.append(s)


emit("# v8b. Проверка нового экрана приглашения: выборка и срок")
emit()
emit(f"Показатель: активация за 14 дней, база {f(P0 * 100, 0)} % [E-010]; alpha {ALPHA} двусторонняя, мощность {POWER}; распределение 1:1.")
emit()
emit("## Таблица 1. Групп на вариант")
emit()
emit("| Рост, п.п. | Относительный рост | Групп на вариант |")
emit("|---|---|---|")
for d in LIFTS:
    emit(f"| {f(d * 100)} | {f(d / P0 * 100)} % | {n_arm(P0, P0 + d)} |")
emit()
emit("## Таблица 2. Поток новых групп и календарь")
emit()
emit("| Сценарий | Новых подходящих групп в неделю | Момент | Недель набора | Групп на вариант | Обнаружимый рост, п.п. | Недель для 6,5 п.п. |")
emit("|---|---|---|---|---|---|---|")
need = n_arm(P0, P0 + 0.065)
for i, sc in enumerate(SCEN):
    flow = GROUP_CREATED_H2[i] / 26 * SHARE_ELIG[i]
    weeks_need = ceil(2 * need / flow)
    for label, w in RECRUIT_WEEKS.items():
        n = int(flow * w / 2)
        emit(f"| {sc} | {f(flow)} | {label} | {w} | {n} | {f(mde_up(n, P0) * 100)} | {weeks_need} |")
emit()
Path(__file__).with_suffix(".md").write_text("\n".join(OUT) + "\n", encoding="utf-8")
print(f"Сохранено: {Path(__file__).with_suffix('.md')}")
