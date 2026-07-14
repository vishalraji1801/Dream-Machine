"""
Log viewer (Phase 6).

GET /api/logs            -> list of *.log files (name, size, mtime)
GET /api/logs/{name}     -> tail of that file (?lines=N, default 200)
"""
from fastapi import APIRouter, Depends, HTTPException, Query

from webapp.auth import require_token
from webapp.logs_reader import list_logs, tail_log
from webapp.settings import get_settings

router = APIRouter(prefix="/api/logs", dependencies=[Depends(require_token)])


@router.get("")
def logs() -> dict:
    return {"files": list_logs(get_settings().log_dir)}


@router.get("/{name}")
def tail(name: str, lines: int = Query(default=200, ge=1, le=5000)) -> dict:
    result = tail_log(get_settings().log_dir, name, lines)
    if result is None:
        raise HTTPException(status_code=404, detail="log not found")
    return result
