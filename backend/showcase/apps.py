"""App config: interrupted-run bookkeeping, engine prewarm, optional auto-runs."""
from __future__ import annotations

import logging
import os

from django.apps import AppConfig

log = logging.getLogger("showcase.apps")


class ShowcaseConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "showcase"

    def ready(self) -> None:
        # Only in the actual server process (runserver sets RUN_MAIN); never during
        # tests, migrations or management commands, so no DB side effects there.
        if os.environ.get("RUN_MAIN") != "true":
            return

        self._mark_interrupted_runs()

        from django.conf import settings

        cfg = settings.SYSTEMONE
        if not cfg.get("PREWARM", True):
            return

        from showcase.services import engine, jobs

        def _warm_then_autorun():
            engine.warm()
            count = int(cfg.get("AUTORUN", 0) or 0)
            if count > 0:
                jobs.autorun_pending(count)

        engine.set_post_warm_hook(_warm_then_autorun)
        engine.warm_async()

    @staticmethod
    def _mark_interrupted_runs() -> None:
        """Runs left 'running'/'pending' by a server stop lost their worker thread;
        mark them errored so the UI never shows phantom progress."""
        try:
            from django.utils import timezone

            from showcase.models import ShowcaseRun

            n = ShowcaseRun.objects.filter(status__in=["pending", "running"]).update(
                status="error", error="interrupted by server restart",
                finished_at=timezone.now())
            if n:
                log.info("marked %d interrupted run(s) as errored", n)
        except Exception:
            # Database not ready yet (first boot before migrate) — nothing to clean.
            log.debug("interrupted-run cleanup skipped", exc_info=True)
