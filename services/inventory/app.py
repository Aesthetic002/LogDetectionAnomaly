"""inventory — reserves / releases stock in Postgres."""
import asyncio
import os
import random

import asyncpg
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from common.logging_setup import get_logger, install

DB_URL = os.environ.get("DB_URL", "postgresql://app:app@db:5432/shop")
DB_TIMEOUT = float(os.environ.get("DB_TIMEOUT_S", "1.5"))
ITEMS = {"pen": 500, "book": 300, "mug": 300, "lamp": 200}
RESTOCK_BELOW = 10
OUT_OF_STOCK_P = 0.015  # concurrent depletion by other channels: rare-but-normal path

log = get_logger()
app = FastAPI()
fault = {"mode": os.environ.get("FAULT_MODE", "none")}
install(app, fault)
pool: asyncpg.Pool | None = None


class Reserve(BaseModel):
    order: int
    item: str
    qty: int = 1


@app.on_event("startup")
async def startup():
    global pool
    for _ in range(60):
        try:
            pool = await asyncpg.create_pool(DB_URL, min_size=2, max_size=10)
            break
        except (OSError, asyncpg.PostgresError):
            await asyncio.sleep(1)
    async with pool.acquire() as con:
        await con.execute("CREATE TABLE IF NOT EXISTS stock (item TEXT PRIMARY KEY, qty INT NOT NULL)")
        for item, qty in ITEMS.items():
            await con.execute("INSERT INTO stock VALUES ($1, $2) ON CONFLICT (item) DO UPDATE SET qty = $2", item, qty)


async def db(fn):
    async def run():
        async with pool.acquire() as con:
            return await fn(con)
    return await asyncio.wait_for(run(), timeout=DB_TIMEOUT)


@app.post("/reserve")
async def reserve(r: Reserve):
    log.info(f"Reserve request for {r.qty} x {r.item} order {r.order}")
    try:
        avail = await db(lambda con: con.fetchval("SELECT qty FROM stock WHERE item = $1", r.item))
        if avail is None or avail < r.qty or random.random() < OUT_OF_STOCK_P:
            log.warning(f"Insufficient stock for {r.item}: requested {r.qty}, available {avail or 0}")
            return JSONResponse(status_code=409, content={"error": "insufficient stock"})
        remaining = await db(lambda con: con.fetchval(
            "UPDATE stock SET qty = qty - $2 WHERE item = $1 RETURNING qty", r.item, r.qty))
        log.info(f"Reserved {r.qty} x {r.item} for order {r.order}, remaining {remaining}")
        if remaining < RESTOCK_BELOW:
            await db(lambda con: con.execute("UPDATE stock SET qty = $2 WHERE item = $1", r.item, ITEMS[r.item]))
            log.info(f"Restocked {r.item} to {ITEMS[r.item]} units")
        return {"reserved": r.qty, "remaining": remaining}
    except (asyncio.TimeoutError, OSError, asyncpg.PostgresError) as e:
        log.error(f"Database query failed for order {r.order}: {type(e).__name__}")
        return JSONResponse(status_code=503, content={"error": "database unavailable"})


@app.post("/release")
async def release(r: Reserve):
    log.info(f"Release request for order {r.order}")
    try:
        await db(lambda con: con.execute("UPDATE stock SET qty = qty + $2 WHERE item = $1", r.item, r.qty))
        log.info(f"Released {r.qty} x {r.item} for order {r.order}")
        return {"released": r.qty}
    except (asyncio.TimeoutError, OSError, asyncpg.PostgresError) as e:
        log.error(f"Database query failed for order {r.order}: {type(e).__name__}")
        return JSONResponse(status_code=503, content={"error": "database unavailable"})
