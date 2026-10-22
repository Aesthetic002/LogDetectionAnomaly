"""Shared JSON logging + trace-ID propagation for the demo services (note 06).

Every log line is one JSON object on stdout:
    {"ts": "...Z", "level": "INFO", "service": "orders", "trace_id": "a91f3c...", "msg": "..."}
"""
import contextvars
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from pydantic import BaseModel

trace_var = contextvars.ContextVar("trace_id", default="-")
SERVICE = os.environ.get("SERVICE_NAME", "unknown")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z"),
            "level": record.levelname,
            "service": SERVICE,
            "trace_id": trace_var.get(),
            "msg": record.getMessage(),
        })


def get_logger() -> logging.Logger:
    log = logging.getLogger(SERVICE)
    if not log.handlers:
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(JsonFormatter())
        log.addHandler(h)
        log.setLevel(logging.INFO)
        log.propagate = False
    return log


def trace_headers() -> dict:
    """Headers for every outbound call so the next service joins the same trace."""
    return {"X-Trace-Id": trace_var.get()}


class FaultBody(BaseModel):
    mode: str = "none"


def install(app: FastAPI, fault_state: dict) -> None:
    """Trace middleware + /health + the runtime fault switch used by the injector.

    The fault switch is the runtime equivalent of flipping FAULT_MODE in the compose
    file; it never logs, so the fault itself leaves no tell-tale line in the logs.
    """

    @app.middleware("http")
    async def trace_mw(request: Request, call_next):
        tid = request.headers.get("X-Trace-Id") or uuid.uuid4().hex[:12]
        token = trace_var.set(tid)
        try:
            response = await call_next(request)
        finally:
            trace_var.reset(token)
        response.headers["X-Trace-Id"] = tid
        return response

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": SERVICE}

    @app.get("/admin/fault")
    async def get_fault():
        return fault_state

    @app.post("/admin/fault")
    async def set_fault(body: FaultBody):
        fault_state["mode"] = body.mode
        return fault_state
