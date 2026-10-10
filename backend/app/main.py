from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config, scheduler, security, services
from .api.routes import router
from .db import SessionLocal, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with SessionLocal() as db:
        services.seed(db)
    services.recover_interrupted()
    if config.SCHEDULER_ENABLED:
        scheduler.start()
    print(f"[sign] 已启动，管理 token …{security.ADMIN_TOKEN[-6:]}（完整值见 {config.DATA_DIR / 'admin.token'} 或 SIGN_ADMIN_TOKEN）", flush=True)
    yield
    if scheduler.scheduler.running:
        scheduler.scheduler.shutdown(wait=False)


app = FastAPI(title="Sign 自动签到服务", lifespan=lifespan)
app.include_router(router)


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"ok": True}

_static = Path(__file__).resolve().parents[2] / "frontend"
if _static.is_dir():
    @app.get("/")
    def index():
        return FileResponse(_static / "index.html")
    app.mount("/static", StaticFiles(directory=_static), name="static")
