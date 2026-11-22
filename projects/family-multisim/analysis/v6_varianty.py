"""v6: сравнение вариантов на одном горизонте (плановый год) и прогноз пяти показателей.

Запуск: python projects/family-multisim/analysis/v6_varianty.py
Результат печатается и сохраняется в analysis/v6_varianty.md. Только стандартная библиотека.

Модель упрощённая и намеренно прозрачная: каждое слагаемое = объём × цена × период.
Сценарии: (осторожное, основное, сильное). «Менее благоприятный» ход событий брифа = осторожное.
"""
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

SCEN = ("осторожное", "основное", "сильное")

# ---------------------------------------------------------------- факты (учебные, S-002)
PROFIT_BASE = 279.0        # E-002, млн руб., без изменений
CONN_BASE = 8000           # E-006, групп на конец планового года без изменений
ACTIVE_SHARE_BASE = 5000 / 8000   # E-004, E-006: 62,5 %
OWN_BASE = 1000            # E-008, владельцев на конец года без изменений
ACTIV_BASE = 0.45          # E-010, доля активированных за 14 дней без изменений
RATE = 500                 # E-012, руб. за доп. номеро-месяц
GOALS = {"profit": 285.0, "active": 8000, "conn": 12000, "own": 2000, "activ": 0.60}  # E-002..E-010

# ---------------------------------------------------------------- общие допущения
COST_PM = (0.60, 0.45, 0.30)      # допущение: млн руб. за человеко-месяц (осторожное = дороже)
FAM_GROUPS_AVG = (6500, 7250, 8000)   # E-033 / v5
FAM_SIZE = (2.5, 3.0, 3.5)            # E-033
FAM_CHURN = (0.010, 0.015, 0.025)     # E-029
FAM_DISRUPT = (0.05, 0.10, 0.20)      # E-033
FAM_RELCUT = (0.05, 0.15, 0.30)       # E-033
FAM_PREVENT = (0.30, 0.50, 0.70)      # E-033
OWN_AVG = (800, 900, 1000)            # E-033
OWN_NUMS = (2.0, 2.3, 2.7)
OWN_STOP = (0.03, 0.06, 0.12)
OWN_LEAVE = (0.05, 0.10, 0.20)
OWN_PREVENT = (0.40, 0.60, 0.80)
GROUP_CREATED_H2 = (2000, 2500, 3000)  # допущение: групп создаётся во втором полугодии (нет в брифе)
NEW_MONTHS = 3                          # допущение: оплаченных месяцев в году у номера, пришедшего во 2-м полугодии
# Правки после критика (шаг options):
FAM_ELIGIBLE = (0.40, 0.60, 0.80)       # допущение (как в v5): доля групп, подходящих по тарифу и разрешению
EXHAUST_SHARE = (0.5, 0.6, 0.7)         # допущение: доля перебоев из-за исчерпания доли (на неоплату B не действует)
ACCEPT_BASE, ACT14_BASE = 0.60, 0.75    # допущение: воронка активации 45 % = принято 60 % × первое действие в 14 дней 75 %
# Календарь пилота семей: разработка 3 чм во 2-м кв. (~7 недель), тестирование, набор с 9-й недели 2-го кв.
PILOT_RECRUIT_WEEKS_Q2 = 5              # допущение: недель набора во 2-м квартале после разработки и теста
PILOT_RECRUIT_WEEKS_Q3 = 13             # продолжение набора в 3-м квартале
FAM_WEEK_EVENT = (0.01, 0.02, 0.04)     # допущение (v5): доля групп с первым случаем низкого остатка в неделю
P_BASE = 0.12                           # допущение (пример брифа): доля ограничений за 7 дней
MIN_IMPORTANT_PP = 0.03                 # допущение: наименьшее важное улучшение 3 п.п. (12 % -> 9 %), задаётся до запуска

# ---------------------------------------------------------------- варианты (допущения)
# Человеко-месяцы: разработка + тестирование; дизайнер и аналитик (по 0,5 ставки) — отдельная строка, общая для всех.
DA_PM = (6.0, 4.5, 3.0)   # допущение: дизайнер+аналитик 0,5+0,5 ставки на 6 / 4,5 / 3 мес

OPTIONS = {
    "A": dict(name="Оставить как есть", dev_pm=(0, 0, 0), da=False, months=(0, 0, 0),
              act_up=(0, 0, 0), accept_up=(0, 0, 0), new_share=(0, 0, 0), activ_up=(0, 0, 0),
              fam_ret=False, own_ret=False, own_extra=(0, 0, 0), extra_groups=(0, 0, 0),
              direct_rub_per_new=(0, 0, 0), notes="Прогноз оператора без изменений"),
    "B": dict(name="Семьи: сигнал в момент риска + доведение приглашения", dev_pm=(4.0, 3.0, 2.0), da=True,
              months=(3, 6, 6),                 # полный охват подходящих: осторожно — расширение только с 4-го кв.
              act_up=(0.01, 0.03, 0.05),       # допущение: рост доли активных среди ПОДХОДЯЩИХ групп
              accept_up=(0.03, 0.06, 0.10),     # допущение: рост доли созданных групп, где приняли приглашение (п.п.)
              act14_up=(0.0, 0.03, 0.05),       # допущение: рост доли принявших, сделавших первое действие в 14 дней
              new_share=(0.0, 0.1, 0.2),        # допущение: приглашение близкого с другого оператора без скидки
              activ_up=(0, 0, 0),               # активация считается из воронки (accept_up, act14_up)
              fam_ret=True, own_ret=False, own_extra=(0, 0, 0), extra_groups=(0, 0, 0),
              direct_rub_per_new=(0, 0, 0), notes="Использует существующее выделение интернета"),
    "C": dict(name="Семьи: общий семейный кабинет", dev_pm=(12.0, 9.0, 7.0), da=True,
              months=(2, 3, 3),                 # допущение: запуск не раньше 4-го квартала
              act_up=(0.02, 0.04, 0.07), accept_up=(0.03, 0.06, 0.10), act14_up=(0.0, 0.03, 0.05),
              new_share=(0.0, 0.1, 0.2),
              activ_up=(0, 0, 0), fam_ret=True, own_ret=False, own_extra=(0, 0, 0),
              extra_groups=(0, 0, 0), direct_rub_per_new=(0, 0, 0),
              notes="Нужно больше 3 чм разработки; эффект доли групп — только в 4-м квартале"),
    "D": dict(name="Владельцы: предупреждение о списании номера устройства", dev_pm=(2.5, 1.5, 1.0), da=True,
              months=(3, 6, 6), act_up=(0, 0, 0), accept_up=(0, 0, 0), new_share=(0, 0, 0), activ_up=(0, 0, 0),
              fam_ret=False, own_ret=True,
              own_extra=(100, 300, 600),        # допущение: доп. владельцев — предложение объединить номера в момент неудачного списания на SIM устройства
              extra_groups=(0, 0, 0), direct_rub_per_new=(0, 0, 0),
              notes="Доп. владельцы — существующие абоненты, новых номеров не дают (допущение)"),
    "E": dict(name="Семьи: привлечение близких с других операторов", dev_pm=(2.0, 1.5, 1.0), da=True,
              months=(3, 6, 6), act_up=(0, 0, 0), accept_up=(0, 0, 0), new_share=(0, 0, 0),
              activ_up=(-0.03, 0.0, 0.0),       # допущение: приглашения вне сети принимают хуже
              fam_ret=False, own_ret=False, own_extra=(0, 0, 0),
              extra_groups=(400, 900, 1600),    # допущение: доп. групп с хотя бы одним новым номером
              new_per_group=(1.0, 1.3, 1.6),    # допущение: новых номеров в такой группе
              direct_rub_per_new=(450, 450, 300),  # допущение: скидка 150 руб./мес × 3 мес (или 100 в сильном)
              notes="Скидка за новый номер — прямой расход"),
    "F": dict(name="Заморозить направление и отдать ресурс другим продуктам", dev_pm=(0, 0, 0), da=False, months=(0, 0, 0),
              act_up=(-0.02, -0.01, 0.0), accept_up=(0, 0, 0), new_share=(0, 0, 0), activ_up=(-0.02, -0.01, 0.0),
              fam_ret=False, own_ret=False, own_extra=(-150, -100, 0),
              extra_groups=(-800, -500, -200),   # допущение: без продвижения в приложении и продажах прирост групп ниже
              direct_rub_per_new=(0, 0, 0), notes="Снято продвижение; 3 чм 2-го кв. уходят в другой продукт"),
}


def fam_ret_months(i, m):
    # только подходящие группы и только перебои из-за исчерпания доли; верхняя граница (спасённый номер не уходит до конца года,
    # месяц спасения засчитан)
    saved = (FAM_GROUPS_AVG[i] * FAM_ELIGIBLE[i] * FAM_SIZE[i] * FAM_DISRUPT[i] * EXHAUST_SHARE[i]
             * FAM_PREVENT[i] * FAM_CHURN[i] * FAM_RELCUT[i])
    return saved * m * (m + 1) / 2


def own_ret_months(i, m):
    saved = OWN_AVG[i] * OWN_NUMS[i] * OWN_STOP[i] * OWN_LEAVE[i] * OWN_PREVENT[i]
    return saved * m * (m + 1) / 2


def evaluate(key, i):
    o = OPTIONS[key]
    m = o["months"][i]
    ret = 0.0
    if o["fam_ret"]:
        ret += fam_ret_months(i, m)
    if o["own_ret"]:
        ret += own_ret_months(i, m)
    # доп. группы за счёт принятия приглашений: только группы, созданные во время действия (доля m/6 полугодия)
    accept_groups = GROUP_CREATED_H2[i] * o["accept_up"][i] * min(m, 6) / 6
    new_from_accept = accept_groups * (FAM_SIZE[i] - 1) * o["new_share"][i]
    acq_share = 1.0 if o["extra_groups"][i] < 0 else min(m, 6) / 6   # для F снижение прироста — весь год
    extra_groups = accept_groups + o["extra_groups"][i] * acq_share
    new_from_acq = max(o["extra_groups"][i], 0) * acq_share * o.get("new_per_group", (0, 0, 0))[i]
    new_numbers = new_from_accept + new_from_acq
    new_months = new_numbers * NEW_MONTHS
    gross = (ret + new_months) * RATE / 1e6
    direct = new_from_acq * o["direct_rub_per_new"][i] / 1e6
    contrib = gross - direct
    pm = o["dev_pm"][i] + (DA_PM[i] if o["da"] else 0)
    invest = pm * COST_PM[i]
    conn = CONN_BASE + extra_groups
    elig = FAM_ELIGIBLE[i] if o["fam_ret"] else 1.0       # рост доли активных — только среди подходящих групп
    active = conn * (ACTIVE_SHARE_BASE + o["act_up"][i] * elig)
    # активация из воронки: (принято + рост) × (первое действие + рост); у вариантов без воронки — сдвиг activ_up
    a_up, b_up = o["accept_up"][i], o.get("act14_up", (0, 0, 0))[i]
    activ = (ACCEPT_BASE + a_up) * (ACT14_BASE + b_up) + o["activ_up"][i]
    return dict(m=m, ret=ret, new_numbers=new_numbers, new_months=new_months, gross=gross, direct=direct,
                contrib=contrib, pm=pm, invest=invest, net_year=contrib - invest,
                profit=PROFIT_BASE + contrib, conn=conn, active=active,
                own=OWN_BASE + o["own_extra"][i], activ=activ, extra_groups=extra_groups)


OUT = []


def emit(s=""):
    print(s)
    OUT.append(s)


def f(x, d=1):
    return f"{x:,.{d}f}".replace(",", " ").replace(".", ",")


def table(head, rows):
    emit("| " + " | ".join(head) + " |")
    emit("|" + "---|" * len(head))
    for r in rows:
        emit("| " + " | ".join(str(c) for c in r) + " |")
    emit()


emit("# v6. Варианты: вклад в прибыль, вложения и пять показателей планового года")
emit()
emit("Формулы: вклад = (доп. номеро-месяцы удержания + новые номера × 3 мес.) × 500 руб. − прямые расходы (скидки);")
emit("вложения = (чм разработки и тестирования + чм дизайнера и аналитика) × цена чм; подключённые = 8000 + доп. группы;")
emit("активные = подключённые × (62,5 % + рост доли). Валовая прибыль = 279 + вклад (вложения в разработку в валовую прибыль не входят).")
emit("Все параметры вариантов — допущения (см. начало скрипта).")
emit()

rows = []
for k in OPTIONS:
    for i, sc in enumerate(SCEN):
        r = evaluate(k, i)
        rows.append([k, sc, r["m"], f(r["ret"], 0), f(r["new_numbers"], 0), f(r["gross"], 2), f(r["direct"], 2),
                     f(r["contrib"], 2), f(r["pm"], 1), f(r["invest"], 2), f(r["net_year"], 2)])
emit("## Таблица 1. Вклад и вложения в плановом году, млн руб.")
emit()
table(["Вар.", "Сценарий", "Мес. действия", "Доп. номеро-мес. удержания", "Новых номеров", "Валовой вклад",
       "Прямые расходы", "Вклад после прямых", "Человеко-мес.", "Вложения", "Вклад − вложения за год"], rows)

rows = []
for k in OPTIONS:
    for i in (1, 0):
        r = evaluate(k, i)
        rows.append([k, SCEN[i], f(r["profit"], 1), f(r["active"], 0), f(r["conn"], 0), f(r["own"], 0),
                     f(r["activ"] * 100, 0) + " %"])
rows.append(["Цель", "", f(GOALS["profit"], 1), f(GOALS["active"], 0), f(GOALS["conn"], 0), f(GOALS["own"], 0), "60 %"])
emit("## Таблица 2. Прогноз пяти показателей (основной и менее благоприятный ход)")
emit()
table(["Вар.", "Сценарий", "Валовая прибыль, млн руб.", "Активные группы (посл. месяц)", "Подключённые группы",
       "Владельцы нескольких номеров", "Активация за 14 дней"], rows)

emit("## Таблица 3. Граница решения")
emit()
rows = []
for k in ("B", "C", "D", "E"):
    r = evaluate(k, 1)
    per_month = r["contrib"] / r["m"] if r["m"] else 0
    rows.append([k, f(r["contrib"], 2), f(r["invest"], 2), f(r["contrib"], 2),
                 f(6 / r["contrib"], 1) if r["contrib"] > 0 else "—"])
table(["Вар.", "Вклад после прямых (основной), млн руб.", "Вложения (основной), млн руб.",
       "Предельные вложения, окупаемые в плановом году, млн руб.", "Во сколько раз эффект должен быть больше, чтобы закрыть 6 млн"], rows)

# Какое число новых номеров закрывает 6 млн
need_new = 6e6 / RATE / NEW_MONTHS
emit(f"Новых номеров, пришедших во 2-м полугодии (3 оплаченных месяца), нужно для 6 млн руб.: {f(need_new, 0)}.")
emit()

emit("## Таблица 4. Календарь пилота семей (вариант B): что можно узнать к концу 2-го и 3-го квартала")
emit()
from math import ceil, sqrt
from statistics import NormalDist
za, zb = NormalDist().inv_cdf(0.975), NormalDist().inv_cdf(0.8)


def n_arm(p1, p2):
    pb = (p1 + p2) / 2
    return ceil((za * sqrt(2 * pb * (1 - pb)) + zb * sqrt(p1 * (1 - p1) + p2 * (1 - p2))) ** 2 / (p1 - p2) ** 2)


def mde(n, p1):
    lo, hi = 0.0001, p1 - 1e-6
    for _ in range(100):
        mid = (lo + hi) / 2
        if n_arm(p1, mid) > n:
            hi = mid
        else:
            lo = mid
    return lo


need = n_arm(P_BASE, P_BASE - MIN_IMPORTANT_PP)
rows = []
for i, sc in enumerate(SCEN):
    flow = FAM_GROUPS_AVG[i] * FAM_WEEK_EVENT[i] * FAM_ELIGIBLE[i]
    for label, weeks in (("конец 2-го кв.", PILOT_RECRUIT_WEEKS_Q2 - 1),
                         ("конец 3-го кв.", PILOT_RECRUIT_WEEKS_Q2 + PILOT_RECRUIT_WEEKS_Q3 - 1)):
        n = int(flow * weeks / 2)
        rows.append([sc, label, weeks, f(flow, 0), n, f(mde(n, P_BASE) * 100, 1) + " %",
                     "да" if n >= need else "нет"])
table(["Сценарий", "Момент", "Недель набора (минус 7 дней наблюдения)", "Поток, групп/нед.", "Групп на вариант",
       "Наименьшая обнаружимая доля (от 12 %)", f"Хватает для 3 п.п. ({need} на вариант)"], rows)

Path(__file__).with_suffix(".md").write_text("\n".join(OUT) + "\n", encoding="utf-8")
emit(f"Сохранено: {Path(__file__).with_suffix('.md')}")
