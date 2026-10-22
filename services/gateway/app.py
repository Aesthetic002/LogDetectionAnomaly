"""gateway — entry point. Creates the trace ID and forwards the checkout to orders."""
import os
import time

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from common.logging_setup import get_logger, install, trace_headers

ORDERS_URL = os.environ.get("ORDERS_URL", "http://orders:8000")
BLOCKED_USERS = range(495, 501)  # ~1% of users fail auth: rare-but-normal path

log = get_logger()
app = FastAPI()
fault = {"mode": os.environ.get("FAULT_MODE", "none")}
install(app, fault)
client = httpx.AsyncClient(timeout=8.0)


class Checkout(BaseModel):
    user: int
    item: str
    qty: int = 1


def respond(status: int, body: dict, t0: float) -> JSONResponse:
    log.info(f"Response sent with status {status} in {int((time.perf_counter() - t0) * 1000)} ms")
    return JSONResponse(status_code=status, content=body)


@app.post("/checkout")
async def checkout(c: Checkout):
    t0 = time.perf_counter()
    log.info(f"Checkout request received for user {c.user} item {c.item} qty {c.qty}")
    if c.user in BLOCKED_USERS:
        log.warning(f"Auth rejected for user {c.user}")
        return respond(401, {"error": "unauthorized"}, t0)
    log.info(f"Auth ok for user {c.user}")
    log.info("Forwarding order to orders service")
    try:
        r = await client.post(f"{ORDERS_URL}/orders", json=c.model_dump(), headers=trace_headers())
    except httpx.HTTPError as e:
        log.error(f"Orders service call failed: {type(e).__name__}")
        return respond(502, {"error": "orders unavailable"}, t0)
    return respond(r.status_code, r.json() if r.content else {}, t0)
