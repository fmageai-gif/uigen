"""Concurrency tests: saving must never hang or error when the background
sync/backup thread is touching the same workbook (the cause of the Windows
"Saving…" freeze)."""

from __future__ import annotations

import threading
import time

from eqms.core.models import Audit
from eqms.data.audit_repository import AuditRepository


def test_concurrent_reads_and_writes_do_not_error(store):
    repo = AuditRepository(store)
    errors: list[str] = []
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            try:
                store.read_rows("AuditDatabase.xlsx", "Audits")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"read: {exc}")

    def writer(base: int):
        for i in range(10):
            try:
                repo.add(Audit(audit_id=f"A{base}-{i}", case_number=f"{base}-{i}",
                               genesys_id=f"g{base}-{i}", validation="Valid",
                               reason="RESOLVED", remarks="x"))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"write: {exc}")

    readers = [threading.Thread(target=reader) for _ in range(2)]
    writers = [threading.Thread(target=writer, args=(b,)) for b in range(3)]
    for t in readers:
        t.start()
    start = time.time()
    for t in writers:
        t.start()
    for t in writers:
        t.join(timeout=30)
    stop.set()
    for t in readers:
        t.join(timeout=5)

    assert not any(t.is_alive() for t in writers), "a writer hung (deadlock)"
    assert errors == [], f"errors during concurrent access: {errors[:5]}"
    assert len(repo.all(refresh=True)) == 30
    assert time.time() - start < 30
