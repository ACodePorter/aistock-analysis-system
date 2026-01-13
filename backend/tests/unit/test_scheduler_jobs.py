import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.tasks.scheduler import configure_scheduler_jobs


def test_configure_scheduler_jobs_registers_expected_jobs(monkeypatch):
    monkeypatch.setenv("CRON_HOUR", "7")
    monkeypatch.setenv("CRON_MINUTE", "5")
    monkeypatch.setenv("CRON_HOUR2", "8")
    monkeypatch.setenv("CRON_MINUTE2", "40")
    monkeypatch.setenv("MACRO_CRON_HOUR", "19")
    monkeypatch.setenv("MACRO_CRON_MINUTE", "10")
    monkeypatch.setenv("MACRO_TRAIN_CRON_HOUR", "20")
    monkeypatch.setenv("MACRO_TRAIN_CRON_MINUTE", "25")
    monkeypatch.setenv("MACRO_REPORT_CRON_HOUR", "21")
    monkeypatch.setenv("MACRO_REPORT_CRON_MINUTE", "5")

    loop = asyncio.new_event_loop()
    try:
        sched = AsyncIOScheduler(timezone="UTC", event_loop=loop)
        summary = configure_scheduler_jobs(sched)

        job_ids = {job.id for job in sched.get_jobs()}
        assert {
            "daily_pipeline",
            "daily_pipeline_post_close",
            "intelligent_news_collection",
            "legacy_news_collection",
            "macro_observation_pipeline",
            "macro_training_job",
            "macro_report_job",
        }.issubset(job_ids)

        assert summary["daily"] == (7, 5)
        assert summary["daily_post_close"] == (8, 40)
        assert summary["macro"] == (19, 10)
        assert summary["macro_train"] == (20, 25)
        assert summary["macro_report"] == (21, 5)
    finally:
        loop.close()
