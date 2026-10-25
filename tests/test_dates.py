from tests.conftest import ADMIN_PASSWORD
from tests.helpers import login


def test_invalid_report_dates_return_422(client):
    login(client, "admin", ADMIN_PASSWORD)

    assert client.get("/reports/?date_start=no-es-fecha").status_code == 422
    assert client.get("/reports/?date_start=2026-10-10&date_end=2026-10-01").status_code == 422
    assert (
        client.get("/reports/export?date_start=2026-13-01&date_end=2026-13-02").status_code == 422
    )
    assert client.get("/lunch/reports?date_start=2026-13-01").status_code == 422
    assert client.get("/api/dashboard/details?type=door&date=2026-13-01").status_code == 422
