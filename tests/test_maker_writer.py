"""Strategy Maker — Commit 24: single-writer registry under parallel emit (test 25)."""
import sqlite3
import threading

import pytest

from maker.registry import Registry
from maker.writer import SingleWriter


def _rec(i):
    return {"cid": f"c{i}", "family": f"fam{i % 10}", "stage": "SCREEN", "status": "FAIL"}


def test_parallel_emit_exactly_n_rows_no_loss(tmp_path):
    reg = Registry(str(tmp_path / "t.db"))
    writer = SingleWriter(reg).start()
    n_workers, per_worker = 8, 100

    def worker(w):
        for j in range(per_worker):
            writer.emit(_rec(w * per_worker + j))

    threads = [threading.Thread(target=worker, args=(w,)) for w in range(n_workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    writer.close()

    total = n_workers * per_worker
    assert writer.written == total
    assert reg.count() == total                          # exactly N rows, zero lost writes


def test_append_only_still_enforced_after_writer(tmp_path):
    reg = Registry(str(tmp_path / "t.db"))
    with SingleWriter(reg) as w:
        w.emit(_rec(1))
    conn = sqlite3.connect(str(tmp_path / "t.db"))
    with pytest.raises(sqlite3.Error):                    # append-only invariant intact
        conn.execute("DELETE FROM trials"); conn.commit()
