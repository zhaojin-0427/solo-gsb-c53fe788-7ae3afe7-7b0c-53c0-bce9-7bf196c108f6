"""FastAPI 端到端测试（临时 SQLite 数据库）。"""

import pytest
from fastapi.testclient import TestClient

from app import db


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    from app.main import app
    db.init_db()
    with TestClient(app) as c:
        yield c


TIMELINE = {
    "fps": 25,
    "materials": [
        {"id": "A", "total_frames": 1000, "segments": [
            {"id": "S1", "in": 0, "out": 100, "origin": 0, "speed": 1},
        ]},
        {"id": "B", "total_frames": 1000, "segments": [
            {"id": "S2", "in": 50, "out": 150, "origin": 500, "speed": "-1/2"},
        ]},
    ],
}


def test_index_page(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "剪辑素材授权覆盖台" in r.text
    assert client.get("/static/app.js").status_code == 200


def test_project_lifecycle_and_verify(client):
    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]

    # 未导入时间线即登记授权 / 核验 => 400
    r = client.post(f"/api/projects/{pid}/verify",
                    json={"date": "2026-09-29", "region": "CN", "channel": "TV"})
    assert r.status_code == 400

    assert client.put(f"/api/projects/{pid}/timeline",
                      json={"timeline": TIMELINE}).status_code == 200

    # 坏时间线 => 422
    bad_tl = {"total_frames": 10, "segments": [
        {"in": 0, "out": 5, "origin": 0, "speed": 0}]}
    r = client.put(f"/api/projects/{pid}/timeline", json={"timeline": bad_tl})
    assert r.status_code == 422

    # 授权校验：未知素材 / 越界 / 坏日期
    assert client.post(f"/api/projects/{pid}/authorizations", json={
        "material_id": "ZZ", "src_lo": 0, "src_hi": 10,
        "date_from": "2026-01-01", "date_to": "2026-12-31",
        "region": "CN", "channel": "TV"}).status_code == 422
    assert client.post(f"/api/projects/{pid}/authorizations", json={
        "material_id": "A", "src_lo": 0, "src_hi": 9999,
        "date_from": "2026-01-01", "date_to": "2026-12-31",
        "region": "CN", "channel": "TV"}).status_code == 422
    assert client.post(f"/api/projects/{pid}/authorizations", json={
        "material_id": "A", "src_lo": 0, "src_hi": 10,
        "date_from": "not-a-date", "date_to": "2026-12-31",
        "region": "CN", "channel": "TV"}).status_code in (422, 400)

    # 初始核验：全部违规
    v = client.post(f"/api/projects/{pid}/verify",
                    json={"date": "2026-09-29", "region": "CN", "channel": "TV"}).json()
    assert v["status"] == "ok"
    assert v["violating_frames"] == 150
    # 活动帧并集 [0,150)
    assert v["active_frames"] == 150

    # 只登记一个片段的授权，另一片段维度不符 => 重叠区 [50,100) 仍违规，
    # 且合并运行保留两条片段原因
    client.post(f"/api/projects/{pid}/authorizations", json={
        "material_id": "A", "src_lo": 0, "src_hi": 100,
        "date_from": "2026-01-01", "date_to": "2026-12-31",
        "region": "CN", "channel": "TV", "note": "a"})
    client.post(f"/api/projects/{pid}/authorizations", json={
        "material_id": "B", "src_lo": 475, "src_hi": 525,
        "date_from": "2026-01-01", "date_to": "2026-12-31",
        "region": "US", "channel": "TV", "note": "b-wrong-region"})
    v = client.post(f"/api/projects/{pid}/verify",
                    json={"date": "2026-09-29", "region": "CN", "channel": "TV"}).json()
    assert [(x["out"], x["out_end"]) for x in v["violations"]] == [(50, 150)]
    run = v["violations"][0]
    pieces = {p["segment_id"]: p for p in run["segments"]}
    assert set(pieces) == {"S2"}  # S1 已全覆盖
    assert pieces["S2"]["reason_code"] == "DIMENSION_MISMATCH"
    assert pieces["S2"]["candidates"][0]["mismatch"] == ["region"]

    # 删除维度不符的授权，换上匹配授权 => 干净
    aid = client.get(f"/api/projects/{pid}/authorizations").json()["authorizations"][1]["id"]
    assert client.delete(f"/api/projects/{pid}/authorizations/{aid}").status_code == 204
    # S2 倒放映射源帧 500..451，故需覆盖 [451,501)
    client.post(f"/api/projects/{pid}/authorizations", json={
        "material_id": "B", "src_lo": 451, "src_hi": 501,
        "date_from": "2026-01-01", "date_to": "2026-12-31",
        "region": "CN", "channel": "TV"})
    v = client.post(f"/api/projects/{pid}/verify",
                    json={"date": "2026-09-29", "region": "CN", "channel": "TV"}).json()
    assert v["violating_frames"] == 0

    # 最近核验结果已持久化
    g = client.get(f"/api/projects/{pid}").json()
    assert g["last_verify"]["violating_frames"] == 0


def test_out_of_bounds_rejected_via_api(client):
    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]
    client.put(f"/api/projects/{pid}/timeline", json={"timeline": {
        "total_frames": 100,
        "segments": [{"id": "X", "in": 0, "out": 40,
                      "origin": 10, "speed": -1}],
    }})
    v = client.post(f"/api/projects/{pid}/verify",
                    json={"date": "2026-09-29", "region": "CN", "channel": "TV"}).json()
    assert v["status"] == "rejected"
    assert v["violations_out_of_bounds"][0]["segment_id"] == "X"


def test_404_and_delete(client):
    assert client.get("/api/projects/999").status_code == 404
    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]
    assert client.delete(f"/api/projects/{pid}").status_code == 204
    assert client.get(f"/api/projects/{pid}").status_code == 404
