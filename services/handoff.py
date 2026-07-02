from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from typing import Any, Protocol
from uuid import uuid4

from core.models import (
    WorkflowCase,
    WorkflowCaseHandoffDeliveryEntry,
    WorkflowCaseOperationEntry,
)
from services.audit import AuditLog, build_upstream_audit_event
from services.case_service import CaseService
from services.observability import current_headers


@dataclass(frozen=True)
class HandoffDestination:
    destination_type: str
    destination_key: str


@dataclass(frozen=True)
class HandoffExportEnvelope:
    export_id: str
    schema_version: str
    exported_at: str
    destination: HandoffDestination
    case: WorkflowCase
    handoff_artifact: dict[str, Any]
    operation_log: list[WorkflowCaseOperationEntry] = field(default_factory=list)


@dataclass(frozen=True)
class HandoffPublishReceipt:
    receipt_id: str
    status: str
    published_at: str
    publisher_type: str
    target_ref: str
    summary: str = ""
    error_type: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HandoffPublishResult:
    case: WorkflowCase
    export: HandoffExportEnvelope
    receipt: HandoffPublishReceipt
    audit_event: dict[str, Any]


@dataclass(frozen=True)
class HandoffRetryPolicy:
    max_attempts: int
    min_retry_interval_sec: float = 0.0


@dataclass(frozen=True)
class HandoffRetryDecision:
    eligible: bool
    reason: str | None
    retry_after: str | None
    attempt_count: int
    max_attempts: int
    remaining_attempts: int


class HandoffDeliveryPublishError(RuntimeError):
    def __init__(
        self,
        *,
        publisher_type: str,
        target_ref: str,
        error_type: str,
        error_message: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(error_message)
        self.publisher_type = publisher_type
        self.target_ref = target_ref
        self.error_type = error_type
        self.error_message = error_message
        self.metadata = dict(metadata or {})


class HandoffPublishError(RuntimeError):
    def __init__(self, result: HandoffPublishResult) -> None:
        super().__init__(result.receipt.error_message or result.receipt.summary)
        self.result = result


class HandoffPublisher(Protocol):
    publisher_type: str

    def supports(self, destination_type: str) -> bool:
        ...

    def publish(self, export: HandoffExportEnvelope) -> HandoffPublishReceipt:
        ...


@dataclass(frozen=True)
class AuditOnlyHandoffPublisher:
    publisher_type: str = "audit-only"

    def supports(self, destination_type: str) -> bool:
        return destination_type == "audit-only"

    def publish(self, export: HandoffExportEnvelope) -> HandoffPublishReceipt:
        return HandoffPublishReceipt(
            receipt_id=f"HANDOFF-{uuid4().hex[:10].upper()}",
            status="published",
            published_at=export.exported_at,
            publisher_type=self.publisher_type,
            target_ref=f"audit://{export.destination.destination_key}",
            summary=f"案件交接已归档到 audit-only:{export.destination.destination_key}。",
            metadata={"delivery_mode": "audit_only"},
        )


@dataclass(frozen=True)
class HttpTicketHandoffPublisher:
    publisher_type: str = "ticket"
    base_url: str = "https://handoff.local/tickets"
    path_template: str = "/projects/{project_key}/cases"
    project_key: str = "risk-ops"
    headers: dict[str, str] = field(default_factory=dict)
    timeout_sec: float = 5.0
    retry_attempts: int = 1
    retry_backoff_sec: float = 0.1

    def supports(self, destination_type: str) -> bool:
        return destination_type == "ticket"

    def publish(self, export: HandoffExportEnvelope) -> HandoffPublishReceipt:
        target_ref = (
            f"{self.base_url.rstrip('/')}"
            f"{self.path_template.format(project_key=self.project_key)}"
        )
        payload = {
            "external_case_key": export.destination.destination_key,
            "summary": export.case.summary,
            "severity": export.case.severity,
            "status": export.case.status,
            "source_agent": export.case.source_agent,
            "handoff_artifact": export.handoff_artifact,
            "operation_log": [_operation_to_mapping(item) for item in export.operation_log],
        }
        try:
            response_status = _post_json_with_retry(
                url=target_ref,
                payload=payload,
                headers=self.headers,
                timeout_sec=self.timeout_sec,
                retry_attempts=self.retry_attempts,
                retry_backoff_sec=self.retry_backoff_sec,
            )
        except Exception as exc:
            raise HandoffDeliveryPublishError(
                publisher_type=self.publisher_type,
                target_ref=target_ref,
                error_type=type(exc).__name__,
                error_message=str(exc) or "Ticket handoff publish failed",
                metadata={
                    "project_key": self.project_key,
                    "case_status": export.case.status,
                    "case_severity": export.case.severity,
                },
            ) from exc
        return HandoffPublishReceipt(
            receipt_id=f"HANDOFF-{uuid4().hex[:10].upper()}",
            status="published",
            published_at=export.exported_at,
            publisher_type=self.publisher_type,
            target_ref=target_ref,
            summary=f"案件交接已发布到工单系统 {self.project_key}。",
            metadata={
                "project_key": self.project_key,
                "case_status": export.case.status,
                "case_severity": export.case.severity,
                "http_status": response_status,
            },
        )


@dataclass(frozen=True)
class HttpWebhookHandoffPublisher:
    publisher_type: str = "webhook"
    base_url: str = "https://handoff.local/webhooks"
    headers: dict[str, str] = field(default_factory=dict)
    timeout_sec: float = 5.0
    retry_attempts: int = 1
    retry_backoff_sec: float = 0.1

    def supports(self, destination_type: str) -> bool:
        return destination_type == "webhook"

    def publish(self, export: HandoffExportEnvelope) -> HandoffPublishReceipt:
        target_ref = f"{self.base_url.rstrip('/')}/{export.destination.destination_key}"
        payload = {
            "event": "case_handoff",
            "export_id": export.export_id,
            "schema_version": export.schema_version,
            "exported_at": export.exported_at,
            "destination": {
                "destination_type": export.destination.destination_type,
                "destination_key": export.destination.destination_key,
            },
            "case": {
                "case_id": export.case.case_id,
                "status": export.case.status,
                "severity": export.case.severity,
                "summary": export.case.summary,
            },
            "handoff_artifact": export.handoff_artifact,
        }
        try:
            response_status = _post_json_with_retry(
                url=target_ref,
                payload=payload,
                headers=self.headers,
                timeout_sec=self.timeout_sec,
                retry_attempts=self.retry_attempts,
                retry_backoff_sec=self.retry_backoff_sec,
            )
        except Exception as exc:
            raise HandoffDeliveryPublishError(
                publisher_type=self.publisher_type,
                target_ref=target_ref,
                error_type=type(exc).__name__,
                error_message=str(exc) or "Webhook handoff publish failed",
                metadata={"method": "POST"},
            ) from exc
        return HandoffPublishReceipt(
            receipt_id=f"HANDOFF-{uuid4().hex[:10].upper()}",
            status="published",
            published_at=export.exported_at,
            publisher_type=self.publisher_type,
            target_ref=target_ref,
            summary=f"案件交接已推送到 webhook:{export.destination.destination_key}。",
            metadata={"method": "POST", "http_status": response_status},
        )


class CaseHandoffPublisherService:
    def __init__(
        self,
        *,
        case_service: CaseService,
        audit_log: AuditLog,
        publishers: list[HandoffPublisher],
        retry_policies: dict[str, HandoffRetryPolicy] | None = None,
    ) -> None:
        self._case_service = case_service
        self._audit_log = audit_log
        self._publishers = publishers
        self._retry_policies = dict(retry_policies or {})

    def export_case_handoff(
        self,
        case_id: str,
        *,
        destination_type: str,
        destination_key: str,
        exported_at: str,
    ) -> HandoffExportEnvelope | None:
        case = self._case_service.get_case(case_id)
        if case is None:
            return None
        return self._build_export(
            case,
            destination_type=destination_type,
            destination_key=destination_key,
            exported_at=exported_at,
        )

    def publish_case_handoff(
        self,
        case_id: str,
        *,
        destination_type: str,
        destination_key: str,
        note: str | None,
        published_at: str,
    ) -> HandoffPublishResult | None:
        case = self._case_service.get_case(case_id)
        if case is None:
            return None
        export = self._build_export(
            case,
            destination_type=destination_type,
            destination_key=destination_key,
            exported_at=published_at,
        )
        publisher = self._publisher_for(destination_type)
        try:
            receipt = publisher.publish(export)
        except HandoffDeliveryPublishError as exc:
            failed_receipt = HandoffPublishReceipt(
                receipt_id=f"HANDOFF-{uuid4().hex[:10].upper()}",
                status="failed",
                published_at=published_at,
                publisher_type=exc.publisher_type,
                target_ref=exc.target_ref,
                summary=note or f"案件交接发布失败到 {destination_type}:{destination_key}。",
                error_type=exc.error_type,
                error_message=exc.error_message,
                metadata=exc.metadata,
            )
            failed_case = self._case_service.record_case_handoff_delivery(
                case_id,
                export_id=export.export_id,
                destination_type=destination_type,
                destination_key=destination_key,
                publisher_type=failed_receipt.publisher_type,
                target_ref=failed_receipt.target_ref,
                status=failed_receipt.status,
                summary=failed_receipt.summary,
                created_at=published_at,
                published_at=failed_receipt.published_at,
                error_type=failed_receipt.error_type,
                error_message=failed_receipt.error_message,
                metadata=failed_receipt.metadata,
            )
            result_case = failed_case or case
            failed_export = self._build_export(
                result_case,
                destination_type=destination_type,
                destination_key=destination_key,
                exported_at=published_at,
            )
            audit_event = self._build_audit_event(result_case, failed_export, failed_receipt)
            self._audit_log.record(audit_event)
            raise HandoffPublishError(
                HandoffPublishResult(
                    case=result_case,
                    export=failed_export,
                    receipt=failed_receipt,
                    audit_event=audit_event,
                )
            ) from exc

        delivered_case = self._case_service.record_case_handoff_delivery(
            case_id,
            export_id=export.export_id,
            destination_type=destination_type,
            destination_key=destination_key,
            publisher_type=receipt.publisher_type,
            target_ref=receipt.target_ref,
            status=receipt.status,
            summary=receipt.summary or (note or "案件交接已发布。"),
            created_at=published_at,
            published_at=receipt.published_at,
            metadata=receipt.metadata,
        )
        if delivered_case is None:
            return None
        updated_case = self._case_service.publish_case_handoff(
            case_id,
            destination_type=destination_type,
            destination_key=destination_key,
            note=note,
        )
        if updated_case is None:
            return None
        updated_export = self._build_export(
            updated_case,
            destination_type=destination_type,
            destination_key=destination_key,
            exported_at=published_at,
        )
        audit_event = self._build_audit_event(updated_case, updated_export, receipt)
        self._audit_log.record(audit_event)
        return HandoffPublishResult(
            case=updated_case,
            export=updated_export,
            receipt=receipt,
            audit_event=audit_event,
        )

    def retry_policy_for(self, destination_type: str) -> HandoffRetryPolicy:
        return self._retry_policies.get(
            destination_type,
            HandoffRetryPolicy(max_attempts=3, min_retry_interval_sec=0.0),
        )

    def evaluate_delivery_retry(
        self,
        case: WorkflowCase,
        delivery: WorkflowCaseHandoffDeliveryEntry,
        *,
        evaluated_at: str,
    ) -> HandoffRetryDecision:
        policy = self.retry_policy_for(delivery.destination_type)
        related = self._related_deliveries(case, delivery)
        related.sort(key=lambda item: item.created_at)
        if delivery.status == "published":
            return HandoffRetryDecision(
                eligible=False,
                reason="delivery_already_published",
                retry_after=None,
                attempt_count=len(related),
                max_attempts=policy.max_attempts,
                remaining_attempts=0,
            )
        attempt_count = len(related)
        if related and related[-1].delivery_id != delivery.delivery_id:
            return HandoffRetryDecision(
                eligible=False,
                reason="delivery_superseded_by_newer_attempt",
                retry_after=None,
                attempt_count=attempt_count,
                max_attempts=policy.max_attempts,
                remaining_attempts=max(0, policy.max_attempts - attempt_count),
            )
        if attempt_count >= policy.max_attempts:
            return HandoffRetryDecision(
                eligible=False,
                reason="retry_attempt_limit_reached",
                retry_after=None,
                attempt_count=attempt_count,
                max_attempts=policy.max_attempts,
                remaining_attempts=0,
            )
        retry_after = None
        if policy.min_retry_interval_sec > 0:
            retry_after_dt = _parse_timestamp(delivery.created_at) + timedelta(
                seconds=policy.min_retry_interval_sec
            )
            retry_after = _format_timestamp(retry_after_dt)
            if _parse_timestamp(evaluated_at) < retry_after_dt:
                return HandoffRetryDecision(
                    eligible=False,
                    reason="retry_cooldown_active",
                    retry_after=retry_after,
                    attempt_count=attempt_count,
                    max_attempts=policy.max_attempts,
                    remaining_attempts=max(0, policy.max_attempts - attempt_count),
                )
        return HandoffRetryDecision(
            eligible=True,
            reason=None,
            retry_after=retry_after,
            attempt_count=attempt_count,
            max_attempts=policy.max_attempts,
            remaining_attempts=max(0, policy.max_attempts - attempt_count),
        )

    def list_retry_candidates(
        self,
        cases: list[WorkflowCase],
        *,
        evaluated_at: str,
        case_id: str | None = None,
        destination_type: str | None = None,
        publisher_type: str | None = None,
        limit: int = 50,
    ) -> list[tuple[WorkflowCase, WorkflowCaseHandoffDeliveryEntry, HandoffRetryDecision]]:
        candidates: list[
            tuple[WorkflowCase, WorkflowCaseHandoffDeliveryEntry, HandoffRetryDecision]
        ] = []
        for case in cases:
            if case_id is not None and case.case_id != case_id:
                continue
            for delivery in case.handoff_deliveries:
                if delivery.status == "published":
                    continue
                if (
                    destination_type is not None
                    and delivery.destination_type != destination_type
                ):
                    continue
                if publisher_type is not None and delivery.publisher_type != publisher_type:
                    continue
                decision = self.evaluate_delivery_retry(
                    case,
                    delivery,
                    evaluated_at=evaluated_at,
                )
                candidates.append((case, delivery, decision))
        candidates.sort(key=lambda item: item[1].created_at, reverse=True)
        return candidates[:limit]

    def _build_export(
        self,
        case: WorkflowCase,
        *,
        destination_type: str,
        destination_key: str,
        exported_at: str,
    ) -> HandoffExportEnvelope:
        return HandoffExportEnvelope(
            export_id=f"HEX-{uuid4().hex[:12].upper()}",
            schema_version="case-handoff.v1",
            exported_at=exported_at,
            destination=HandoffDestination(
                destination_type=destination_type,
                destination_key=destination_key,
            ),
            case=case,
            handoff_artifact={
                **case.handoff_artifact,
                "destination_type": destination_type,
                "destination_key": destination_key,
                "exported_at": exported_at,
            },
            operation_log=list(case.operation_log[-10:]),
        )

    def _related_deliveries(
        self,
        case: WorkflowCase,
        delivery: WorkflowCaseHandoffDeliveryEntry,
    ) -> list[WorkflowCaseHandoffDeliveryEntry]:
        return [
            item
            for item in case.handoff_deliveries
            if item.destination_type == delivery.destination_type
            and item.destination_key == delivery.destination_key
            and item.publisher_type == delivery.publisher_type
        ]

    def _publisher_for(self, destination_type: str) -> HandoffPublisher:
        for publisher in self._publishers:
            if publisher.supports(destination_type):
                return publisher
        raise ValueError(f"Unsupported handoff destination type: {destination_type}")

    def _build_audit_event(
        self,
        case: WorkflowCase,
        export: HandoffExportEnvelope,
        receipt: HandoffPublishReceipt,
    ) -> dict[str, Any]:
        event = build_upstream_audit_event(
            upstream_client="CaseHandoffPublisher",
            method="PUBLISH",
            url=receipt.target_ref,
            outcome="success" if receipt.status == "published" else "error",
            attempt=1,
            total_attempts=1,
            status_code=_receipt_status_code(receipt),
            request_header_names=["X-Request-Id", "X-Trace-Id"],
        )
        event["event_type"] = "case_handoff_publish"
        event["case_id"] = case.case_id
        event["handoff_export_id"] = export.export_id
        event["handoff_schema_version"] = export.schema_version
        event["destination_type"] = export.destination.destination_type
        event["destination_key"] = export.destination.destination_key
        event["publisher_type"] = receipt.publisher_type
        event["target_ref"] = receipt.target_ref
        event["case_status"] = case.status
        event["case_severity"] = case.severity
        if receipt.error_type is not None:
            event["error_type"] = receipt.error_type
        return event


def _operation_to_mapping(entry: WorkflowCaseOperationEntry) -> dict[str, Any]:
    return {
        "operation_id": entry.operation_id,
        "operation_type": entry.operation_type,
        "actor": entry.actor,
        "status_before": entry.status_before,
        "status_after": entry.status_after,
        "summary": entry.summary,
        "created_at": entry.created_at,
        "assigned_to": entry.assigned_to,
        "action_outcome": entry.action_outcome,
        "metadata": entry.metadata,
    }


def _post_json_with_retry(
    *,
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout_sec: float,
    retry_attempts: int,
    retry_backoff_sec: float,
) -> int:
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    merged_headers = {
        "Content-Type": "application/json",
        **headers,
        **current_headers(),
    }
    attempts = retry_attempts + 1
    for attempt in range(1, attempts + 1):
        request = Request(url, data=body, headers=merged_headers, method="POST")
        try:
            with urlopen(request, timeout=timeout_sec) as response:
                return int(getattr(response, "status", 200))
        except HTTPError as exc:
            if exc.code < 500 and exc.code not in {408, 425, 429}:
                raise
            if attempt == attempts:
                raise
        except (URLError, TimeoutError):
            if attempt == attempts:
                raise
        if retry_backoff_sec > 0:
            time.sleep(retry_backoff_sec * (2 ** (attempt - 1)))
    raise RuntimeError("handoff publish failed after retries")


def _receipt_status_code(receipt: HandoffPublishReceipt) -> int:
    status_code = receipt.metadata.get("http_status")
    if isinstance(status_code, int):
        return status_code
    if receipt.status == "published":
        return 202
    return 502


def _parse_timestamp(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized).astimezone(timezone.utc)


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
