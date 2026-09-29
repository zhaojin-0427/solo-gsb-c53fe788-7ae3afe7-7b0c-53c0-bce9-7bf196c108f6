"""剪辑素材授权覆盖台 —— FastAPI 入口。

启动: uvicorn app.main:app --host 0.0.0.0 --port 8000
浏览器访问: http://localhost:8000/
"""

from __future__ import annotations

from datetime import date as _date
from pathlib import Path
from typing import Any

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from . import db
from .verification import normalize_timeline, verify


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="剪辑素材授权覆盖台", version="1.0.0", lifespan=lifespan)


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------

class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("工程名称不能为空")
        return v


class TimelineIn(BaseModel):
    timeline: dict[str, Any]


class AuthorizationIn(BaseModel):
    material_id: str = Field(min_length=1)
    src_lo: int
    src_hi: int
    date_from: str
    date_to: str
    region: str = Field(min_length=1)
    channel: str = Field(min_length=1)
    note: str = ""

    @field_validator("material_id", "region", "channel", "note")
    @classmethod
    def _strip_str(cls, v: str) -> str:
        return v.strip()

    @field_validator("date_from", "date_to")
    @classmethod
    def _check_date(cls, v: str) -> str:
        try:
            _date.fromisoformat(v)
        except ValueError as exc:
            raise ValueError(f"日期必须是 ISO 格式 YYYY-MM-DD: {v}") from exc
        return v


class AuthorizationBatchIn(BaseModel):
    items: list[AuthorizationIn]


class VerifyIn(BaseModel):
    date: str
    region: str = Field(min_length=1)
    channel: str = Field(min_length=1)

    @field_validator("date")
    @classmethod
    def _check_date(cls, v: str) -> str:
        try:
            _date.fromisoformat(v)
        except ValueError as exc:
            raise ValueError(f"日期必须是 ISO 格式 YYYY-MM-DD: {v}") from exc
        return v

    @field_validator("region", "channel")
    @classmethod
    def _strip_str(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("不能为空")
        return v


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _require_project(conn, project_id: int) -> dict:
    project = db.get_project(conn, project_id)
    if project is None:
        raise HTTPException(404, f"工程 {project_id} 不存在")
    return project


def _require_timeline(project: dict) -> dict:
    if not project.get("timeline"):
        raise HTTPException(400, "该工程尚未导入时间线")
    return project["timeline"]


def _validate_authorization(timeline: dict, a: AuthorizationIn) -> dict:
    materials = {m["id"]: m for m in timeline["materials"]}
    if a.material_id not in materials:
        raise HTTPException(
            422, f"时间线中不存在素材 {a.material_id}，"
                 f"可选: {', '.join(sorted(materials)) or '(无)'}")
    if a.src_lo < 0:
        raise HTTPException(422, "授权源帧起点不能为负")
    if a.src_hi <= a.src_lo:
        raise HTTPException(422, "授权源帧区间必须是非空半开区间 [src_lo, src_hi)")
    total = materials[a.material_id]["total_frames"]
    if a.src_hi > total:
        raise HTTPException(
            422, f"授权源帧终点 {a.src_hi} 超出素材 {a.material_id} 总帧数 {total}")
    if a.date_from > a.date_to:
        raise HTTPException(422, "授权开始日期不能晚于结束日期（日期区间含首尾）")
    return a.model_dump()


# ---------------------------------------------------------------------------
# 工程接口
# ---------------------------------------------------------------------------

@app.get("/api/projects")
def api_list_projects():
    with db.get_conn() as conn:
        return {"projects": db.list_projects(conn)}


@app.post("/api/projects", status_code=201)
def api_create_project(body: ProjectIn):
    with db.get_conn() as conn:
        return db.create_project(conn, body.name)


@app.get("/api/projects/{project_id}")
def api_get_project(project_id: int):
    with db.get_conn() as conn:
        project = _require_project(conn, project_id)
        project["authorizations"] = db.list_authorizations(conn, project_id)
        return project


@app.patch("/api/projects/{project_id}")
def api_rename_project(project_id: int, body: ProjectIn):
    with db.get_conn() as conn:
        _require_project(conn, project_id)
        db.rename_project(conn, project_id, body.name)
        return db.get_project(conn, project_id)


@app.delete("/api/projects/{project_id}", status_code=204)
def api_delete_project(project_id: int):
    with db.get_conn() as conn:
        _require_project(conn, project_id)
        db.delete_project(conn, project_id)


# ---------------------------------------------------------------------------
# 时间线
# ---------------------------------------------------------------------------

@app.put("/api/projects/{project_id}/timeline")
def api_put_timeline(project_id: int, body: TimelineIn):
    try:
        timeline = normalize_timeline(body.timeline)
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(422, f"时间线格式错误: {exc}") from exc
    with db.get_conn() as conn:
        _require_project(conn, project_id)
        project = db.save_timeline(conn, project_id, timeline)
        return {"timeline": project["timeline"], "fps": project["fps"]}


# ---------------------------------------------------------------------------
# 授权
# ---------------------------------------------------------------------------

@app.get("/api/projects/{project_id}/authorizations")
def api_list_authorizations(project_id: int):
    with db.get_conn() as conn:
        _require_project(conn, project_id)
        return {"authorizations": db.list_authorizations(conn, project_id)}


@app.post("/api/projects/{project_id}/authorizations", status_code=201)
def api_add_authorization(project_id: int, body: AuthorizationIn):
    with db.get_conn() as conn:
        project = _require_project(conn, project_id)
        timeline = _require_timeline(project)
        data = _validate_authorization(timeline, body)
        auth = db.add_authorization(conn, project_id, data)
        return auth


@app.post("/api/projects/{project_id}/authorizations/batch", status_code=201)
def api_add_authorizations_batch(project_id: int, body: AuthorizationBatchIn):
    with db.get_conn() as conn:
        project = _require_project(conn, project_id)
        timeline = _require_timeline(project)
        created = []
        for item in body.items:
            data = _validate_authorization(timeline, item)
            created.append(db.add_authorization(conn, project_id, data))
        return {"authorizations": created, "count": len(created)}


@app.delete("/api/projects/{project_id}/authorizations/{auth_id}", status_code=204)
def api_delete_authorization(project_id: int, auth_id: int):
    with db.get_conn() as conn:
        _require_project(conn, project_id)
        if not db.delete_authorization(conn, project_id, auth_id):
            raise HTTPException(404, f"授权 {auth_id} 不存在")


# ---------------------------------------------------------------------------
# 核验
# ---------------------------------------------------------------------------

@app.post("/api/projects/{project_id}/verify")
def api_verify(project_id: int, body: VerifyIn):
    with db.get_conn() as conn:
        project = _require_project(conn, project_id)
        timeline = _require_timeline(project)
        auths = db.list_authorizations(conn, project_id)
        result = verify(timeline, auths, body.date, body.region, body.channel)
        db.save_last_verify(conn, project_id, result)
        return result


# ---------------------------------------------------------------------------
# 静态前端（放在 API 路由之后挂载）
# ---------------------------------------------------------------------------

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(_STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
