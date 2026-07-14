"""
Log reader — list and tail the human-readable *.log files under logs/.

Deliberately narrow: only files ending in .log inside the configured log dir are
readable (never trades.db, .env, state, etc.), and names are reduced to a
basename so no path can escape the directory.
"""
import os
from typing import Optional


def _safe_path(log_dir: str, name: str) -> Optional[str]:
    base = os.path.basename(name)
    if not base.endswith(".log") or base != name:
        return None
    path = os.path.join(log_dir, base)
    # resolve and confirm containment
    real_dir = os.path.realpath(log_dir)
    real_path = os.path.realpath(path)
    if os.path.commonpath([real_dir, real_path]) != real_dir:
        return None
    return path if os.path.isfile(path) else None


def list_logs(log_dir: str) -> list[dict]:
    if not os.path.isdir(log_dir):
        return []
    out = []
    for name in os.listdir(log_dir):
        if name.endswith(".log"):
            p = os.path.join(log_dir, name)
            try:
                stat = os.stat(p)
            except OSError:
                continue
            out.append({"name": name, "size": stat.st_size, "mtime": int(stat.st_mtime)})
    return sorted(out, key=lambda f: f["mtime"], reverse=True)


def tail_log(log_dir: str, name: str, lines: int = 200) -> Optional[dict]:
    path = _safe_path(log_dir, name)
    if path is None:
        return None
    lines = max(1, min(lines, 5000))
    # read the tail block rather than the whole file
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        block = min(size, 256 * 1024)
        f.seek(size - block)
        data = f.read().decode("utf-8", errors="replace")
    tail = data.splitlines()[-lines:]
    return {"name": name, "lines": tail, "truncated": block < size}
