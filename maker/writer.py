"""maker/writer.py — single-writer registry (Strategy Maker, spec section 16.5).

The registry is the only serialized resource in a parallel campaign. Workers run trials
concurrently and EMIT trial records to a queue; a single writer thread drains the queue
and performs every insert. No worker touches the DB — this is both the throughput fix
and the append-only enforcement point (one writer, in insertion order, zero lost writes).
"""
import queue
import threading


class SingleWriter:
    def __init__(self, registry):
        self.registry = registry
        self._q = queue.Queue()
        self._stop = object()
        self._thread = None
        self.written = 0

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def emit(self, record: dict):
        """Called from any worker thread — just enqueues; never touches the DB."""
        self._q.put(record)

    def _run(self):
        while True:
            rec = self._q.get()
            if rec is self._stop:
                break
            self.registry.record(**rec)
            self.written += 1

    def close(self):
        """Flush the queue and stop the writer (blocks until all records are written)."""
        self._q.put(self._stop)
        if self._thread is not None:
            self._thread.join()

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.close()
