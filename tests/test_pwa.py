import json
import re
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parent.parent / "app" / "static"


def test_manifest_icons_exist(client):
    manifest = json.loads((STATIC_DIR / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["scope"] == "/"
    assert manifest["start_url"] == "/"
    assert {icon["purpose"] for icon in manifest["icons"]} >= {"any", "maskable"}

    for icon in manifest["icons"]:
        path = STATIC_DIR / icon["src"].removeprefix("/static/")
        assert path.is_file(), f"Falta el icono {icon['src']}"
        response = client.get(icon["src"])
        assert response.status_code == 200


def test_service_worker_precache_files_exist():
    source = (STATIC_DIR / "sw.js").read_text(encoding="utf-8")
    urls = set(re.findall(r"'(/static/[^']+)'", source))

    assert urls
    for url in urls:
        path = STATIC_DIR / url.removeprefix("/static/")
        assert path.is_file(), f"El service worker precachea un archivo inexistente: {url}"


def test_service_worker_is_served_from_root_scope(client):
    response = client.get("/sw.js")

    assert response.status_code == 200
    assert response.headers["service-worker-allowed"] == "/"
    assert response.headers["cache-control"] == "no-cache"
    assert "javascript" in response.headers["content-type"]


def test_service_worker_does_not_cache_dynamic_routes():
    source = (STATIC_DIR / "sw.js").read_text(encoding="utf-8")

    assert "/api/" not in source
    assert "PRECACHE_PATHS.has" in source
