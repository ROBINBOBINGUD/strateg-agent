"""Тест MCP-сервера: рукопожатие, список инструментов, вызов, ошибки. Сервер ничего не пишет в реестры."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


class McpServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="strateg-mcp-"))
        shutil.copytree(REPO / "tools", self.tmp / "tools", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(REPO / "projects" / "_template", self.tmp / "projects" / "_template")
        (self.tmp / "AGENTS.md").write_text("# test\n", encoding="utf-8")
        (self.tmp / "memory").mkdir()
        (self.tmp / "knowledge").mkdir()
        self.env = dict(os.environ, CLAUDE_PROJECT_DIR=str(self.tmp), PYTHONIOENCODING="utf-8")
        cli = [sys.executable, str(self.tmp / "tools" / "strateg.py")]
        subprocess.run(cli + ["new", "demo", "--title", "Проверка MCP"], cwd=self.tmp, env=self.env, capture_output=True)
        subprocess.run(cli + ["source", "add", "--type", "document", "--title", "Бриф", "--ref", "materials/b.md",
                              "--reliability", "A"], cwd=self.tmp, env=self.env, capture_output=True)
        subprocess.run(cli + ["evidence", "add", "--kind", "fact", "--text", "Активных групп 4000",
                              "--sources", "S-001"], cwd=self.tmp, env=self.env, capture_output=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def talk(self, messages):
        payload = "".join(json.dumps(m, ensure_ascii=False) + "\n" for m in messages).encode("utf-8")
        result = subprocess.run([sys.executable, str(self.tmp / "tools" / "mcp_server.py")], input=payload,
                                cwd=self.tmp, env=self.env, capture_output=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        replies = [json.loads(line) for line in result.stdout.decode("utf-8").splitlines() if line.strip()]
        return {reply["id"]: reply for reply in replies}

    def test_handshake_tools_and_calls(self):
        before = (self.tmp / "projects" / "demo" / "evidence.jsonl").read_bytes()
        replies = self.talk([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "strateg_status", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
             "params": {"name": "strateg_impact", "arguments": {"id": "S-001"}}},
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
             "params": {"name": "strateg_impact", "arguments": {"id": "E-777"}}},
            {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "delete_everything", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 7, "method": "resources/list"},
        ])
        self.assertEqual(len(replies), 7)  # уведомление без id остаётся без ответа
        self.assertEqual(replies[1]["result"]["serverInfo"]["name"], "strateg")
        tools = replies[2]["result"]["tools"]
        self.assertEqual(len(tools), 6)
        self.assertTrue(all(tool["annotations"]["readOnlyHint"] for tool in tools))
        self.assertIn("Проверка MCP", replies[3]["result"]["content"][0]["text"])
        self.assertFalse(replies[3]["result"]["isError"])
        self.assertIn("E-001", replies[4]["result"]["content"][0]["text"])
        self.assertTrue(replies[5]["result"]["isError"])       # несуществующая запись — ошибка инструмента
        self.assertEqual(replies[6]["error"]["code"], -32602)   # неизвестный инструмент
        self.assertEqual(replies[7]["error"]["code"], -32601)   # неподдерживаемый метод
        self.assertEqual(before, (self.tmp / "projects" / "demo" / "evidence.jsonl").read_bytes())


if __name__ == "__main__":
    unittest.main()
