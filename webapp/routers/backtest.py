"""
Backtest runner (Phase 5).

GET  /api/backtest/data       -> stored timeframes + symbol counts
POST /api/backtest            -> start a job, returns {job_id}
GET  /api/backtest/{job_id}   -> poll status/result
"""
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from webapp.auth import require_token
from webapp.backtest_jobs import get_jobs
from webapp.settings import get_settings

router = APIRouter(prefix="/api/backtest", dependencies=[Depends(require_token)])


class RunRequest(BaseModel):
    strategy: str = ""
    timeframe: str = "15min"
    window: int = 60
    overrides: dict[str, Any] = {}
    symbols: Optional[list[str]] = None


def _jobs():
    return get_jobs(get_settings().config_path)


@router.get("/data")
def data() -> dict:
    return _jobs().data_summary()


@router.post("")
def run(req: RunRequest) -> dict:
    try:
        job_id = _jobs().submit(req.strategy, req.timeframe, req.window,
                                req.overrides, req.symbols)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"job_id": job_id}


@router.get("/{job_id}")
def status(job_id: str) -> dict:
    job = _jobs().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="unknown job")
    return job
