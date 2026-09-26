"""Background run jobs: one active engine run at a time (GPU singleton), progress via DB rows."""
from __future__ import annotations

import logging
import threading

from django.db import connection
from django.utils import timezone

from showcase.models import Decision, Record, ShowcaseRun
from showcase.services import engine, registry, runner

log = logging.getLogger("showcase.jobs")

_LOCK = threading.Lock()
_ACTIVE: threading.Thread | None = None


def is_busy() -> bool:
    return _ACTIVE is not None and _ACTIVE.is_alive()


def latest(use_case: str | None = None, kind_running_only: bool = False) -> ShowcaseRun | None:
    qs = ShowcaseRun.objects.all()
    if use_case:
        qs = qs.filter(use_case=use_case)
    if kind_running_only:
        # Prefer the actually-running job over queued ones (a sweep pre-creates pending rows).
        running = qs.filter(status="running").order_by("-id").first()
        if running:
            return running
        qs = qs.filter(status="pending")
    return qs.order_by("-id").first()


def _finish(run: ShowcaseRun, error: str) -> None:
    run.status = "error"
    run.error = error[:2000]
    run.finished_at = timezone.now()
    run.save(update_fields=["status", "error", "finished_at"])


def _worker(run_ids: list[int]) -> None:
    global _ACTIVE
    try:
        for run_id in run_ids:
            run = ShowcaseRun.objects.filter(id=run_id).first()
            if run is None or run.status == "error":
                continue
            try:
                runner.run_use_case(run, run.use_case, limit=run.total or None)
            except Exception as exc:
                log.exception("run %s (%s) failed", run_id, run.use_case)
                _finish(run, f"{type(exc).__name__}: {exc}")
    finally:
        connection.close()
        with _LOCK:
            _ACTIVE = None


def _start(runs: list[ShowcaseRun]) -> list[ShowcaseRun]:
    global _ACTIVE
    with _LOCK:
        if is_busy():
            raise RuntimeError("a run is already active — wait for it to finish")
        t = threading.Thread(target=_worker, args=([r.id for r in runs],),
                             name=f"hs-run-{runs[0].id}", daemon=True)
        _ACTIVE = t
        t.start()
    return runs


def start_run(key: str, limit: int | None = None) -> ShowcaseRun:
    registry.get(key)  # validates
    total = Record.objects.filter(use_case=key).count()
    if limit:
        total = min(total, int(limit))
    if total == 0:
        raise ValueError(f"no records for '{key}' — seed the demo data first")
    run = ShowcaseRun.objects.create(use_case=key, status="pending", total=total, message="queued")
    try:
        _start([run])
    except RuntimeError:
        run.delete()
        raise
    return run


def start_run_all() -> list[ShowcaseRun]:
    if is_busy():
        raise RuntimeError("a run is already active — wait for it to finish")
    runs = []
    for key in registry.USE_CASE_ORDER:
        total = Record.objects.filter(use_case=key).count()
        if total == 0:
            continue
        runs.append(ShowcaseRun.objects.create(use_case=key, status="pending", total=total,
                                               message="queued (full sweep)"))
    if not runs:
        raise ValueError("no records at all — seed the demo data first")
    try:
        _start(runs)
    except RuntimeError:
        for r in runs:
            r.delete()
        raise
    return runs


def autorun_pending(count: int) -> list[ShowcaseRun]:
    """Auto-run the first `count` use cases that have records but no decisions yet (launcher UX)."""
    keys = [k for k in registry.USE_CASE_ORDER
            if Record.objects.filter(use_case=k).exists()
            and not Decision.objects.filter(record__use_case=k).exists()]
    keys = keys[:max(0, count)]
    if not keys or is_busy():
        return []
    runs = [ShowcaseRun.objects.create(use_case=k, status="pending",
                                       total=Record.objects.filter(use_case=k).count(),
                                       message="queued (auto-run)") for k in keys]
    log.info("auto-running %d use case(s): %s", len(runs), ", ".join(keys))
    _start(runs)
    return runs


def engine_status() -> dict:
    return engine.status()
