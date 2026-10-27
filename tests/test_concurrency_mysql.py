import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.schemas import LunchRequest
from app.services import lunch as lunch_service
from app.services.exits import record_exit
from app.services.qr import sign_qr_v1

MYSQL_TEST_URL = os.environ.get("MYSQL_TEST_URL")

pytestmark = [
    pytest.mark.mysql,
    pytest.mark.skipif(
        not MYSQL_TEST_URL,
        reason="Define MYSQL_TEST_URL para ejecutar las pruebas de concurrencia",
    ),
]


@pytest.fixture(scope="module")
def engine():
    engine = create_engine(MYSQL_TEST_URL, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture
def factory(engine):
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


@pytest.fixture
def people(factory):
    suffix = uuid4().hex[:10]
    session = factory()
    try:
        operator = models.User(
            username=f"conc_{suffix}",
            full_name="Operador Concurrencia",
            hashed_password="x",
            role=models.UserRole.LUNCH_OP,
            is_active=True,
        )
        door = models.Door(name=f"Puerta {suffix}", is_active=True)
        student = models.Student(
            student_id=f"C{suffix}",
            full_name="Estudiante Concurrencia",
            course="10A",
            is_active=True,
            is_authorized=True,
            has_lunch=True,
            lunch_type="Normal",
        )
        session.add_all([operator, door, student])
        session.commit()
        data = {
            "user_id": operator.id,
            "door_id": door.id,
            "student_id": student.id,
            "student_code": student.student_id,
        }
    finally:
        session.close()

    yield data

    session = factory()
    try:
        session.query(models.ScanAttempt).filter(
            (models.ScanAttempt.student_id == data["student_id"])
            | (models.ScanAttempt.operator_id == data["user_id"])
        ).delete(synchronize_session=False)
        session.query(models.AuditLog).filter(models.AuditLog.actor_id == data["user_id"]).delete(
            synchronize_session=False
        )
        session.query(models.LunchLog).filter(
            models.LunchLog.student_id == data["student_id"]
        ).delete(synchronize_session=False)
        session.query(models.ExitLog).filter(
            models.ExitLog.student_id == data["student_id"]
        ).delete(synchronize_session=False)
        session.query(models.Student).filter(models.Student.id == data["student_id"]).delete(
            synchronize_session=False
        )
        session.query(models.Door).filter(models.Door.id == data["door_id"]).delete(
            synchronize_session=False
        )
        session.query(models.User).filter(models.User.id == data["user_id"]).delete(
            synchronize_session=False
        )
        session.commit()
    finally:
        session.close()


def _concurrently(factory, operation, workers=2):
    barrier = Barrier(workers)

    def run(index):
        session = factory()
        try:
            barrier.wait(timeout=10)
            return operation(session, index)
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(run, index) for index in range(workers)]
        return [future.result(timeout=30) for future in futures]


def test_concurrent_exits_create_a_single_log(factory, people):
    code = sign_qr_v1(people["student_code"])

    def scan(session, _):
        operator = session.get(models.User, people["user_id"])
        return record_exit(
            session,
            qr_code=code,
            door_id=people["door_id"],
            operator=operator,
        )

    outcomes = _concurrently(factory, scan)

    assert sorted(outcome.status for outcome in outcomes) == ["success", "warning"]

    session = factory()
    try:
        assert session.query(models.ExitLog).filter_by(student_id=people["student_id"]).count() == 1
        assert (
            session.query(models.ScanAttempt)
            .filter_by(module="exit", student_id=people["student_id"])
            .count()
            == 2
        )
    finally:
        session.close()


def test_concurrent_lunches_create_a_single_log(factory, people):
    payload = LunchRequest(method="qr", code=sign_qr_v1(people["student_code"]))

    def process(session, _):
        operator = session.get(models.User, people["user_id"])
        return lunch_service.record_lunch(session, payload=payload, operator=operator)

    outcomes = _concurrently(factory, process)

    assert sorted(outcome.status for outcome in outcomes) == ["success", "warning"]
    tickets = {outcome.log.public_id for outcome in outcomes if outcome.log}
    assert len(tickets) == 1

    session = factory()
    try:
        assert (
            session.query(models.LunchLog).filter_by(student_id=people["student_id"]).count() == 1
        )
        assert (
            session.query(models.ScanAttempt)
            .filter_by(module="lunch", student_id=people["student_id"])
            .count()
            == 2
        )
    finally:
        session.close()


def test_concurrent_reprints_do_not_lose_counts(factory, people):
    payload = LunchRequest(method="qr", code=sign_qr_v1(people["student_code"]))
    session = factory()
    try:
        operator = session.get(models.User, people["user_id"])
        outcome = lunch_service.record_lunch(session, payload=payload, operator=operator)
        public_id = outcome.log.public_id
    finally:
        session.close()

    def reprint(session, _):
        operator = session.get(models.User, people["user_id"])
        return lunch_service.reprint_ticket(session, public_id=public_id, operator=operator)

    results = _concurrently(factory, reprint)
    assert all(result is not None for result in results)

    session = factory()
    try:
        log = session.query(models.LunchLog).filter_by(public_id=public_id).one()
        assert log.printed_count == 2
        assert (
            session.query(models.AuditLog)
            .filter_by(action="lunch.ticket_reprinted", actor_id=people["user_id"])
            .count()
            == 2
        )
    finally:
        session.close()
