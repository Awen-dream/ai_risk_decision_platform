from __future__ import annotations

from dataclasses import asdict, dataclass
from threading import Lock


@dataclass
class FaultRule:
    target_path: str
    status_code: int
    remaining: int
    delay_sec: float = 0.0


class FaultController:
    """Thread-safe, finite fault rules for explicit recovery drills."""

    def __init__(self) -> None:
        self._rules: dict[str, FaultRule] = {}
        self._lock = Lock()

    def configure(self, rule: FaultRule) -> FaultRule:
        with self._lock:
            self._rules[rule.target_path] = rule
            return FaultRule(**asdict(rule))

    def consume(self, path: str) -> FaultRule | None:
        with self._lock:
            rule = self._rules.get(path)
            if rule is None or rule.remaining <= 0:
                return None
            rule.remaining -= 1
            return FaultRule(**asdict(rule))

    def clear(self) -> None:
        with self._lock:
            self._rules.clear()

    def snapshot(self) -> list[dict[str, object]]:
        with self._lock:
            return [asdict(rule) for rule in self._rules.values()]
