import hashlib
from typing import Any

from fastapi import Request

from .. import models
from ..observability import current_request_id


def hash_code(code: str | None) -> str | None:
    if not code:
        return None
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _request_metadata(request: Request | None) -> tuple[str | None, str | None]:
    if request is None:
        return None, None
    ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    return (
        ip[:45] if ip else None,
        user_agent[:255] if user_agent else None,
    )


def add_audit(
    db,
    *,
    action: str,
    actor_id: int | None = None,
    entity_type: str | None = None,
    entity_id: Any = None,
    details: dict | None = None,
    request: Request | None = None,
) -> models.AuditLog:
    ip, user_agent = _request_metadata(request)
    request_id = current_request_id()
    if request_id is None and request is not None:
        request_id = getattr(request.state, "request_id", None)
    entry = models.AuditLog(
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        ip=ip,
        user_agent=user_agent,
        details=details,
        request_id=request_id,
    )
    db.add(entry)
    return entry


def record_audit(db, **kwargs) -> models.AuditLog:
    entry = add_audit(db, **kwargs)
    db.commit()
    return entry


def add_scan_attempt(
    db,
    *,
    module: str,
    method: str,
    result: str,
    student_id: int | None = None,
    employee_id: int | None = None,
    operator_id: int | None = None,
    door_id: int | None = None,
    code: str | None = None,
    reason: str | None = None,
) -> models.ScanAttempt:
    attempt = models.ScanAttempt(
        module=module,
        method=method,
        result=result,
        student_id=student_id,
        employee_id=employee_id,
        operator_id=operator_id,
        door_id=door_id,
        code_hash=hash_code(code),
        reason=reason[:255] if reason else None,
    )
    db.add(attempt)
    return attempt


def record_scan_attempt(db, **kwargs) -> models.ScanAttempt:
    attempt = add_scan_attempt(db, **kwargs)
    db.commit()
    return attempt
