from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from . import config, services

scheduler = AsyncIOScheduler(timezone=config.TZ)


def start():
    h, m = config.DAILY_AT.split(":")
    # 每天主任务：所有启用账号
    scheduler.add_job(services.run_all, CronTrigger(hour=int(h), minute=int(m), timezone=config.TZ), args=["schedule"],
                      id="daily", misfire_grace_time=3600, coalesce=True)
    # 整点补签：只处理今日尚未成功的账号
    scheduler.add_job(services.run_pending, CronTrigger(hour=config.RETRY_HOURS, minute=0, timezone=config.TZ), args=["retry"],
                      id="retry", misfire_grace_time=1800, coalesce=True)
    scheduler.start()
