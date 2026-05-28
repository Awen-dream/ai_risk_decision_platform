from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, Optional, TextIO
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from settings import AppConfig


class ApiClient:
    """Small zero-dependency client for the local agent API."""

    def __init__(
        self,
        base_url: str,
        debug: bool = False,
        debug_stream: Optional[TextIO] = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._debug = debug
        self._debug_stream = debug_stream or sys.stderr

    def healthz(self) -> Dict[str, Any]:
        return self._get("/healthz")

    def list_agents(self) -> Dict[str, Any]:
        return self._get("/agents")

    def runtime_info(self) -> Dict[str, Any]:
        return self._get("/admin/runtime")

    def create_session(self) -> Dict[str, Any]:
        return self._post("/sessions", {})

    def get_session(self, session_id: str) -> Dict[str, Any]:
        return self._get(f"/sessions/{session_id}")

    def reload_knowledge(self) -> Dict[str, Any]:
        return self._post("/admin/knowledge/reload", {})

    def invoke_agent(
        self,
        agent_name: str,
        query: str,
        session_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        user_role: str = "risk_analyst",
    ) -> Dict[str, Any]:
        payload = {
            "query": query,
            "context": context or {},
            "user_role": user_role,
        }
        if session_id:
            payload["session_id"] = session_id
        return self._post(f"/agents/{agent_name}", payload)

    def _get(self, path: str) -> Dict[str, Any]:
        request = Request(f"{self._base_url}{path}", method="GET")
        self._log_request(request)
        with urlopen(request) as response:
            payload = json.load(response)
            self._log_response(getattr(response, "status", 200), payload)
            return payload

    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        data = json.dumps(payload).encode("utf-8")
        request = Request(
            f"{self._base_url}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        self._log_request(request, payload)
        with urlopen(request) as response:
            response_payload = json.load(response)
            self._log_response(getattr(response, "status", 200), response_payload)
            return response_payload

    def _log_request(self, request: Request, payload: Optional[Dict[str, Any]] = None) -> None:
        if not self._debug:
            return
        print(f"[debug] {request.get_method()} {request.full_url}", file=self._debug_stream)
        if payload is not None:
            print(
                f"[debug] request body: {json.dumps(payload, ensure_ascii=False)}",
                file=self._debug_stream,
            )

    def _log_response(self, status: int, payload: Dict[str, Any]) -> None:
        if not self._debug:
            return
        print(f"[debug] response status: {status}", file=self._debug_stream)
        print(
            f"[debug] response body: {json.dumps(payload, ensure_ascii=False)}",
            file=self._debug_stream,
        )


def build_parser() -> argparse.ArgumentParser:
    config = AppConfig.from_env()
    parser = argparse.ArgumentParser(description="CLI workbench for the AI risk decision platform.")
    parser.add_argument(
        "--base-url",
        default=f"http://{config.api_host}:{config.api_port}",
        help="Base URL of the agent API.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print HTTP request and response details to stderr.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("healthz", help="Check API health")
    subparsers.add_parser("agents", help="List registered agents")
    subparsers.add_parser("runtime", help="Inspect runtime configuration")
    subparsers.add_parser("create-session", help="Create a new session")
    subparsers.add_parser("reload-knowledge", help="Reload file-backed knowledge sources")

    session_parser = subparsers.add_parser("session", help="Inspect a session by ID")
    session_parser.add_argument("session_id")

    ask_parser = subparsers.add_parser("ask", help="Invoke an agent")
    ask_parser.add_argument("agent", choices=["knowledge", "investigation", "strategy"])
    ask_parser.add_argument("query", help="Natural language query")
    ask_parser.add_argument("--session-id", default=None)
    ask_parser.add_argument("--user-role", default="risk_analyst")
    ask_parser.add_argument("--country", default=None)
    ask_parser.add_argument("--channel", default=None)
    ask_parser.add_argument("--order-id", default=None)
    ask_parser.add_argument("--strategy-id", default=None)
    ask_parser.add_argument("--time-range", default=None)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    client = ApiClient(args.base_url, debug=args.debug)

    try:
        if args.command == "healthz":
            _print_json(client.healthz())
            return 0
        if args.command == "agents":
            _print_json(client.list_agents())
            return 0
        if args.command == "runtime":
            _print_json(client.runtime_info())
            return 0
        if args.command == "create-session":
            _print_json(client.create_session())
            return 0
        if args.command == "reload-knowledge":
            _print_json(client.reload_knowledge())
            return 0
        if args.command == "session":
            _print_json(client.get_session(args.session_id))
            return 0
        if args.command == "ask":
            context = {
                key: value
                for key, value in {
                    "country": args.country,
                    "channel": args.channel,
                    "order_id": args.order_id,
                    "strategy_id": args.strategy_id,
                    "time_range": args.time_range,
                }.items()
                if value
            }
            _print_json(
                client.invoke_agent(
                    agent_name=args.agent,
                    query=args.query,
                    session_id=args.session_id,
                    context=context,
                    user_role=args.user_role,
                )
            )
            return 0
    except HTTPError as exc:
        print(
            f"HTTP error from {args.base_url}: {exc.code} {exc.reason}",
            file=sys.stderr,
        )
        if args.debug:
            response_body = exc.read().decode("utf-8", errors="replace")
            print(f"[debug] error body: {response_body}", file=sys.stderr)
        return 1
    except URLError as exc:
        print(
            f"Unable to reach API at {args.base_url}: {exc.reason}. "
            "Start the local stack first with `make run-local-stack`.",
            file=sys.stderr,
        )
        if args.debug:
            print(f"[debug] url error: {exc!r}", file=sys.stderr)
        return 1

    parser.error(f"Unknown command: {args.command}")
    return 2


def _print_json(payload: Dict[str, Any]) -> None:
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    raise SystemExit(main())
