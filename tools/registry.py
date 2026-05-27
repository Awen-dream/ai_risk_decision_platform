from __future__ import annotations

from collections.abc import Callable
from typing import Any

from adapters.base import ToolAdapter
from core.models import ToolResult


class ToolRegistry:
    """Simple registry for strongly named tools."""

    def __init__(self) -> None:
        self._tools: dict[str, Callable[..., ToolResult]] = {}

    def register(self, name: str, handler: Callable[..., ToolResult]) -> None:
        self._tools[name] = handler

    def register_adapter(self, adapter: ToolAdapter) -> None:
        self.register(adapter.name, adapter.invoke)

    def execute(self, name: str, **kwargs: Any) -> ToolResult:
        if name not in self._tools:
            return ToolResult(
                name=name,
                payload={},
                summary="工具未注册",
                success=False,
                error=f"Unknown tool: {name}",
            )
        return self._tools[name](**kwargs)

    def list_tools(self) -> list[str]:
        return list(self._tools)
