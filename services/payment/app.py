"""payment — charges the card.

Fault modes (set at runtime by the injector):
    slow          F1: every charge takes 3 s (orders times out at 2 s and retries).
    retry_storm   F4: the processor answers 503 for 50% of calls.

LOG_VARIANT=v2 is the "bad deploy" image for F7 (improvement 1 / E10): 2 of payment's
6 messages (~30%) are reworded — same behaviour, different text — and one genuinely new
ERROR message fires only while a real fault is active.
"""
import asyncio
import os
import random

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from common.logging_setup import get_logger, install

V2 = os.environ.get("LOG_VARIANT", "v1") == "v2"
DECLINE_P = 0.015
BUSY_P = 0.02  # one retry now and then is normal

log = get_logger()
app = FastAPI()
fault = {"mode": os.environ.get("FAULT_MODE", "none")}
install(app, fault)


class Charge(BaseModel):
    order: int
    amount: float


@app.post("/charge")
async def charge(c: Charge):
    if V2:
        log.info(f"Charging customer card for order {c.order} with amount {c.amount:.2f}")
    else:
        log.info(f"Charging card for order {c.order} amount {c.amount:.2f}")

    if fault["mode"] == "slow":
        await asyncio.sleep(3.0)
    busy_p = 0.5 if fault["mode"] == "retry_storm" else BUSY_P
    if V2 and fault["mode"] != "none":
        log.error(f"Ledger write failed code {random.choice([502, 503, 504])} for order {c.order}")

    if random.random() < busy_p:
        log.warning(f"Payment processor busy for order {c.order}, returning 503")
        return JSONResponse(status_code=503, content={"error": "busy"})
    if random.random() < DECLINE_P:
        log.warning(f"Card declined for order {c.order}")
        return JSONResponse(status_code=402, content={"error": "declined"})

    if V2:
        log.info(f"Payment successfully confirmed for order {c.order}")
    else:
        log.info(f"Payment confirmed for order {c.order}")
    log.info(f"Ledger entry written for order {c.order}")
    return {"order": c.order, "status": "confirmed"}
