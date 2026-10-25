from app import auth
from app.config import settings
from app.services import qr as qr_service
from app.services.qr import QRPayload, sign_qr_v2, verify_qr


def _sign_v2(person_type: str, identifier: str, key: str) -> str:
    message = f"v2.{person_type}.{identifier}"
    return f"{message}.{qr_service._signature(message, key)}"


def test_current_key_signs_and_verifies():
    token = auth.sign_qr_content("S100")
    assert token.startswith("S100.")
    assert auth.verify_qr_content(token) == "S100"


def test_previous_key_still_valid_during_rotation():
    previous = auth._sign_qr("S100", settings.qr_secret_key_previous)
    assert auth.verify_qr_content(f"S100.{previous}") == "S100"


def test_invalid_signature_is_rejected():
    assert auth.verify_qr_content("S100." + "0" * 16) is None
    assert auth.verify_qr_content("S100.deadbeef") is None


def test_malformed_qr_is_rejected():
    assert auth.verify_qr_content("") is None
    assert auth.verify_qr_content("S100") is None
    assert auth.verify_qr_content(".abcdef0123456789") is None


def test_v1_payload_has_no_person_type():
    assert verify_qr(auth.sign_qr_content("S100")) == QRPayload(
        identifier="S100", person_type=None, version=1
    )


def test_v2_includes_person_type_and_version():
    token = sign_qr_v2("student", "S100")
    assert token.startswith("v2.student.S100.")
    assert verify_qr(token) == QRPayload(identifier="S100", person_type="student", version=2)


def test_v2_previous_key_is_valid_during_rotation():
    token = _sign_v2("employee", "E100", settings.qr_secret_key_previous)
    assert verify_qr(token) == QRPayload(identifier="E100", person_type="employee", version=2)


def test_v2_cannot_be_retyped():
    signature = sign_qr_v2("student", "S100").rsplit(".", 1)[1]
    assert verify_qr(f"v2.employee.S100.{signature}") is None


def test_v2_rejects_unknown_person_type():
    token = _sign_v2("guardian", "S100", settings.qr_secret_key_current)
    assert verify_qr(token) is None


def test_v2_rejects_short_or_forged_signature():
    assert verify_qr(f"v2.student.S100.{'0' * 16}") is None
    assert verify_qr(f"v2.student.S100.{'0' * 64}") is None


def test_v1_and_v2_signatures_are_not_interchangeable():
    v1_signature = auth.sign_qr_content("S100").rsplit(".", 1)[1]
    assert verify_qr(f"v2.student.S100.{v1_signature}") is None

    v2_signature = sign_qr_v2("student", "S100").rsplit(".", 1)[1]
    assert verify_qr(f"S100.{v2_signature}") is None


def test_oversized_qr_is_rejected():
    assert verify_qr("S" * 300 + ".0000000000000000") is None
