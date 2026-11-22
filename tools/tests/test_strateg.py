import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch


STRATEG = Path(__file__).resolve().parents[1] / "strateg.py"


class StrategTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.root.joinpath("AGENTS.md").write_text("# Временный проект\n", encoding="utf-8")
        self.script = self.root / "tools" / "strateg.py"
        self.script.parent.mkdir()
        shutil.copyfile(STRATEG, self.script)
        self.cwd = self.root / "nested"
        self.cwd.mkdir()
        self.project = self.root / "projects" / "demo"
        self.env = os.environ.copy()
        self.env.pop("CLAUDE_PROJECT_DIR", None)
        self.env["PYTHONDONTWRITEBYTECODE"] = "1"
        self.env["PYTHONIOENCODING"] = "utf-8"

    def run_cli(self, *args, code=0):
        result = subprocess.run(
            [sys.executable, str(self.script), *args],
            cwd=self.cwd,
            env=self.env,
            capture_output=True,
            encoding="utf-8",
            timeout=15,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            code,
            f"{args!r}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )
        return result

    def cli(self, *args, code=0):
        return self.run_cli(*args, code=code).stdout

    def load_api(self):
        return runpy.run_path(str(self.script))

    def decision_args(self, *extra):
        return (
            "decisions", "add", "--decision", "Пересмотреть", "--owner", "Команда",
            "--metric", "Выпуск", "--review-condition", "Падение выпуска", *extra,
        )

    def state(self):
        return json.loads(self.project.joinpath("state.json").read_text(encoding="utf-8"))

    def records(self, name):
        lines = self.project.joinpath(name).read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines]

    def assert_timestamp(self, value):
        parsed = datetime.fromisoformat(value)
        self.assertIsNotNone(parsed.utcoffset())
        self.assertEqual(value, parsed.isoformat(timespec="seconds"))

    def test_project_workflow(self):
        self.cli("new", "demo", "--title", "Стратегия поставок")
        active = self.root / "projects" / "ACTIVE"
        self.assertEqual(active.read_text(encoding="utf-8").strip(), "demo")
        self.assertEqual(self.state()["steps"][0]["status"], "in_progress")
        self.assert_timestamp(self.state()["created"])
        report = self.project / "outputs" / "report.md"
        report.touch()
        self.cli("step", "intake", "done", "--note", "Задача согласована", "--outputs", "outputs/report.md")
        step = self.state()["steps"][0]
        self.assertEqual(step["status"], "done")
        self.assertEqual(step["outputs"], ["outputs/report.md"])
        self.assert_timestamp(step["finished"])

        source_args = ("source", "add", "--type", "document", "--title", "Отчёт", "--ref", "report.txt")
        self.assertEqual(self.cli(*source_args).strip(), "S-001")
        self.assertEqual(self.cli(*source_args).strip(), "S-001")
        self.assertEqual(len(self.records("sources.jsonl")), 1)
        self.cli("evidence", "add", "--kind", "fact", "--text", "Поставки выросли", "--sources", "S-001")
        self.assertEqual(self.records("evidence.jsonl")[0]["id"], "E-001")

        report.write_text("Поставки выросли [E-001, S-001].\nНет ссылки [E-999].\n", encoding="utf-8")
        diagnostics = self.cli("check", code=1)
        self.assertIn("ОШИБКА", diagnostics)
        self.assertIn("report.md:2", diagnostics)
        self.assertIn("E-999", diagnostics)
        for name in ("sources.md", "evidence.md", "STATUS.md"):
            self.assertTrue(self.project.joinpath(name).is_file(), name)

        report.write_text("Поставки выросли [E-001, S-001].\n", encoding="utf-8")
        self.cli("check")
        self.cli(
            "decisions", "add", "--decision", "Изменить график поставок", "--owner", "Команда",
            "--metric", "Срок", "--review-condition", "Срок увеличился", "--based-on", "E-001",
        )
        self.cli("revoke", "E-001", "--reason", "Получены уточнённые данные")
        evidence = self.records("evidence.jsonl")[0]
        self.assertEqual(evidence["status"], "revoked")
        self.assertEqual(evidence["text"], "Поставки выросли")
        self.assertIn("E-001", self.cli("impact", "S-001"))
        impact = self.cli("impact", "E-001")
        self.assertIn("report.md:1", impact)
        self.assertIn("D-001", impact)
        due = self.cli("decisions", "due")
        self.assertIn("D-001", due)
        self.assertIn("E-001", due)
        self.assertIn("E-001", self.cli("check", code=1))
        self.assertIn("~~", self.project.joinpath("evidence.md").read_text(encoding="utf-8"))

        usage = {
            "session_id": "сеанс-1",
            "total_cost_usd": 0.125,
            "duration_ms": 120000,
            "modelUsage": {
                "model": {
                    "inputTokens": 10, "outputTokens": 20, "cacheReadInputTokens": 30,
                    "cacheCreationInputTokens": 40, "costUSD": 0.125,
                },
            },
        }
        result_path = self.cwd / "result.json"
        result_path.write_text(json.dumps(usage, ensure_ascii=False), encoding="utf-8")
        self.cli("cost", "import", result_path.name, "--label", "Первый импорт")
        self.cli("cost", "import", result_path.name, "--label", "Повторный импорт")
        costs = self.records("costs.jsonl")
        self.assertEqual(len(costs), 1)
        cost = costs[0]
        self.assertEqual(cost["session"], "сеанс-1")
        self.assertEqual(cost["source"], "headless")
        self.assertEqual(cost["label"], "Повторный импорт")
        self.assertEqual(cost["duration_s"], 120)
        self.assertEqual(cost["cost_usd"], 0.125)
        self.assertEqual(cost["models"], {
            "model": {"input": 10, "output": 20, "cache_read": 30, "cache_write": 40, "cost_usd": 0.125},
        })
        self.assert_timestamp(cost["ts"])

        knowledge = self.root / "knowledge"
        knowledge.mkdir()
        knowledge.joinpath("поставки.md").write_text("Методика прогнозирования поставок.\n", encoding="utf-8")
        self.cli("evidence", "add", "--kind", "fact", "--text", "График поставок обновлён", "--sources", "S-001")
        self.cli("memory", "add", "--kind", "lesson", "--text", "Планирование поставок требует запаса")
        self.cli("memory", "add", "--kind", "lesson", "--text", "Устаревшее правило поставок")
        self.cli("memory", "revoke", "M-002", "--reason", "Правило отменено")
        results = self.cli("search", "ПОСТАВКИ")
        self.assertIn("поставки.md", results)
        self.assertIn("E-002", results)
        self.assertIn("M-001", results)
        self.assertIn("заметка агента, не факт", results)
        self.assertNotIn("M-002", results)
        self.assertNotIn("E-001", results)

    def test_gate_blocks_completion_and_redo_records_reason(self):
        self.cli("new", "demo", "--title", "Проект")
        self.cli("gate", "ask", "Какой вариант выбрать?", "--options", "А|Б", "--step", "intake")
        waiting = self.state()["waiting_for_human"]
        self.assertEqual(waiting["step"], "intake")
        self.assertEqual(waiting["options"], ["А", "Б"])
        self.assert_timestamp(waiting["since"])
        self.cli("step", "intake", "done", code=2)
        self.assertEqual(self.state()["steps"][0]["status"], "in_progress")
        self.cli("gate", "answer", "Б")
        state = self.state()
        self.assertIsNone(state["waiting_for_human"])
        self.assertEqual(state["gates"][0]["answer"], "Б")
        self.assert_timestamp(state["gates"][0]["answered"])
        self.cli("step", "intake", "done")
        self.cli("step", "intake", "start", code=2)
        self.cli("step", "intake", "start", "--redo", "--note", "Поступили новые вводные")
        self.assertEqual(self.state()["steps"][0]["status"], "in_progress")
        self.assertIn("Поступили новые вводные", self.cli("journal", "--tail", "1"))

    def test_template_and_hook_functions(self):
        configured = self.root / "configured"
        template = configured / "projects" / "_template"
        template.parent.mkdir(parents=True)
        configured.joinpath("AGENTS.md").write_text("# Другой корень\n", encoding="utf-8")
        shutil.copytree(STRATEG.parents[1] / "projects" / "_template", template)
        template_state = json.loads(template.joinpath("state.json").read_text(encoding="utf-8"))
        self.assertEqual(len(template_state["steps"]), 9)
        self.assertTrue(all(step["status"] == "pending" for step in template_state["steps"]))
        self.env["CLAUDE_PROJECT_DIR"] = str(configured)
        self.cli("new", "from-template", "--title", "Из шаблона")
        self.cli("new", "other", "--title", "Другой проект")
        self.cli("use", "from-template")
        self.assertIn("from-template | Из шаблона | intake", self.cli("projects"))
        project = configured / "projects" / "from-template"
        for folder in ("materials", "outputs", "analysis"):
            self.assertTrue((project / folder / ".gitkeep").is_file())
        self.assertFalse(self.project.exists())

        api = self.load_api()
        with patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(configured)}):
            self.assertEqual(api["find_root"](), configured.resolve())
            self.assertEqual(api["active_project"](), project.resolve())
        api["append_journal"](project, {"event": "note", "note": "Проверка хука"})
        self.assertIn("Проверка хука", self.cli("journal", "--tail", "1"))
        cost = {
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "session": "test", "source": "stop-hook", "label": "Из хука",
            "duration_s": 60, "cost_usd": 0.5, "models": {},
        }
        api["upsert_cost"](project, cost)
        api["upsert_cost"](project, {**cost, "cost_usd": 1.25})
        status = json.loads(self.cli("status", "--json"))
        self.assertEqual(status["cost_usd"], 1.25)
        self.assertEqual(status["duration_s"], 60)
        rendered = api["status_text"](project)
        self.assertLessEqual(len(rendered), 2500)
        self.assertEqual(self.cli("status").rstrip(), rendered)
        self.assertEqual(project.joinpath("STATUS.md").read_text(encoding="utf-8"), rendered + "\n")

    def test_check_reports_jsonl_errors_and_paragraph_warnings(self):
        self.cli("new", "demo", "--title", "Проверка")
        for source_type in ("synthetic", "document", "calc"):
            self.cli("source", "add", "--type", source_type, "--title", source_type, "--ref", source_type)
        self.cli("evidence", "add", "--kind", "fact", "--text", "Ответ модели", "--sources", "S-001")
        self.cli("evidence", "add", "--kind", "synthetic", "--text", "Реальные данные", "--sources", "S-002")
        evidence = self.project / "evidence.jsonl"
        with evidence.open("a", encoding="utf-8") as stream:
            stream.write("{оборванная строка\n")
        outputs = self.project / "outputs" / "report.md"
        outputs.write_text(
            "Показатель составил 125 единиц.\n"
            "Данные из отчёта [S-002].\n\n"
            "Выпуск достиг 5 млн.\n\n"
            "Допущение: выпуск составит 999 единиц.\n",
            encoding="utf-8",
        )
        self.cli(
            "decisions", "add", "--decision", "Пересмотреть", "--owner", "Команда", "--metric", "Выпуск",
            "--review-condition", "Падение выпуска", "--review-date", "2000-01-01",
        )
        diagnostics = self.cli("check", code=1)
        self.assertIn("evidence.jsonl:1", diagnostics)
        self.assertIn("evidence.jsonl:2", diagnostics)
        self.assertIn("evidence.jsonl:3", diagnostics)
        self.assertIn("ПРЕДУПРЕЖДЕНИЕ: outputs/report.md:4", diagnostics)
        self.assertNotIn("report.md:1", diagnostics)
        self.assertNotIn("report.md:6", diagnostics)
        self.assertIn("sources.jsonl:3", diagnostics)
        self.assertIn("decisions.jsonl:1", diagnostics)
        for name in ("sources.md", "evidence.md", "STATUS.md"):
            self.assertFalse((self.project / name).exists(), name)
        first_row = json.loads(evidence.read_text(encoding="utf-8").splitlines()[0])
        evidence.write_text(json.dumps({**first_row, "kind": "synthetic"}) + "\n", encoding="utf-8")
        diagnostics = self.cli("check")
        self.assertIn("ПРЕДУПРЕЖДЕНИЕ", diagnostics)
        self.assertNotIn("ОШИБКА", diagnostics)
        self.assertNotIn("sources.jsonl:2", diagnostics)

    def test_step_requires_in_progress_and_existing_project_outputs(self):
        self.cli("new", "demo", "--title", "Проверка")
        original = self.state()
        self.assertIn("pending", self.run_cli("step", "collect", "done", code=2).stderr)
        report = self.project / "outputs" / "report.md"
        report.touch()
        (self.cwd / "outside.md").touch()
        result = self.run_cli(
            "step", "intake", "done", "--outputs",
            f"outputs/report.md, outputs/missing.md, other.md, ../../nested/outside.md, {report}", code=2,
        )
        for item in ("outputs/missing.md", "other.md", "../../nested/outside.md", str(report)):
            self.assertIn(item, result.stderr)
        self.assertNotIn(": outputs/report.md", result.stderr)
        self.assertEqual(self.state(), original)
        self.cli("step", "intake", "done", "--outputs", "outputs/report.md")
        self.assertIn("done", self.run_cli("step", "intake", "done", code=2).stderr)
        finished = self.state()["steps"][0]["finished"]
        self.cli("step", "intake", "block")
        self.assertIn("blocked", self.run_cli("step", "intake", "done", code=2).stderr)
        self.assertEqual(self.state()["steps"][0]["finished"], finished)
        self.assertIn("--redo", self.run_cli("step", "intake", "start", code=2).stderr)
        self.cli("step", "intake", "start", "--redo")
        self.assertIn("--redo", self.run_cli("step", "intake", "start", code=2).stderr)

    def test_gate_prevents_starting_another_step_and_answer_is_idempotent(self):
        self.cli("new", "demo", "--title", "Проверка")
        self.assertIn("Нет открытого вопроса", self.cli("gate", "answer", "Первый вызов"))
        self.cli("gate", "ask", "Продолжаем?", "--step", "intake")
        self.cli("step", "intake", "start")
        state = self.state()
        blocked = self.run_cli("step", "collect", "start", "--redo", code=2)
        self.assertIn("gate answer", blocked.stderr)
        self.assertIn("intake", blocked.stderr)
        self.assertEqual(self.state(), state)
        self.cli("gate", "answer", "Продолжаем")
        self.cli("gate", "ask", "Куда?")
        self.cli("gate", "answer", "К расчётам")
        state = self.state()
        journal = self.records("journal.jsonl")
        duplicate = self.cli("gate", "answer", "Дублирующий ответ")
        self.assertIn("Нет открытого вопроса", duplicate)
        self.assertIn("К расчётам", duplicate)
        self.assertNotIn("Продолжаем", duplicate)
        self.assertNotIn("Дублирующий ответ", duplicate)
        self.assertEqual(self.state(), state)
        self.assertEqual(self.records("journal.jsonl"), journal)
        self.cli("step", "collect", "start")

    def test_check_citations_and_synthetic_paragraphs(self):
        self.cli("new", "demo", "--title", "Проверка")
        self.cli("source", "add", "--type", "synthetic", "--title", "Модель", "--ref", "model")
        self.cli("source", "add", "--type", "document", "--title", "Отчёт", "--ref", "report")
        self.cli("evidence", "add", "--kind", "synthetic", "--text", "Ответ модели", "--sources", "S-001")
        self.cli("evidence", "add", "--kind", "fact", "--text", "Реальные данные", "--sources", "S-002")
        report = self.project / "outputs" / "report.md"
        valid = (
            "Результаты СИНТЕТИЧЕСКИЕ.\n"
            "Ответы [E-001, E-002; S-001].\n\n"
            "Пример `[E-99]` и ``[E-999] ` [S-1]``.\n\n"
            "Пример на двух строках `[E-999]\n"
            "и [S-999]`.\n\n"
            "```markdown\n"
            "[E-999] [S-1] 123\n"
            "```\n"
            "Данные [E-002; S-002].\n"
            "\nПометка `синтетический` относится к ответу [E-001].\n"
        )
        report.write_text(valid, encoding="utf-8")
        self.assertNotIn("report.md:", self.cli("check"))
        report.write_text(
            valid + "\nСмешанная ссылка [E-002; S-999].\n\n"
            "Ссылки [E-99], [S-1] и [E-0001x].\n\n"
            "Ответ [E-001].\n\nСИНТЕТИЧЕСКИЙ пример отдельно.\n\n"
            "Источник [S-001].\n",
            encoding="utf-8",
        )
        diagnostics = self.cli("check", code=1)
        for marker in ("[E-99]", "[S-1]", "[E-0001x]"):
            self.assertIn(f"неверный формат ссылки {marker}", diagnostics)
        self.assertIn("несуществующую запись S-999", diagnostics)
        self.assertIn("синтетика без пометки (E-001)", diagnostics)
        self.assertIn("синтетика без пометки (S-001)", diagnostics)
        self.assertNotIn("E-999", diagnostics)

    def test_check_decision_evidence_and_missing_registries(self):
        self.cli("new", "demo", "--title", "Проверка")
        self.cli(*self.decision_args("--based-on", "E-401,E-402"))
        diagnostics = self.cli("check", code=1)
        for identifier in ("E-401", "E-402"):
            self.assertIn(f"основание {identifier} не существует в evidence.jsonl", diagnostics)
        for name in ("sources.jsonl", "evidence.jsonl", "decisions.jsonl"):
            path = self.project / name
            original = path.read_bytes()
            with self.subTest(registry=name):
                path.unlink()
                self.assertIn(f"ОШИБКА: {name} — файл не найден", self.cli("check", code=1))
            path.write_bytes(original)

    def test_check_keeps_generated_files_on_bad_registry_or_state(self):
        self.cli("new", "demo", "--title", "Проверка")
        self.cli("check")
        views = [self.project / name for name in ("sources.md", "evidence.md", "STATUS.md")]
        sentinel = b"existing view\n"
        for view in views:
            view.write_bytes(sentinel)
        for name, raw, problem in (
            ("sources.jsonl", b"{\n", "некорректный JSON"),
            ("decisions.jsonl", b"{}\n", "отсутствует поле"),
            ("state.json", b"{\n", "некорректный JSON (столбец 1)"),
            ("state.json", b"[]\n", "ожидается объект JSON"),
            ("state.json", b"{}\n", "отсутствует поле «id»"),
        ):
            with self.subTest(name=name, raw=raw):
                path = self.project / name
                original = path.read_bytes()
                path.write_bytes(raw)
                diagnostics = self.cli("check", code=1)
                self.assertIn(name, diagnostics)
                self.assertIn(problem, diagnostics)
                self.assertEqual([view.read_bytes() for view in views], [sentinel] * 3)
                path.write_bytes(original)
        state = self.state()
        state["steps"][0]["status"] = "incorrect"
        (self.project / "state.json").write_text(json.dumps(state), encoding="utf-8")
        self.assertIn("steps, запись 1: недопустимое значение поля «status»", self.cli("check", code=1))
        (self.project / "state.json").unlink()
        self.assertIn("ОШИБКА: state.json — файл не найден", self.cli("check", code=1))
        self.assertEqual([view.read_bytes() for view in views], [sentinel] * 3)

    def test_check_warns_about_corrupted_journal_and_cost_lines(self):
        self.cli("new", "demo", "--title", "Проверка")
        self.cli("log", "note", "Запись перед повреждённой строкой")
        with (self.project / "journal.jsonl").open("ab") as stream:
            stream.write(b"{\n")
        (self.project / "costs.jsonl").write_bytes(b"\xff\n")
        diagnostics = self.cli("check")
        self.assertIn("ПРЕДУПРЕЖДЕНИЕ: journal.jsonl:2", diagnostics)
        self.assertIn("ПРЕДУПРЕЖДЕНИЕ: costs.jsonl:1", diagnostics)
        self.assertNotIn("ОШИБКА", diagnostics)
        self.assertTrue((self.project / "STATUS.md").is_file())

    def test_impact_unknown_ids_and_decisions_due(self):
        self.cli("new", "demo", "--title", "Проверка")
        for identifier in ("S-999", "E-999"):
            result = self.run_cli("impact", identifier, code=2)
            self.assertIn(identifier, result.stderr)
            self.assertIn("не найдена", result.stderr)
        self.cli("evidence", "add", "--kind", "assumption", "--text", "Допущение", "--sources", "")
        self.cli("revoke", "E-001", "--reason", "Уточнение")
        today = date.today()
        for day, based_on in (
            (today.isoformat(), ""), ((today - timedelta(days=1)).isoformat(), ""),
            ((today + timedelta(days=2)).isoformat(), ""), ("", "E-001"), ("", "E-001"),
        ):
            self.cli(*self.decision_args("--review-date", day, "--based-on", based_on))
        decisions = self.records("decisions.jsonl")
        decisions[1]["status"] = "revised"
        decisions[3]["status"] = "cancelled"
        (self.project / "decisions.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in decisions), encoding="utf-8",
        )
        due = self.cli("decisions", "due")
        self.assertIn("D-001", due)
        self.assertIn(today.isoformat(), due)
        self.assertIn("D-005", due)
        self.assertIn("E-001", due)
        for identifier in ("D-002", "D-003", "D-004"):
            self.assertNotIn(identifier, due)

    def test_parallel_additions_allocate_unique_ids_and_deduplicate_sources(self):
        self.cli("new", "demo", "--title", "Проверка")

        def add_source(ref):
            return self.cli("source", "add", "--type", "document", "--title", "Отчёт", "--ref", ref).strip()

        def add_evidence(index):
            return self.cli(
                "evidence", "add", "--kind", "fact", "--text", f"Факт {index}", "--sources", "S-001",
            ).strip()

        with ThreadPoolExecutor(max_workers=8) as pool:
            source_ids = list(pool.map(add_source, ["a", "a", "b", "a", "b", "c", "d", "c"]))
            evidence_ids = list(pool.map(add_evidence, range(8)))
        self.assertEqual(source_ids[0], source_ids[1])
        self.assertEqual(source_ids[0], source_ids[3])
        self.assertEqual(source_ids[2], source_ids[4])
        self.assertEqual(source_ids[5], source_ids[7])
        self.assertEqual(sorted(set(source_ids)), [f"S-{index:03d}" for index in range(1, 5)])
        self.assertEqual(len(self.records("sources.jsonl")), 4)
        self.assertEqual(sorted(evidence_ids), [f"E-{index:03d}" for index in range(1, 9)])
        self.assertEqual(len(self.records("evidence.jsonl")), 8)

    def test_write_commands_do_not_modify_files_after_lock_timeout(self):
        self.cli("new", "demo", "--title", "Проверка")
        source = ("source", "add", "--type", "document", "--title", "Отчёт", "--ref", "report")
        evidence = ("evidence", "add", "--kind", "fact", "--text", "Факт", "--sources", "S-001")
        memory = ("memory", "add", "--kind", "lesson", "--text", "Заметка")
        for command in (source, evidence, memory):
            self.cli(*command)
        self.cli("gate", "ask", "Продолжать?", "--step", "intake")
        api = self.load_api()
        parser = api["make_parser"]()
        init = api["file_lock"].__init__

        def without_wait(lock, path, timeout=5.0):
            init(lock, path, timeout=0)

        active = self.root / "projects" / "ACTIVE"
        notes = self.root / "memory" / "notes.jsonl"
        cases = (
            (active, ("new", "other", "--title", "Проверка")),
            (self.project / "state.json", ("step", "intake", "start")),
            (self.project / "state.json", ("gate", "ask", "Куда?")),
            (self.project / "state.json", ("gate", "answer", "Да")),
            (self.project / "sources.jsonl", source),
            (self.project / "evidence.jsonl", evidence),
            (self.project / "evidence.jsonl", ("revoke", "E-001", "--reason", "Уточнение")),
            (self.project / "decisions.jsonl", self.decision_args()),
            (notes, memory),
            (notes, ("memory", "revoke", "M-001", "--reason", "Уточнение")),
        )
        with patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(self.root)}):
            for path, command in cases:
                with self.subTest(command=command), api["file_lock"](path):
                    original = path.read_bytes()
                    args = parser.parse_args(command)
                    with patch.object(api["file_lock"], "__init__", without_wait):
                        with self.assertRaisesRegex(api["CliError"], "Повторите команду"):
                            args.handler(args)
                    self.assertEqual(path.read_bytes(), original)
        self.assertFalse((self.project.parent / "other").exists())

    def test_lock_staleness_and_best_effort_journal(self):
        self.cli("new", "demo", "--title", "Проверка")
        api = self.load_api()
        journal = self.project / "journal.jsonl"
        lock_file = self.project / "journal.jsonl.lock"
        lock_file.touch()
        timestamp = time.time() - 20
        os.utime(lock_file, (timestamp, timestamp))
        with self.assertRaises(api["CliError"]):
            with api["file_lock"](journal, timeout=0):
                self.fail("Недавнюю блокировку захватили повторно")
        init = api["file_lock"].__init__
        with patch.object(api["file_lock"], "__init__", lambda lock, path: init(lock, path, timeout=0)):
            api["append_journal"](self.project, {"event": "note", "note": "Событие при блокировке"})
        self.assertTrue(lock_file.exists())
        self.assertEqual(self.records("journal.jsonl")[-1]["note"], "Событие при блокировке")
        timestamp = time.time() - 31
        os.utime(lock_file, (timestamp, timestamp))
        with api["file_lock"](journal, timeout=0):
            self.assertGreater(lock_file.stat().st_mtime, timestamp)
        self.assertFalse(lock_file.exists())

    def test_cost_upsert_preserves_corruption_and_prefers_headless(self):
        self.cli("new", "demo", "--title", "Проверка")
        api = self.load_api()
        costs = self.project / "costs.jsonl"
        prefix = b"{invalid}\r\n{}\n"
        suffix = b"\xff broken final line"
        costs.write_bytes(prefix + suffix)
        stop = {
            "session": "same", "source": "stop-hook", "label": "Из хука",
            "duration_s": 60, "cost_usd": 0.5, "models": {},
        }
        api["upsert_cost"](self.project, stop)
        headless = {**stop, "source": "headless", "label": "Импорт", "cost_usd": 0.125}
        api["upsert_cost"](self.project, headless)
        raw = costs.read_bytes()
        self.assertTrue(raw.startswith(prefix))
        self.assertTrue(raw.endswith(suffix))
        self.assertEqual(len(raw.split(b"\n")), 4)
        imported = json.loads(raw.split(b"\n")[2])
        self.assertEqual({key: imported[key] for key in headless}, headless)
        api["upsert_cost"](self.project, {**stop, "cost_usd": 3.0})
        self.assertEqual(costs.read_bytes(), raw)
        for command in (("status", "--json"), ("cost",)):
            result = self.run_cli(*command)
            for line in (1, 2, 4):
                self.assertIn(f"ПРЕДУПРЕЖДЕНИЕ: costs.jsonl:{line}", result.stderr)
            if command[0] == "status":
                data = json.loads(result.stdout)
                self.assertEqual(data["cost_usd"], 0.125)
                self.assertEqual(data["duration_s"], 60)
            else:
                self.assertIn("0.125000 USD", result.stdout)

    def test_cost_import_requires_force_for_error_and_names_unreadable_results(self):
        self.cli("new", "demo", "--title", "Проверка")
        result = self.cwd / "result.json"
        missing = self.run_cli("cost", "import", result.name, code=2)
        self.assertIn(result.name, missing.stderr)
        self.assertIn("не найден", missing.stderr)
        result.write_bytes(b"{\n")
        invalid = self.run_cli("cost", "import", result.name, "--force", code=2)
        self.assertIn(f"{result.name}:2", invalid.stderr)
        self.assertIn("некорректный JSON", invalid.stderr)
        result.write_text(json.dumps({
            "is_error": True, "session_id": "error-session", "total_cost_usd": 0.125, "duration_ms": 1000,
        }), encoding="utf-8")
        self.assertIn("--force", self.run_cli("cost", "import", result.name, code=2).stderr)
        self.assertEqual(self.records("costs.jsonl"), [])
        self.cli("cost", "import", result.name, "--force")
        self.assertEqual(self.records("costs.jsonl")[0]["session"], "error-session")

    def test_find_root_prefers_config_then_script_then_nearest_cwd(self):
        self.cwd.joinpath("AGENTS.md").touch()
        nested = self.cwd / "more"
        nested.mkdir()
        configured = self.root / "configured"
        configured.mkdir()
        configured.joinpath("AGENTS.md").touch()
        missing = self.root / "invalid-config"
        detached = self.root / "isolated" / "tools" / "strateg.py"
        detached.parent.mkdir(parents=True)
        shutil.copyfile(self.script, detached)
        with (
            patch.object(Path, "cwd", return_value=nested),
            patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(configured)}),
        ):
            self.assertEqual(self.load_api()["find_root"](), configured.resolve())
        with (
            patch.object(Path, "cwd", return_value=nested),
            patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(missing)}),
        ):
            self.assertEqual(self.load_api()["find_root"](), self.root.resolve())
            self.assertEqual(runpy.run_path(str(detached))["find_root"](), self.cwd.resolve())

    def test_new_id_format_and_case_insensitive_collision(self):
        self.cli("new", "demo", "--title", "Проверка")
        for identifier in ("", "Demo", "проект", "-demo", "a_b", "a.b", "a/b", "a" * 41):
            with self.subTest(identifier=identifier):
                result = self.run_cli("new", "--title", "Проверка", "--", identifier, code=2)
                self.assertIn("Идентификатор проекта", result.stderr)
        projects = self.root / "projects"
        (projects / "LeGaCy").mkdir()
        result = self.run_cli("new", "legacy", "--title", "Проверка", code=2)
        self.assertIn("уже существует", result.stderr)
        self.assertEqual((projects / "ACTIVE").read_text(encoding="utf-8").strip(), "demo")
        self.cli("new", "7" + "z" * 38 + "-", "--title", "Предельная длина")
        self.cli("new", "x", "--title", "Один символ")

    def test_append_journal_redacts_absolute_root_in_target_and_note(self):
        self.cli("new", "demo", "--title", "Проверка")
        root = self.root.resolve().as_posix().swapcase()
        backslash_root = root.replace("/", "\\")
        event = {
            "event": "note", "tool": root,
            "target": f"{root}/outputs/report.md, {backslash_root}\\state.json",
            "note": f"Корень {backslash_root} и {root}",
        }
        self.load_api()["append_journal"](self.project, event)
        row = self.records("journal.jsonl")[-1]
        self.assertEqual(row["target"], "./outputs/report.md, .\\state.json")
        self.assertEqual(row["note"], "Корень . и .")
        self.assertEqual(row["tool"], root)
        self.assertIn(root, event["target"])


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    unittest.main()
