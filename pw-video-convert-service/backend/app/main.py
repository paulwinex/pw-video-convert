from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.config import FRONTEND_DIST
from app.core.db import init_db
from app.core.log import get_logger
from app.models import Task
from app.tasks.manager import manager

logger = get_logger("main")

if not FRONTEND_DIST.exists():
    raise RuntimeError("No frontend dist found")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("init db...")
    init_db([Task])
    logger.info("start task manager...")
    await manager.start()
    yield
    logger.info("stop task manager...")
    await manager.stop()


app = FastAPI(title="pw-convert-service", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(FRONTEND_DIST / "index.html")


