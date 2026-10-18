import json
import logging
import os
import time
import uuid
from collections import deque
from datetime import datetime, timezone

from fastapi import FastAPI, Query, Request
from fastapi.responses import Response
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST

EMAIL = "23f2004697@ds.study.iitm.ac.in"
START_TIME = time.monotonic()

app = FastAPI(title="Production Observability API")

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total number of HTTP requests",
)

recent_logs = deque(maxlen=1000)


class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({
            "level": record.levelname.lower(),
            "ts": datetime.now(timezone.utc).isoformat(),
            "message": record.getMessage(),
        })


logger = logging.getLogger("observability")
logger.setLevel(logging.INFO)
logger.handlers.clear()

handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logger.addHandler(handler)
logger.propagate = False


@app.middleware("http")
async def observe_requests(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    started = time.monotonic()
    status_code = 500

    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        REQUEST_COUNT.inc()

        entry = {
            "level": "info" if status_code < 500 else "error",
            "ts": datetime.now(timezone.utc).isoformat(),
            "path": request.url.path,
            "request_id": request_id,
            "method": request.method,
            "status_code": status_code,
            "duration_ms": round((time.monotonic() - started) * 1000, 3),
        }

        recent_logs.append(entry)
        logger.info(json.dumps(entry))


@app.get("/work")
def work(n: int = Query(default=1, ge=0)):
    return {"email": EMAIL, "done": n}


@app.get("/healthz")
def healthz():
    return {
        "status": "ok",
        "uptime_s": float(max(0.0, time.monotonic() - START_TIME)),
    }


@app.get("/metrics")
def metrics():
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )


@app.get("/logs/tail")
def logs_tail(limit: int = Query(default=100, ge=1, le=1000)):
    return list(reversed(list(recent_logs)[-limit:]))
