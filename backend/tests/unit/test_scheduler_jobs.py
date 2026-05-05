import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.tasks import scheduler as scheduler_module
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


def test_configure_scheduler_jobs_registers_agent_pipeline_jobs(monkeypatch):
    monkeypatch.setenv("ENABLE_AGENT_PIPELINE_SCHEDULER", "1")
    monkeypatch.setenv("AGENT_PRE_MARKET_CRON_HOUR", "8")
    monkeypatch.setenv("AGENT_PRE_MARKET_CRON_MINUTE", "45")
    monkeypatch.setenv("AGENT_INTRADAY_CRON_HOUR", "10,13")
    monkeypatch.setenv("AGENT_INTRADAY_CRON_MINUTE", "20")
    monkeypatch.setenv("AGENT_POST_MARKET_CRON_HOUR", "18")
    monkeypatch.setenv("AGENT_POST_MARKET_CRON_MINUTE", "15")

    loop = asyncio.new_event_loop()
    try:
        sched = AsyncIOScheduler(timezone="UTC", event_loop=loop)
        summary = configure_scheduler_jobs(sched)

        job_ids = {job.id for job in sched.get_jobs()}
        assert {
            "agent_pipeline_pre_market",
            "agent_pipeline_intraday",
            "agent_pipeline_post_market",
        }.issubset(job_ids)
        assert summary["agent_pipelines"] == {
            "pre_market": ("8", "45"),
            "intraday": ("10,13", "20"),
            "post_market": ("18", "15"),
        }
    finally:
        loop.close()


def test_configure_scheduler_jobs_can_disable_agent_pipeline_jobs(monkeypatch):
    monkeypatch.setenv("ENABLE_AGENT_PIPELINE_SCHEDULER", "0")

    loop = asyncio.new_event_loop()
    try:
        sched = AsyncIOScheduler(timezone="UTC", event_loop=loop)
        summary = configure_scheduler_jobs(sched)

        job_ids = {job.id for job in sched.get_jobs()}
        assert summary["agent_pipelines"] == "disabled"
        assert not any(job_id.startswith("agent_pipeline_") for job_id in job_ids)
    finally:
        loop.close()


def test_scheduled_agent_pipeline_skips_non_trading_day(monkeypatch):
    monkeypatch.delenv("AGENT_PIPELINE_RUN_ON_NON_TRADING_DAYS", raising=False)
    monkeypatch.setattr(scheduler_module, "is_trading_day", lambda _today: False)

    result = scheduler_module._run_scheduled_agent_pipeline("pre-market")

    assert result == {
        "status": "skipped",
        "pipelineType": "pre-market",
        "reason": "non_trading_day",
    }
