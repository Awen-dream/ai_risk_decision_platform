from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import uuid4

from core.models import WorkflowCase, WorkflowCaseOperationEntry
from services.audit import AuditLog, build_upstream_audit_event
from services.case_service import CaseService


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
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HandoffPublishResult:
    case: WorkflowCase
    export: HandoffExportEnvelope
    receipt: HandoffPublishReceipt
    audit_event: dict[str, Any]


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
            metadata={"delivery_mode": "audit_only"},
        )


@dataclass(frozen=True)
class TicketHandoffPublisher:
    publisher_type: str = "ticket"
    project_key: str = "risk-ops"

    def supports(self, destination_type: str) -> bool:
        return destination_type == "ticket"

    def publish(self, export: HandoffExportEnvelope) -> HandoffPublishReceipt:
        return HandoffPublishReceipt(
            receipt_id=f"HANDOFF-{uuid4().hex[:10].upper()}",
            status="published",
            published_at=export.exported_at,
            publisher_type=self.publisher_type,
            target_ref=f"ticket://{self.project_key}/{export.destination.destination_key}",
            metadata={
                "project_key": self.project_key,
                "case_status": export.case.status,
                "case_severity": export.case.severity,
            },
        )


@dataclass(frozen=True)
class WebhookHandoffPublisher:
    publisher_type: str = "webhook"
    base_url: str = "https://handoff.local/webhooks"

    def supports(self, destination_type: str) -> bool:
        return destination_type == "webhook"

    def publish(self, export: HandoffExportEnvelope) -> HandoffPublishReceipt:
        return HandoffPublishReceipt(
            receipt_id=f"HANDOFF-{uuid4().hex[:10].upper()}",
            status="published",
            published_at=export.exported_at,
            publisher_type=self.publisher_type,
            target_ref=f"{self.base_url.rstrip('/')}/{export.destination.destination_key}",
            metadata={"method": "POST"},
        )


class CaseHandoffPublisherService:
    def __init__(
        self,
        *,
        case_service: CaseService,
        audit_log: AuditLog,
        publishers: list[HandoffPublisher],
    ) -> None:
        self._case_service = case_service
        self._audit_log = audit_log
        self._publishers = publishers

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
        case = self._case_service.publish_case_handoff(
            case_id,
            destination_type=destination_type,
            destination_key=destination_key,
            note=note,
        )
        if case is None:
            return None
        export = self._build_export(
            case,
            destination_type=destination_type,
            destination_key=destination_key,
            exported_at=published_at,
        )
        publisher = self._publisher_for(destination_type)
        receipt = publisher.publish(export)
        audit_event = self._build_audit_event(case, export, receipt)
        self._audit_log.record(audit_event)
        return HandoffPublishResult(
            case=case,
            export=export,
            receipt=receipt,
            audit_event=audit_event,
        )

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
            outcome="success",
            attempt=1,
            total_attempts=1,
            status_code=202,
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
        return event
