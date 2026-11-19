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
    assert len(run["lines"]) == run["summary"]["items"] + run["summary"]["stm_items"]
    assert run["summary"]["stm_items"] == sum(1 for r in run["lines"] if r["stm"])
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
    task = next(
        t for t in tl["tasks"] if t["line_code"] and t["line_group"] == "Линия ББЛ" and t["status"] != "Начат"
    )
    assert tl["off"] and "load" not in tl
    # остаток к выпуску; начатые в 1С этапы стоят на линии из 1С и идут первыми
    assert all(t["qty"] == t["qty_plan"] - t["qty_done"] for t in tl["tasks"])
    started = [t for t in tl["tasks"] if t["status"] == "Начат"]
    assert started and all(t["line_locked"] for t in started)
    assert all(t["line_1c"] for t in tl["tasks"])
    bbl = sorted(
        (t for t in tl["tasks"] if t["line_code"] == "BBL-1" and t["start"]), key=lambda t: t["start"]
    )
    statuses = [t["status"] for t in bbl]
    assert statuses == sorted(statuses, key=lambda s: s != "Начат")

    # выбор линии закрепляет линию, время считается автоматически
    other = "BBL-1" if task["line_code"] != "BBL-1" else "BBL-2"
    r = client.patch(f"/api/schedule/tasks/{task['id']}", json={"line_code": other, "pin_line": True})
    assert r.status_code == 200
    moved = next(t for t in client.get("/api/schedule").json()["tasks"] if t["id"] == task["id"])
    assert moved["line_code"] == other and moved["line_locked"]
    # на линию другой группы — нельзя
    bad = client.patch(f"/api/schedule/tasks/{task['id']}", json={"line_code": "IMA C51", "pin_line": True})
    assert bad.status_code == 422
    # начатый этап не двигается
    run = started[0]
    assert client.patch(f"/api/schedule/tasks/{run['id']}", json={"pin_line": False}).status_code == 422
    assert (
        client.put("/api/schedule/queues", json={"queues": {run["line_code"]: [run["id"]]}}).status_code
        == 422
    )

    # ручная очередь линии: переставляем два незапущенных заказа местами
    tasks = client.get("/api/schedule").json()["tasks"]
    line = next(
        code
        for code in {t["line_code"] for t in tasks}
        if sum(1 for t in tasks if t["line_code"] == code and t["status"] != "Начат") >= 2
    )
    queue = sorted(
        (t for t in tasks if t["line_code"] == line and t["status"] != "Начат"), key=lambda t: t["start"]
    )
    new_order = [queue[1]["id"], queue[0]["id"]] + [t["id"] for t in queue[2:]]
    assert client.put("/api/schedule/queues", json={"queues": {line: new_order}}).status_code == 200
    tasks = client.get("/api/schedule").json()["tasks"]
    on_line = sorted((t for t in tasks if t["line_code"] == line), key=lambda t: t["start"])
    assert [t["id"] for t in on_line if t["status"] != "Начат"][:2] == new_order[:2]
    assert [t["status"] == "Начат" for t in on_line] == sorted(
        (t["status"] == "Начат" for t in on_line), reverse=True
    )  # начатые — впереди
    assert all(t["seq"] == i for i, t in enumerate(t for t in on_line if t["status"] != "Начат"))
    assert client.delete(f"/api/schedule/queues/{line}").status_code == 200
    tasks = client.get("/api/schedule").json()["tasks"]
    assert all(t["seq"] is None for t in tasks)

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


def test_warehouse_roles(client, data_dir):
    from app.reference.warehouses import DEFAULT_ROLES

    client.post("/api/imports/from-folder")
    data = client.get("/api/warehouses").json()
    roles = {w["warehouse"]: w for w in data["warehouses"]}
    # роли по умолчанию — из справочника, для складов из отчёта и для известных, которых сейчас нет
    for name, w in roles.items():
        assert w["role"] == DEFAULT_ROLES.get(name, "ignore")
    mat = "Материальный склад"
    assert roles[mat]["role"] == "materials"
    run1 = client.post("/api/planning/stage2", json={"horizon_months": 3}).json()
    assert mat in run1["summary"]["warehouses"]["materials"]

    assert client.put("/api/warehouses", json={"warehouse": mat, "role": "ignore"}).status_code == 200
    w = next(x for x in client.get("/api/warehouses").json()["warehouses"] if x["warehouse"] == mat)
    assert w["role"] == "ignore" and w["manual"]
    run2 = client.post("/api/planning/stage2", json={"horizon_months": 3}).json()
    assert mat not in run2["summary"]["warehouses"].get("materials", [])

    client.put("/api/warehouses", json={"warehouse": mat, "role": None})
    w = next(x for x in client.get("/api/warehouses").json()["warehouses"] if x["warehouse"] == mat)
    assert w["role"] == "materials" and not w["manual"]
    assert client.put("/api/warehouses", json={"warehouse": "X", "role": "nonsense"}).status_code == 422


def test_capacity_summary(client):
    from datetime import date, timedelta

    from app.planning.calendar import workdays_in_month

    nxt = (date.today().replace(day=1) + timedelta(days=32)).replace(day=1)
    data = client.get("/api/calendars/capacity", params={"month": f"{nxt:%Y-%m}", "months": 2}).json()
    assert data["months"][0] == nxt.isoformat() and len(data["months"]) == 2
    bbl = next(g for g in data["groups"] if g["group"] == "Линия ББЛ")
    assert bbl["unit"] == "шт" and len(bbl["lines"]) == 3
    # по умолчанию 5/2, одна смена (8 ч) на трёх линиях; 17 283 шт за смену на линию
    days = workdays_in_month(nxt)
    assert bbl["months"][0]["hours"] == days * 8 * 3 and bbl["months"][0]["output"] == days * 3 * 17283
    assert bbl["total"] == sum(m["output"] for m in bbl["months"])
    assert any(g["unit"] == "кг" for g in data["groups"])


def test_line_from_1c_by_default(client, data_dir):
    from app.reference.lines import LINE_BY_CODE, line_from_1c

    client.post("/api/imports/from-folder")
    client.post("/api/planning/stage2", json={"horizon_months": 3})
    client.post("/api/schedule/sync")
    tasks = client.get("/api/schedule").json()["tasks"]
    for t in tasks:  # каждый заказ — на линии из 1С
        code = line_from_1c(t["line_1c"])
        if code and LINE_BY_CODE[code].group == t["line_group"]:
            assert (t["line_code"], t["line_locked"], t["line_source"]) == (code, True, "1c"), t["number"]

    t = next(t for t in tasks if t["status"] != "Начат" and t["line_group"] == "Линия ББЛ")
    other = next(c for c in ("BBL-1", "BBL-2", "BBL-3") if c != t["line_code"])
    client.patch(f"/api/schedule/tasks/{t['id']}", json={"line_code": other, "pin_line": True})
    client.post("/api/schedule/sync")  # ручной выбор не затирается загрузкой из 1С
    moved = next(x for x in client.get("/api/schedule").json()["tasks"] if x["id"] == t["id"])
    assert (moved["line_code"], moved["line_source"]) == (other, "manual")

    client.patch(f"/api/schedule/tasks/{t['id']}", json={"pin_line": False})
    auto = next(x for x in client.get("/api/schedule").json()["tasks"] if x["id"] == t["id"])
    assert auto["line_source"] == "auto" and not auto["line_locked"]

    client.patch(f"/api/schedule/tasks/{t['id']}", json={"from_1c": True})
    back = next(x for x in client.get("/api/schedule").json()["tasks"] if x["id"] == t["id"])
    assert (back["line_code"], back["line_source"]) == (t["line_code"], "1c")


def test_shelf_life_analysis(client, data_dir):
    assert client.get("/api/shelf-life").status_code == 404  # нет снимка
    client.post("/api/imports/from-folder")
    data = client.get("/api/shelf-life", params={"threshold_pct": 70, "fulfillment_pct": 100}).json()
    s = data["summary"]
    assert s["items"] > 0 and s["lots"] > 0 and s["stock"] > 0
    assert len(data["months"]) >= 12 and data["detail"] is None
    item = data["items"][0]["item"]
    detail = client.get("/api/shelf-life", params={"item": item}).json()["detail"]
    assert detail["item"] == item and detail["points"] and detail["lots"]
    # чем ниже выполнение плана, тем больше неликвида
    low = client.get("/api/shelf-life", params={"fulfillment_pct": 50, "replenish": False}).json()["summary"]
    full = client.get("/api/shelf-life", params={"fulfillment_pct": 100, "replenish": False}).json()[
        "summary"
    ]
    assert low["illiquid_forecast"] >= full["illiquid_forecast"]
