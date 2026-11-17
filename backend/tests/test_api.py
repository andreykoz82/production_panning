import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db import Base, get_session
from app.main import app


@pytest.fixture()
def client():
    # одна in-memory БД на все запросы
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)

    def override():
        with TestSession() as s:
            yield s

    app.dependency_overrides[get_session] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_lines(client):
    lines = client.get("/api/reference/lines").json()
    assert len(lines) == 17
    bbl = next(line for line in lines if line["code"] == "BBL-1")
    assert bbl["per_hour"] == pytest.approx(2160.38, abs=0.01)


def test_import_from_folder_and_read_back(client, data_dir):
    snap = client.post("/api/imports/from-folder").json()
    assert snap["summary"]["items_in_scope"] > 100
    assert client.get("/api/imports").json()[0]["id"] == snap["id"]

    issues = client.get(f"/api/imports/{snap['id']}/issues").json()
    order = {"error": 0, "warning": 1, "info": 2}
    assert [order[i["severity"]] for i in issues] == sorted(order[i["severity"]] for i in issues)
    items = client.get(f"/api/imports/{snap['id']}/items").json()
    assert len(items) == snap["summary"]["items_total"]


def test_upload(client, data_dir):
    files = [
        ("files", (p.name, p.read_bytes(), "application/octet-stream"))
        for p in sorted(data_dir.glob("*.xlsx"))
    ]
    snap = client.post("/api/imports/upload", files=files).json()
    assert snap["source"] == "upload"
    assert snap["summary"]["orders_stage2"] > 0


def test_unknown_snapshot(client):
    assert client.get("/api/imports/999").status_code == 404


def test_stage2_run_and_export(client, data_dir):
    client.post("/api/imports/from-folder")
    run = client.post("/api/planning/stage2", json={"horizon_months": 3, "calc_date": "2026-11-17"}).json()
    assert run["summary"]["items"] > 100
    assert len(run["lines"]) == run["summary"]["items"]
    assert client.get("/api/planning/runs").json()[0]["id"] == run["id"]
    xlsx = client.get(f"/api/planning/runs/{run['id']}/export")
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"


def test_stage2_without_snapshot(client):
    assert client.post("/api/planning/stage2", json={"horizon_months": 3}).status_code == 404


def test_calendars_and_gantt(client, data_dir):
    client.post("/api/imports/from-folder")
    client.post("/api/planning/stage2", json={"horizon_months": 3})
    grid = client.get("/api/calendars", params={"month": "2026-11"}).json()
    assert len(grid["days"]) == 30 and any(line["line_code"] == "BBL-1" for line in grid["lines"])

    sync = client.post("/api/schedule/sync").json()
    assert sync["added"] == sync["total"] == sync["tasks"] > 0
    tl = client.get("/api/schedule").json()
    task = next(t for t in tl["tasks"] if t["line_code"] and t["line_group"] == "Линия ББЛ")
    assert tl["off"] and tl["load"]

    # перетаскивание фиксирует заказ; на линию другой группы — нельзя
    other = "BBL-1" if task["line_code"] != "BBL-1" else "BBL-2"
    assert client.patch(f"/api/schedule/tasks/{task['id']}", json={"line_code": other}).status_code == 200
    moved = next(t for t in client.get("/api/schedule").json()["tasks"] if t["id"] == task["id"])
    assert moved["locked"] and moved["line_code"] == other
    bad = client.patch(f"/api/schedule/tasks/{task['id']}", json={"line_code": "IMA C51"})
    assert bad.status_code == 422

    # календарь: шаблон 24/7 и правка дня
    assert (
        client.put(
            "/api/calendars/template", json={"line_code": "BBL-1", "mode": "24/7", "shifts": 3}
        ).status_code
        == 200
    )
    change = {"changes": [{"line_code": "BBL-2", "day": "2026-11-21", "shifts": 2, "reason": "аврал"}]}
    assert client.put("/api/calendars/days", json=change).status_code == 200
    grid = client.get("/api/calendars", params={"month": "2026-11"}).json()
    bbl2 = next(line for line in grid["lines"] if line["line_code"] == "BBL-2")
    day = next(d for d in bbl2["days"] if d["day"] == "2026-11-21")
    assert day["shifts"] == 2 and day["manual"] and day["reason"] == "аврал"
    assert (
        client.delete("/api/calendars/month", params={"month": "2026-11", "line_code": "BBL-2"}).status_code
        == 200
    )


def test_sync_without_snapshot(client):
    assert client.post("/api/schedule/sync").status_code == 404
