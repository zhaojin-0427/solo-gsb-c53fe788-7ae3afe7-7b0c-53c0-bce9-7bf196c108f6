"""FastAPI application: 剪辑素材授权覆盖台."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import database as db
from . import verify


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="剪辑素材授权覆盖台", lifespan=lifespan)


# ---------- request models ----------

class ProjectCreate(BaseModel):
    name: str
    timeline: dict


class AuthPayload(BaseModel):
    source_start: int
    source_end: int
    valid_from: str
    valid_to: str
    region: str
    channel: str


class VerifyRequest(BaseModel):
    date: str
    region: str
    channel: str


# ---------- projects ----------

@app.post("/api/projects")
def create_project(payload: ProjectCreate):
    errors = verify.validate_timeline(payload.timeline)
    if errors:
        raise HTTPException(status_code=400, detail={"errors": errors})
    proj = db.create_project(payload.name, payload.timeline)
    return proj


@app.get("/api/projects")
def list_projects():
    return db.list_projects()


@app.get("/api/projects/{pid}")
def get_project(pid: str):
    proj = db.get_project(pid)
    if proj is None:
        raise HTTPException(status_code=404, detail="工程不存在")
    return proj


@app.delete("/api/projects/{pid}")
def delete_project(pid: str):
    if not db.delete_project(pid):
        raise HTTPException(status_code=404, detail="工程不存在")
    return {"ok": True}


# ---------- authorizations ----------

@app.post("/api/projects/{pid}/authorizations")
def create_authorization(pid: str, payload: AuthPayload):
    if db.get_project(pid) is None:
        raise HTTPException(status_code=404, detail="工程不存在")
    _validate_auth(payload)
    return db.create_authorization(pid, payload.model_dump())


@app.get("/api/projects/{pid}/authorizations")
def list_authorizations(pid: str):
    if db.get_project(pid) is None:
        raise HTTPException(status_code=404, detail="工程不存在")
    return db.list_authorizations(pid)


@app.put("/api/authorizations/{aid}")
def update_authorization(aid: str, payload: AuthPayload):
    _validate_auth(payload)
    if not db.update_authorization(aid, payload.model_dump()):
        raise HTTPException(status_code=404, detail="授权不存在")
    return {"ok": True}


@app.delete("/api/authorizations/{aid}")
def delete_authorization(aid: str):
    if not db.delete_authorization(aid):
        raise HTTPException(status_code=404, detail="授权不存在")
    return {"ok": True}


def _validate_auth(payload: AuthPayload) -> None:
    if payload.source_start < 0:
        raise HTTPException(status_code=400, detail="source_start 必须非负")
    if payload.source_end <= payload.source_start:
        raise HTTPException(status_code=400, detail="source_end 必须大于 source_start")
    if not payload.valid_from or not payload.valid_to:
        raise HTTPException(status_code=400, detail="有效期不能为空")
    if payload.valid_from > payload.valid_to:
        raise HTTPException(status_code=400, detail="valid_from 不能晚于 valid_to")
    if not payload.region.strip():
        raise HTTPException(status_code=400, detail="地区不能为空")
    if not payload.channel.strip():
        raise HTTPException(status_code=400, detail="渠道不能为空")


# ---------- verify ----------

@app.post("/api/projects/{pid}/verify")
def verify_project(pid: str, payload: VerifyRequest):
    proj = db.get_project(pid)
    if proj is None:
        raise HTTPException(status_code=404, detail="工程不存在")
    auths = db.list_authorizations(pid)
    result = verify.compute_violations(
        proj["timeline"], auths, payload.date, payload.region, payload.channel
    )
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


# ---------- static ----------

app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/")
def index():
    return FileResponse("app/static/index.html")
