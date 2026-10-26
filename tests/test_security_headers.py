import os
import re
import subprocess
import sys
from pathlib import Path

from app.config import settings
from tests.conftest import USER_PASSWORD
from tests.helpers import login

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES = BASE_DIR / "app" / "templates"
EXTERNAL_HOSTS = (
    "cdn.tailwindcss.com",
    "ui-avatars.com",
    "fonts.googleapis.com",
    "fonts.gstatic.com",
    "actions.google.com",
    "cdnjs.cloudflare.com",
    "unpkg.com",
    "cdn.jsdelivr.net",
)

INLINE_SCRIPT_WITHOUT_NONCE = re.compile(r"<script(?![^>]*\bsrc=)(?![^>]*\bnonce=)[^>]*>")
CSP_NONCE = re.compile(r"'nonce-([^']+)'")


def _csp(response) -> str:
    return response.headers["content-security-policy"]


def test_security_headers_are_present(client):
    response = client.get("/")
    assert response.status_code == 200

    headers = response.headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["referrer-policy"] == "no-referrer"
    assert headers["x-frame-options"] == "DENY"
    assert headers["permissions-policy"] == (
        "camera=(self), microphone=(), geolocation=(), payment=(), usb=()"
    )
    assert headers["cross-origin-opener-policy"] == "same-origin"
    assert headers["cross-origin-resource-policy"] == "same-origin"

    csp = _csp(response)
    assert "default-src 'self'" in csp
    assert "script-src 'self' 'nonce-" in csp
    assert "'unsafe-inline'" not in csp.split("script-src", 1)[1].split(";", 1)[0]
    assert "script-src-attr 'unsafe-inline'" in csp
    assert "object-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "strict-transport-security" not in headers


def test_nonce_matches_inline_scripts(client):
    login(client, "operator", USER_PASSWORD)

    response = client.get("/dashboard")
    assert response.status_code == 200

    header_nonce = CSP_NONCE.search(_csp(response))
    assert header_nonce is not None
    page_nonces = set(re.findall(r'<script nonce="([^"]+)"', response.text))
    assert page_nonces == {header_nonce.group(1)}


def test_nonce_changes_between_requests(client):
    first = CSP_NONCE.search(_csp(client.get("/"))).group(1)
    second = CSP_NONCE.search(_csp(client.get("/"))).group(1)
    assert first != second


def test_csp_report_only_mode(client, monkeypatch):
    monkeypatch.setattr(settings, "csp_mode", "report-only")

    response = client.get("/")
    assert "content-security-policy" not in response.headers
    assert "nonce-" in response.headers["content-security-policy-report-only"]


def test_csp_can_be_disabled(client, monkeypatch):
    monkeypatch.setattr(settings, "csp_mode", "off")

    response = client.get("/")
    assert "content-security-policy" not in response.headers
    assert "content-security-policy-report-only" not in response.headers


def test_hsts_only_over_https(client):
    assert "strict-transport-security" not in client.get("/").headers

    response = client.get("/", headers={"x-forwarded-proto": "https"})
    assert response.headers["strict-transport-security"] == (f"max-age={settings.hsts_max_age}")
    assert "upgrade-insecure-requests" in _csp(response)


def test_hsts_can_be_disabled(client, monkeypatch):
    monkeypatch.setattr(settings, "hsts_max_age", 0)

    response = client.get("/", headers={"x-forwarded-proto": "https"})
    assert "strict-transport-security" not in response.headers


def test_api_docs_disabled_in_production(tmp_path):
    env = os.environ.copy()
    env.update(
        {
            "APP_ENV": "production",
            "DATABASE_URL": f"sqlite:///{(tmp_path / 'prod.db').as_posix()}",
            "SECRET_KEY": "production-test-secret",
            "QR_SECRET_KEY_CURRENT": "production-test-qr",
            "MEDIA_PHOTOS_DIR": str(tmp_path / "photos"),
        }
    )
    script = "from app.main import app; print(app.docs_url, app.redoc_url, app.openapi_url)"
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=BASE_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.split() == ["None", "None", "None"]


def test_templates_do_not_reference_external_assets():
    offenders = []
    for path in TEMPLATES.rglob("*.html"):
        content = path.read_text(encoding="utf-8")
        offenders.extend(f"{path.name}: {host}" for host in EXTERNAL_HOSTS if host in content)
    assert offenders == []


def test_inline_scripts_are_nonce_tagged():
    offenders = []
    for path in TEMPLATES.rglob("*.html"):
        content = path.read_text(encoding="utf-8")
        offenders.extend(
            f"{path.name}: {match.group(0)}"
            for match in INLINE_SCRIPT_WITHOUT_NONCE.finditer(content)
        )
    assert offenders == []
