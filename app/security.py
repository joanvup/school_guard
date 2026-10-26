import secrets

from fastapi import Request

from .config import settings


def build_csp(nonce: str, https: bool) -> str:
    directives = [
        "default-src 'self'",
        f"script-src 'self' 'nonce-{nonce}'",
        # Los manejadores inline existentes se migrarán por fases; permitirlos
        # explícitamente evita abrir script-src a 'unsafe-inline'.
        "script-src-attr 'unsafe-inline'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob:",
        "font-src 'self'",
        "connect-src 'self'",
        "media-src 'self'",
        "worker-src 'self' blob:",
        "manifest-src 'self'",
        "frame-src 'none'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
    if https:
        directives.append("upgrade-insecure-requests")
    return "; ".join(directives)


def _is_https(request: Request) -> bool:
    forwarded = request.headers.get("x-forwarded-proto", "")
    first_proto = forwarded.split(",", 1)[0].strip().lower()
    return first_proto == "https" or request.url.scheme == "https"


async def security_headers_middleware(request: Request, call_next):
    nonce = secrets.token_urlsafe(16)
    request.state.csp_nonce = nonce

    response = await call_next(request)

    csp = build_csp(nonce, _is_https(request))
    if settings.csp_mode == "enforce":
        response.headers["Content-Security-Policy"] = csp
    elif settings.csp_mode == "report-only":
        response.headers["Content-Security-Policy-Report-Only"] = csp

    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(self), microphone=(), geolocation=(), payment=(), usb=()",
    )
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")

    if _is_https(request) and settings.hsts_max_age > 0:
        response.headers.setdefault(
            "Strict-Transport-Security",
            f"max-age={settings.hsts_max_age}",
        )
    return response
