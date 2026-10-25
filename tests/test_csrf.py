from tests.conftest import ADMIN_PASSWORD
from tests.helpers import csrf_headers, login


def test_login_without_csrf_is_forbidden(client):
    response = client.post(
        "/login",
        data={"username": "admin", "password": ADMIN_PASSWORD},
    )
    assert response.status_code == 403


def test_mutations_require_csrf_and_post_verb(client):
    login(client, "admin", ADMIN_PASSWORD)

    assert client.post("/students/delete/999").status_code == 403
    assert client.get("/students/delete/999").status_code == 405

    response = client.post(
        "/students/delete/999",
        headers=csrf_headers(client),
        follow_redirects=False,
    )
    assert response.status_code == 303
