from __future__ import annotations

import asyncio
import logging

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .routes import control, ws
from .serial_link import serial_link

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    serial_task = asyncio.create_task(serial_link.run(), name="serial-link")
    logger.info("Motorinador backend started")
    try:
        yield
    finally:
        serial_task.cancel()
        try:
            await serial_task
        except asyncio.CancelledError:
            pass
        logger.info("Motorinador backend stopped")


app = FastAPI(title="Motorinador API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True, "serial": "open" if serial_link.connected else "closed"}


app.include_router(control.router)
app.include_router(ws.router)
