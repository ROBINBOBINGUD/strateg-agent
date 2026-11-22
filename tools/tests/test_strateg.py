import json
import os
from datetime import datetime
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


STRATEG = Path(__file__).resolve().parents[1] / "strateg.py"


class StrategTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.root.joinpath("AGENTS.md").write_text("# Временный проект\n", encoding="utf-8")
        self.cwd = self.root / "nested"
        self.cwd.mkdir()
        self.project = self.root / "projects" / "demo"
        self.env = os.environ.copy()
        self.env.pop("CLAUDE_PROJECT_DIR", None)
        self.env["PYTHONDONTWRITEBYTECODE"] = "1"
        self.env["PYTHONIOENCODING"] = "utf-8"

    def cli(self, *args, code=0):
        result = subprocess.run(
            [sys.executable, str(STRATEG), *args],
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
        return result.stdout

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
        self.cli("step", "intake", "done", "--note", "Задача согласована", "--outputs", "report.md")
        step = self.state()["steps"][0]
        self.assertEqual(step["status"], "done")
        self.assertEqual(step["outputs"], ["report.md"])
        self.assert_timestamp(step["finished"])

        source_args = ("source", "add", "--type", "document", "--title", "Отчёт", "--ref", "report.txt")
        self.assertEqual(self.cli(*source_args).strip(), "S-001")
        self.assertEqual(self.cli(*source_args).strip(), "S-001")
        self.assertEqual(len(self.records("sources.jsonl")), 1)
        self.cli("evidence", "add", "--kind", "fact", "--text", "Поставки выросли", "--sources", "S-001")
        self.assertEqual(self.records("evidence.jsonl")[0]["id"], "E-001")

        report = self.project / "outputs" / "report.md"
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
        self.cli("new", "проект", "--title", "Из шаблона")
        self.cli("new", "другой", "--title", "Другой проект")
        self.cli("use", "проект")
        self.assertIn("проект | Из шаблона | intake", self.cli("projects"))
        project = configured / "projects" / "проект"
        for folder in ("materials", "outputs", "analysis"):
            self.assertTrue((project / folder / ".gitkeep").is_file())
        self.assertFalse(self.project.exists())

        api = runpy.run_path(str(STRATEG))
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
        first_row = json.loads(evidence.read_text(encoding="utf-8").splitlines()[0])
        evidence.write_text(json.dumps({**first_row, "kind": "synthetic"}) + "\n", encoding="utf-8")
        diagnostics = self.cli("check")
        self.assertIn("ПРЕДУПРЕЖДЕНИЕ", diagnostics)
        self.assertNotIn("ОШИБКА", diagnostics)
        self.assertNotIn("sources.jsonl:2", diagnostics)


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    unittest.main()
