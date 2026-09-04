"""APScheduler wiring: EOD refresh on trading weekdays in America/New_York.

The job runs at ``EOD_REFRESH_TIME`` (default 18:00 ET) Monday–Friday. Weekend
days never fire; market holidays fire but fetch nothing new (the incremental
refresh is idempotent and cheap), which keeps the calendar logic in one place —
the SPY-anchored trading calendar used by analytics.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import get_settings
from .routers.admin import run_scheduled_refresh

log = logging.getLogger(__name__)


def create_scheduler() -> BackgroundScheduler:
    s = get_settings()
    hour, minute = (int(x) for x in s.eod_refresh_time.split(":"))
    scheduler = BackgroundScheduler(timezone=s.app_timezone)
    scheduler.add_job(
        run_scheduled_refresh,
        CronTrigger(day_of_week="mon-fri", hour=hour, minute=minute),
        id="eod_refresh",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    return scheduler
