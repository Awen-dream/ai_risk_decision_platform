from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError
from urllib.request import Request

from cli import ApiClient, main


class _FakeResponse:
    def __init__(self, payload) -> None:
        self._buffer = io.BytesIO(json.dumps(payload).encode("utf-8"))
        self.status = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._buffer.close()

    def read(self, *args, **kwargs):
        return self._buffer.read(*args, **kwargs)


class CliTests(unittest.TestCase):
    def test_api_client_invokes_agent(self) -> None:
        client = ApiClient("http://127.0.0.1:8000")
        payload = {"session_id": "s1", "agent_name": "knowledge"}

        with patch("cli.urlopen", return_value=_FakeResponse(payload)) as mocked:
            result = client.invoke_agent(
                "knowledge",
                "营销套利案件的标准排查 SOP 是什么？",
                session_id="s1",
                context={"country": "BR"},
            )

        self.assertEqual(result["agent_name"], "knowledge")
        request = mocked.call_args[0][0]
        self.assertIsInstance(request, Request)
        self.assertIn("/agents/knowledge", request.full_url)

    def test_api_client_sends_admin_header(self) -> None:
        client = ApiClient(
            "http://127.0.0.1:8000",
            headers={"X-Admin-Token": "secret"},
        )

        with patch("cli.urlopen", return_value=_FakeResponse({"status": "ok"})) as mocked:
            client.runtime_info()

        request = mocked.call_args[0][0]
        self.assertEqual(request.headers["X-admin-token"], "secret")

    def test_main_healthz_prints_json(self) -> None:
        with patch("cli.urlopen", return_value=_FakeResponse({"status": "ok"})):
            with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                exit_code = main(["--base-url", "http://127.0.0.1:8000", "healthz"])

        self.assertEqual(exit_code, 0)
        self.assertIn('"status": "ok"', stdout.getvalue())

    def test_main_reads_admin_token_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            token_path = Path(tmp_dir) / "admin-token"
            token_path.write_text("file-admin-secret\n", encoding="utf-8")
            with patch("cli.urlopen", return_value=_FakeResponse({"status": "ok"})) as mocked:
                with patch("sys.stdout", new_callable=io.StringIO):
                    exit_code = main(
                        [
                            "--base-url",
                            "http://127.0.0.1:8000",
                            "--admin-token-file",
                            str(token_path),
                            "runtime",
                        ]
                    )

        self.assertEqual(exit_code, 0)
        request = mocked.call_args[0][0]
        self.assertEqual(request.headers["X-admin-token"], "file-admin-secret")

    def test_main_ask_builds_context(self) -> None:
        response_payload = {"session_id": "s1", "agent_name": "investigation"}

        with patch("cli.urlopen", return_value=_FakeResponse(response_payload)) as mocked:
            with patch("sys.stdout", new_callable=io.StringIO):
                exit_code = main(
                    [
                        "--base-url",
                        "http://127.0.0.1:8000",
                        "ask",
                        "investigation",
                        "请分析这个订单为什么被判高风险",
                        "--order-id",
                        "O10001",
                        "--country",
                        "BR",
                    ]
                )

        self.assertEqual(exit_code, 0)
        request = mocked.call_args[0][0]
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body["context"]["order_id"], "O10001")
        self.assertEqual(body["context"]["country"], "BR")

    def test_main_handles_connection_error(self) -> None:
        with patch("cli.urlopen", side_effect=URLError("connection refused")):
            with patch("sys.stderr", new_callable=io.StringIO) as stderr:
                exit_code = main(["--base-url", "http://127.0.0.1:8000", "runtime"])

        self.assertEqual(exit_code, 1)
        self.assertIn("make run-local-stack", stderr.getvalue())

    def test_main_debug_logs_request_and_response(self) -> None:
        response_payload = {"session_id": "s1", "agent_name": "strategy"}

        with patch("cli.urlopen", return_value=_FakeResponse(response_payload)):
            with patch("sys.stdout", new_callable=io.StringIO):
                with patch("sys.stderr", new_callable=io.StringIO) as stderr:
                    exit_code = main(
                        [
                            "--base-url",
                            "http://127.0.0.1:8000",
                            "--debug",
                            "ask",
                            "strategy",
                            "请评估策略 STRAT-001 是否应该调整阈值",
                            "--strategy-id",
                            "STRAT-001",
                        ]
                    )

        self.assertEqual(exit_code, 0)
        debug_output = stderr.getvalue()
        self.assertIn("[debug] POST http://127.0.0.1:8000/agents/strategy", debug_output)
        self.assertIn('"strategy_id": "STRAT-001"', debug_output)
        self.assertIn('[debug] response status: 200', debug_output)

    def test_main_graph_agent_builds_entity_context(self) -> None:
        response_payload = {"session_id": "s2", "agent_name": "graph"}

        with patch("cli.urlopen", return_value=_FakeResponse(response_payload)) as mocked:
            with patch("sys.stdout", new_callable=io.StringIO):
                exit_code = main(
                    [
                        "--base-url",
                        "http://127.0.0.1:8000",
                        "ask",
                        "graph",
                        "请分析用户 U10001 是否属于团伙网络",
                        "--entity-id",
                        "U10001",
                    ]
                )

        self.assertEqual(exit_code, 0)
        request = mocked.call_args[0][0]
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body["context"]["entity_id"], "U10001")

    def test_main_copilot_agent_accepts_mixed_context(self) -> None:
        response_payload = {"session_id": "s3", "agent_name": "copilot"}

        with patch("cli.urlopen", return_value=_FakeResponse(response_payload)) as mocked:
            with patch("sys.stdout", new_callable=io.StringIO):
                exit_code = main(
                    [
                        "--base-url",
                        "http://127.0.0.1:8000",
                        "ask",
                        "copilot",
                        "请联合分析订单 O10001 和策略 STRAT-001，判断是否存在团伙风险并给出策略建议",
                        "--order-id",
                        "O10001",
                        "--strategy-id",
                        "STRAT-001",
                        "--entity-id",
                        "U10001",
                    ]
                )

        self.assertEqual(exit_code, 0)
        request = mocked.call_args[0][0]
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body["context"]["order_id"], "O10001")
        self.assertEqual(body["context"]["strategy_id"], "STRAT-001")
        self.assertEqual(body["context"]["entity_id"], "U10001")


if __name__ == "__main__":
    unittest.main()
