from app import auth
from app.config import settings


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
