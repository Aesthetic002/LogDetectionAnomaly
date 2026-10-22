"""orders — creates the order, reserves stock (inventory), charges (payment).

Fault modes (set at runtime by the injector):
    skip_reserve  F3: logic bug — the inventory step is silently skipped; no error line.
"""
import asyncio
import itertools
import os
import random
import time

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from common.logging_setup import get_logger, install, trace_headers

INVENTORY_URL = os.environ.get("INVENTORY_URL", "http://inventory:8000")
PAYMENT_URL = os.environ.get("PAYMENT_URL", "http://payment:8000")
CALL_TIMEOUT = float(os.environ.get("CALL_TIMEOUT_S", "2.0"))
MAX_PAYMENT_ATTEMPTS = 4
PRICES = {"pen": 15.0, "book": 499.0, "mug": 249.0, "lamp": 1299.0}

log = get_logger()
app = FastAPI()
fault = {"mode": os.environ.get("FAULT_MODE", "none")}
install(app, fault)


async def call(url: str, body: dict) -> httpx.Response:
    """A fresh client per call: a shared pool can be exhausted by slow calls during a fault
    (F1) and never recover, which would silently cut orders off from every downstream."""
    async with httpx.AsyncClient(timeout=CALL_TIMEOUT) as c:
        return await c.post(url, json=body, headers=trace_headers())
order_ids = itertools.count(random.randint(10_000, 50_000))


class OrderIn(BaseModel):
    user: int
    item: str
    qty: int = 1


async def release(oid: int, item: str, qty: int):
    log.info(f"Calling inventory to release stock for order {oid}")
    try:
        await call(f"{INVENTORY_URL}/release", {"order": oid, "item": item, "qty": qty})
    except httpx.HTTPError:
        log.error(f"Stock release failed for order {oid}")


@app.post("/orders")
async def create_order(o: OrderIn):
    log.info(f"Received order request from user {o.user} for item {o.item}")
    oid = next(order_ids)
    amount = PRICES.get(o.item, 99.0) * o.qty
    log.info(f"Created order {oid} for user {o.user}")

    reserved = False
    if fault["mode"] != "skip_reserve":
        log.info(f"Calling inventory to reserve {o.qty} x {o.item} for order {oid}")
        t0 = time.perf_counter()
        try:
            r = await call(f"{INVENTORY_URL}/reserve", {"order": oid, "item": o.item, "qty": o.qty})
        except httpx.TimeoutException:
            log.error(f"Inventory call timed out after {int((time.perf_counter() - t0) * 1000)} ms for order {oid}")
            return JSONResponse(status_code=504, content={"order": oid, "error": "inventory timeout"})
        except httpx.HTTPError as e:
            log.error(f"Inventory service unreachable for order {oid}: {type(e).__name__}")
            return JSONResponse(status_code=503, content={"order": oid, "error": "inventory unreachable"})
        if r.status_code == 409:
            log.warning(f"Order {oid} rejected: insufficient stock for {o.item}")
            return JSONResponse(status_code=409, content={"order": oid, "error": "insufficient stock"})
        if r.status_code != 200:
            log.error(f"Inventory returned status {r.status_code} for order {oid}")
            return JSONResponse(status_code=503, content={"order": oid, "error": "inventory error"})
        log.info(f"Stock reserved for order {oid}")
        reserved = True

    for attempt in range(1, MAX_PAYMENT_ATTEMPTS + 1):
        if attempt > 1:
            log.info(f"Retrying payment attempt {attempt} for order {oid}")
            await asyncio.sleep(0.1 * attempt)
        log.info(f"Calling payment to charge order {oid} amount {amount:.2f}")
        t0 = time.perf_counter()
        try:
            r = await call(f"{PAYMENT_URL}/charge", {"order": oid, "amount": amount})
        except httpx.TimeoutException:
            log.error(f"Payment call timed out after {int((time.perf_counter() - t0) * 1000)} ms for order {oid}")
            continue
        except httpx.HTTPError as e:
            log.error(f"Payment service unreachable for order {oid}: {type(e).__name__}")
            break
        if r.status_code == 200:
            log.info(f"Payment accepted for order {oid}")
            log.info(f"Order {oid} completed")
            return {"order": oid, "status": "completed"}
        if r.status_code == 402:
            log.warning(f"Order {oid} rejected: card declined")
            if reserved:
                await release(oid, o.item, o.qty)
            return JSONResponse(status_code=402, content={"order": oid, "error": "card declined"})
        if r.status_code == 503:
            log.warning(f"Payment busy for order {oid}")
            continue
        log.error(f"Payment returned status {r.status_code} for order {oid}")
        break

    log.error(f"Order {oid} failed after {attempt} payment attempts")
    if reserved:
        await release(oid, o.item, o.qty)
    return JSONResponse(status_code=503, content={"order": oid, "error": "payment failed"})
