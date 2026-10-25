from tests.conftest import ADMIN_PASSWORD, USER_PASSWORD
from tests.helpers import login


def _status_for(client, path):
    response = client.get(path)
    return response.status_code


def test_anonymous_is_rejected_from_protected_views(client):
    assert client.get("/").status_code == 200
    assert client.get("/dashboard").status_code == 401
    assert client.get("/scan/").status_code == 401
    assert client.get("/lunch/scan").status_code == 401
    assert client.get("/students/").status_code == 401


def test_operator_only_accesses_exit_module(client):
    login(client, "operator", USER_PASSWORD)
    assert _status_for(client, "/scan/") == 200
    assert _status_for(client, "/reports/") == 200
    assert _status_for(client, "/api/dashboard/details?type=door") == 200
    assert _status_for(client, "/lunch/scan") == 403
    assert _status_for(client, "/api/dashboard/lunch/stats") == 403
    assert _status_for(client, "/students/") == 403


def test_lunch_operator_only_accesses_lunch_module(client):
    login(client, "lunch", USER_PASSWORD)
    assert _status_for(client, "/lunch/scan") == 200
    assert _status_for(client, "/api/dashboard/lunch/stats") == 200
    assert _status_for(client, "/scan/") == 403
    assert _status_for(client, "/reports/") == 403
    assert _status_for(client, "/api/dashboard/details?type=door") == 403
    assert _status_for(client, "/students/") == 403


def test_admin_accesses_every_module(client):
    login(client, "admin", ADMIN_PASSWORD)
    for path in (
        "/dashboard",
        "/scan/",
        "/reports/",
        "/lunch/scan",
        "/lunch/reports",
        "/students/",
        "/employees/",
        "/users/",
        "/doors/",
        "/api/dashboard/details?type=door",
        "/api/dashboard/lunch/stats",
    ):
        assert _status_for(client, path) == 200, path
