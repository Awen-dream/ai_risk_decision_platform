from __future__ import annotations

import json
import time
from dataclasses import dataclass
from threading import Lock
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from clients.base import (
    CaseRecordClient,
    GraphRelationClient,
    MetricSnapshotClient,
    OrderProfileClient,
    StrategyProfileClient,
    StrategySimulationClient,
)
from services.observability import current_headers, emit_event


class CircuitBreakerOpenError(RuntimeError):
    """Raised when an upstream request is rejected by the circuit breaker."""


@dataclass(frozen=True)
class HttpResiliencePolicy:
    retry_attempts: int = 2
    retry_backoff_sec: float = 0.1
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_reset_sec: float = 30.0

    def __post_init__(self) -> None:
        if self.retry_attempts < 0:
            raise ValueError("retry_attempts must be greater than or equal to 0")
        if self.retry_backoff_sec < 0:
            raise ValueError("retry_backoff_sec must be greater than or equal to 0")
        if self.circuit_breaker_failure_threshold < 1:
            raise ValueError("circuit_breaker_failure_threshold must be greater than or equal to 1")
        if self.circuit_breaker_reset_sec < 0:
            raise ValueError("circuit_breaker_reset_sec must be greater than or equal to 0")


class BaseHttpJsonClient:
    """Small configurable JSON-over-HTTP client."""

    def __init__(
        self,
        base_url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        timeout_sec: float = 5.0,
        resilience: Optional[HttpResiliencePolicy] = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = headers or {}
        self._timeout_sec = timeout_sec
        self._resilience = resilience or HttpResiliencePolicy()
        self._circuit_state = "closed"
        self._consecutive_failures = 0
        self._circuit_opened_at: Optional[float] = None
        self._circuit_lock = Lock()

    def _join_url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self._base_url}{path}"

    def _get_json(self, path: str) -> Any:
        url = self._join_url(path)
        self._ensure_circuit_allows_request(url)
        request_headers = {**self._headers, **current_headers()}
        request = Request(
            url,
            headers=request_headers,
            method="GET",
        )
        total_attempts = self._resilience.retry_attempts + 1
        for attempt in range(1, total_attempts + 1):
            emit_event(
                "upstream_http_request_started",
                upstream_url=url,
                method="GET",
                attempt=attempt,
                total_attempts=total_attempts,
            )
            try:
                with urlopen(request, timeout=self._timeout_sec) as response:
                    payload = json.load(response)
                    self._record_success(url)
                    emit_event(
                        "upstream_http_request_completed",
                        upstream_url=url,
                        method="GET",
                        status_code=getattr(response, "status", 200),
                        attempt=attempt,
                    )
                    return payload
            except HTTPError as exc:
                emit_event(
                    "upstream_http_request_failed",
                    upstream_url=url,
                    method="GET",
                    status_code=exc.code,
                    error_type="HTTPError",
                    error=str(exc),
                    attempt=attempt,
                )
                if not self._is_retryable_http_error(exc):
                    self._record_success(url)
                    raise
                if attempt == total_attempts:
                    self._record_failure(url)
                    raise
                self._backoff_before_retry(url, attempt, exc)
            except (URLError, TimeoutError) as exc:
                error = exc.reason if isinstance(exc, URLError) else str(exc)
                emit_event(
                    "upstream_http_request_failed",
                    upstream_url=url,
                    method="GET",
                    status_code=None,
                    error_type=type(exc).__name__,
                    error=str(error),
                    attempt=attempt,
                )
                if attempt == total_attempts:
                    self._record_failure(url)
                    raise
                self._backoff_before_retry(url, attempt, exc)
            except json.JSONDecodeError as exc:
                emit_event(
                    "upstream_http_request_failed",
                    upstream_url=url,
                    method="GET",
                    status_code=None,
                    error_type=type(exc).__name__,
                    error=str(exc),
                    attempt=attempt,
                )
                self._record_failure(url)
                raise

    @staticmethod
    def _is_retryable_http_error(exc: HTTPError) -> bool:
        return exc.code in {408, 425, 429} or exc.code >= 500

    def _backoff_before_retry(
        self,
        url: str,
        attempt: int,
        exc: Exception,
    ) -> None:
        backoff_sec = self._resilience.retry_backoff_sec * (2 ** (attempt - 1))
        emit_event(
            "upstream_http_request_retrying",
            upstream_url=url,
            method="GET",
            failed_attempt=attempt,
            backoff_sec=backoff_sec,
            error_type=type(exc).__name__,
        )
        if backoff_sec > 0:
            time.sleep(backoff_sec)

    def _ensure_circuit_allows_request(self, url: str) -> None:
        half_opened = False
        with self._circuit_lock:
            if self._circuit_state == "closed":
                return
            elapsed = time.monotonic() - (self._circuit_opened_at or 0.0)
            if (
                self._circuit_state == "open"
                and elapsed >= self._resilience.circuit_breaker_reset_sec
            ):
                self._circuit_state = "half_open"
                half_opened = True
        if half_opened:
            emit_event(
                "upstream_http_circuit_half_open",
                upstream_url=url,
                method="GET",
            )
            return
        emit_event(
            "upstream_http_circuit_request_rejected",
            upstream_url=url,
            method="GET",
        )
        raise CircuitBreakerOpenError(f"upstream circuit is open for {url}")

    def _record_success(self, url: str) -> None:
        with self._circuit_lock:
            previous_state = self._circuit_state
            self._circuit_state = "closed"
            self._consecutive_failures = 0
            self._circuit_opened_at = None
        if previous_state != "closed":
            emit_event(
                "upstream_http_circuit_closed",
                upstream_url=url,
                method="GET",
            )

    def _record_failure(self, url: str) -> None:
        with self._circuit_lock:
            self._consecutive_failures += 1
            should_open = (
                self._circuit_state == "half_open"
                or self._consecutive_failures
                >= self._resilience.circuit_breaker_failure_threshold
            )
            if should_open:
                self._circuit_state = "open"
                self._circuit_opened_at = time.monotonic()
            failure_count = self._consecutive_failures
        if should_open:
            emit_event(
                "upstream_http_circuit_opened",
                upstream_url=url,
                method="GET",
                consecutive_failures=failure_count,
            )


class HttpMetricSnapshotClient(BaseHttpJsonClient, MetricSnapshotClient):
    def __init__(
        self,
        base_url: str,
        *,
        path: str = "/metric-snapshots",
        country_param: str = "country",
        channel_param: str = "channel",
        headers: Optional[Dict[str, str]] = None,
        timeout_sec: float = 5.0,
        resilience: Optional[HttpResiliencePolicy] = None,
    ) -> None:
        super().__init__(
            base_url,
            headers=headers,
            timeout_sec=timeout_sec,
            resilience=resilience,
        )
        self._path = path
        self._country_param = country_param
        self._channel_param = channel_param

    def fetch_metric_snapshot(
        self,
        country: str,
        channel: str,
        time_range: str = "recent_24h",
    ) -> Optional[Dict[str, Any]]:
        query = urlencode(
            {
                self._country_param: country.upper(),
                self._channel_param: channel.lower(),
                "time_range": time_range,
            }
        )
        try:
            return self._get_json(f"{self._path}?{query}")
        except HTTPError as exc:
            if exc.code == 404:
                return None
            raise

class HttpCaseRecordClient(BaseHttpJsonClient, CaseRecordClient):
    def __init__(
        self,
        base_url: str,
        *,
        path: str = "/case-records",
        country_param: str = "country",
        channel_param: str = "channel",
        headers: Optional[Dict[str, str]] = None,
        timeout_sec: float = 5.0,
        resilience: Optional[HttpResiliencePolicy] = None,
    ) -> None:
        super().__init__(
            base_url,
            headers=headers,
            timeout_sec=timeout_sec,
            resilience=resilience,
        )
        self._path = path
        self._country_param = country_param
        self._channel_param = channel_param

    def fetch_case_records(self, country: str, channel: str) -> List[Dict[str, Any]]:
        query = urlencode(
            {
                self._country_param: country.upper(),
                self._channel_param: channel.lower(),
            }
        )
        try:
            payload = self._get_json(f"{self._path}?{query}")
        except HTTPError as exc:
            if exc.code == 404:
                return []
            raise
        return list(payload)

class HttpOrderProfileClient(BaseHttpJsonClient, OrderProfileClient):
    def __init__(
        self,
        base_url: str,
        *,
        path_template: str = "/order-profiles/{order_id}",
        headers: Optional[Dict[str, str]] = None,
        timeout_sec: float = 5.0,
        resilience: Optional[HttpResiliencePolicy] = None,
    ) -> None:
        super().__init__(
            base_url,
            headers=headers,
            timeout_sec=timeout_sec,
            resilience=resilience,
        )
        self._path_template = path_template

    def fetch_order_profile(self, order_id: str) -> Optional[Dict[str, Any]]:
        try:
            return self._get_json(self._path_template.format(order_id=order_id))
        except HTTPError as exc:
            if exc.code == 404:
                return None
            raise


class HttpStrategyProfileClient(BaseHttpJsonClient, StrategyProfileClient):
    def __init__(
        self,
        base_url: str,
        *,
        path_template: str = "/strategy-profiles/{strategy_id}",
        headers: Optional[Dict[str, str]] = None,
        timeout_sec: float = 5.0,
        resilience: Optional[HttpResiliencePolicy] = None,
    ) -> None:
        super().__init__(
            base_url,
            headers=headers,
            timeout_sec=timeout_sec,
            resilience=resilience,
        )
        self._path_template = path_template

    def fetch_strategy_profile(self, strategy_id: str) -> Optional[Dict[str, Any]]:
        try:
            return self._get_json(self._path_template.format(strategy_id=strategy_id))
        except HTTPError as exc:
            if exc.code == 404:
                return None
            raise


class HttpStrategySimulationClient(BaseHttpJsonClient, StrategySimulationClient):
    def __init__(
        self,
        base_url: str,
        *,
        path_template: str = "/strategy-simulations/{strategy_id}",
        headers: Optional[Dict[str, str]] = None,
        timeout_sec: float = 5.0,
        resilience: Optional[HttpResiliencePolicy] = None,
    ) -> None:
        super().__init__(
            base_url,
            headers=headers,
            timeout_sec=timeout_sec,
            resilience=resilience,
        )
        self._path_template = path_template

    def fetch_strategy_simulation(self, strategy_id: str) -> Optional[Dict[str, Any]]:
        try:
            return self._get_json(self._path_template.format(strategy_id=strategy_id))
        except HTTPError as exc:
            if exc.code == 404:
                return None
            raise


class HttpGraphRelationClient(BaseHttpJsonClient, GraphRelationClient):
    def __init__(
        self,
        base_url: str,
        *,
        path_template: str = "/graph-relations/{entity_id}",
        headers: Optional[Dict[str, str]] = None,
        timeout_sec: float = 5.0,
        resilience: Optional[HttpResiliencePolicy] = None,
    ) -> None:
        super().__init__(
            base_url,
            headers=headers,
            timeout_sec=timeout_sec,
            resilience=resilience,
        )
        self._path_template = path_template

    def fetch_graph_relation(self, entity_id: str) -> Optional[Dict[str, Any]]:
        try:
            return self._get_json(self._path_template.format(entity_id=entity_id))
        except HTTPError as exc:
            if exc.code == 404:
                return None
            raise
