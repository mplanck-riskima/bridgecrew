"""Test that reload_schedules loads maintainer jobs into APScheduler."""
from unittest.mock import patch, MagicMock
from bson import ObjectId
import pytest


def _fake_maintainer(cron="0 9 * * *"):
    return {
        "_id": ObjectId("507f1f77bcf86cd799439011"),
        "name": "Daily Check",
        "cron_expr": cron,
        "enabled": True,
        "project_id": "proj1",
    }


@pytest.fixture(autouse=True)
def reset_scheduler():
    """Reset the scheduler singleton before each test."""
    import app.scheduler as sched_module
    sched_module._scheduler = None
    yield
    # Cleanup: reset after test
    sched_module._scheduler = None


def test_maintainer_job_added_to_scheduler():
    from app.scheduler import reload_schedules, get_scheduler

    with patch("app.db.scheduled_tasks_col") as stc, \
         patch("app.db.project_maintainers_col") as pmc:
        stc.return_value.find.return_value = []
        pmc.return_value.find.return_value = [_fake_maintainer()]

        reload_schedules()

    scheduler = get_scheduler()
    job_ids = [job.id for job in scheduler.get_jobs()]
    assert any(jid.startswith("maintainer:") for jid in job_ids)


def test_invalid_maintainer_cron_is_skipped():
    from app.scheduler import reload_schedules, get_scheduler

    with patch("app.db.scheduled_tasks_col") as stc, \
         patch("app.db.project_maintainers_col") as pmc:
        stc.return_value.find.return_value = []
        pmc.return_value.find.return_value = [_fake_maintainer(cron="bad cron")]

        reload_schedules()

    scheduler = get_scheduler()
    job_ids = [job.id for job in scheduler.get_jobs()]
    assert not any(jid.startswith("maintainer:") for jid in job_ids)
