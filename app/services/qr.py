import hashlib
import hmac
from dataclasses import dataclass

from ..config import settings

PERSON_TYPES = ("student", "employee")
V1_SIGNATURE_LENGTH = 16
V2_SIGNATURE_LENGTH = 64
MAX_QR_LENGTH = 300


@dataclass(frozen=True)
class QRPayload:
    identifier: str
    person_type: str | None
    version: int


def _signature(message: str, key: str, length: int | None = None) -> str:
    digest = hmac.new(key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
    return digest if length is None else digest[:length]


def _keys() -> list[str]:
    keys = [settings.qr_secret_key_current]
    if settings.qr_secret_key_previous:
        keys.append(settings.qr_secret_key_previous)
    return keys


def sign_qr_v1(identifier: str) -> str:
    return sign_qr_v1_with_key(identifier, settings.qr_secret_key_current)


def sign_qr_v1_with_key(identifier: str, key: str) -> str:
    return f"{identifier}.{_signature(identifier, key, V1_SIGNATURE_LENGTH)}"


def sign_qr_v2(person_type: str, identifier: str) -> str:
    if person_type not in PERSON_TYPES:
        raise ValueError("Tipo de persona inválido")
    message = f"v2.{person_type}.{identifier}"
    return f"{message}.{_signature(message, settings.qr_secret_key_current)}"


def verify_qr(qr_content: str | None) -> QRPayload | None:
    if not qr_content:
        return None

    content = qr_content.strip()
    if not content or len(content) > MAX_QR_LENGTH:
        return None

    if content.startswith("v2."):
        parts = content.split(".")
        if len(parts) != 4:
            return None
        _, person_type, identifier, received_sig = parts
        if person_type not in PERSON_TYPES or not identifier:
            return None
        if len(received_sig) != V2_SIGNATURE_LENGTH:
            return None

        message = f"v2.{person_type}.{identifier}"
        for key in _keys():
            if hmac.compare_digest(_signature(message, key), received_sig):
                return QRPayload(identifier=identifier, person_type=person_type, version=2)
        return None

    if "." not in content:
        return None

    identifier, received_sig = content.rsplit(".", 1)
    if not identifier or len(received_sig) != V1_SIGNATURE_LENGTH:
        return None

    for key in _keys():
        if hmac.compare_digest(_signature(identifier, key, V1_SIGNATURE_LENGTH), received_sig):
            return QRPayload(identifier=identifier, person_type=None, version=1)
    return None


def sign_qr_content(identifier: str) -> str:
    """Formato v1, conservado para los carnets ya impresos."""
    return sign_qr_v1(identifier)


def verify_qr_content(qr_content: str) -> str | None:
    payload = verify_qr(qr_content)
    return payload.identifier if payload else None
