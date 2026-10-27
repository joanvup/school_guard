import hashlib

from starlette.requests import Request

from app import models
from app.database import SessionLocal
from app.services.audit import (
    add_audit,
    add_scan_attempt,
    hash_code,
    record_audit,
    record_scan_attempt,
)


def _request(*, path="/", user_agent=None, client_addr=None):
    headers = []
    if user_agent is not None:
        headers.append((b"user-agent", user_agent.encode("utf-8")))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "headers": headers,
            "client": (client_addr, 1234) if client_addr else None,
        }
    )


def test_hash_code_returns_none_for_empty_values():
    assert hash_code(None) is None
    assert hash_code("") is None
    assert hash_code("abc") == hashlib.sha256(b"abc").hexdigest()


def test_add_audit_without_request_has_no_metadata():
    db = SessionLocal()
    try:
        entry = add_audit(
            db,
            action="test.no_request",
            entity_type="student",
            entity_id=7,
            details={"motivo": "prueba"},
        )
        db.commit()
        assert entry.ip is None
        assert entry.user_agent is None
        assert entry.request_id is None
        assert entry.entity_id == "7"
    finally:
        db.close()


def test_add_audit_uses_request_metadata_and_state_request_id():
    request = _request(user_agent="agente/" + "x" * 300, client_addr="9" * 50)
    request.state.request_id = "req-desde-estado"

    db = SessionLocal()
    try:
        entry = add_audit(db, action="test.request", request=request)
        db.commit()
        assert entry.ip == "9" * 45
        assert entry.user_agent == ("agente/" + "x" * 300)[:255]
        assert entry.request_id == "req-desde-estado"
        assert entry.entity_id is None
    finally:
        db.close()


def test_add_audit_handles_request_without_client_or_user_agent():
    request = _request()

    db = SessionLocal()
    try:
        entry = add_audit(db, action="test.empty_request", request=request)
        db.commit()
        assert entry.ip is None
        assert entry.user_agent is None
        assert entry.request_id is None
    finally:
        db.close()


def test_record_audit_commits_the_entry():
    db = SessionLocal()
    try:
        entry = record_audit(db, action="test.record")
        entry_id = entry.id
    finally:
        db.close()

    check = SessionLocal()
    try:
        stored = check.query(models.AuditLog).filter(models.AuditLog.id == entry_id).one()
        assert stored.action == "test.record"
    finally:
        check.close()


def test_add_scan_attempt_hashes_code_and_truncates_reason():
    db = SessionLocal()
    try:
        attempt = add_scan_attempt(
            db,
            module="lunch",
            method="qr",
            result="denied",
            code="codigo-123",
            reason="x" * 400,
        )
        db.commit()
        assert attempt.code_hash == hashlib.sha256(b"codigo-123").hexdigest()
        assert len(attempt.reason) == 255
        assert attempt.door_id is None
    finally:
        db.close()


def test_record_scan_attempt_without_code_skips_hashing():
    db = SessionLocal()
    try:
        attempt = record_scan_attempt(db, module="scan", method="manual", result="success")
        attempt_id = attempt.id
    finally:
        db.close()

    assert attempt.code_hash is None
    check = SessionLocal()
    try:
        assert check.query(models.ScanAttempt).filter_by(id=attempt_id).count() == 1
    finally:
        check.close()
