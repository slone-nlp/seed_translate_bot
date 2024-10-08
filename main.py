#!/usr/bin/python3
# -*- coding: utf-8 -*-
import argparse
import logging
import os

import sentry_sdk
from apscheduler.schedulers.background import BackgroundScheduler  # type: ignore

from app import DB, DM, bot, server, web_hook

logging.basicConfig(level=logging.DEBUG)

logger = logging.getLogger(__name__)

if os.getenv("SENTRY_DSN", None) is not None:
    sentry_sdk.init(os.environ["SENTRY_DSN"])  # type: ignore


scheduler = BackgroundScheduler()
# https://apscheduler.readthedocs.io/en/stable/modules/triggers/cron.html

# the time in UTC, so the pushes will be sent each 21 pm (by Moscow time)
scheduler.add_job(DM.run_reminders, "cron", hour=18, jitter=60 * 1)

# Rerun the scheduler every couple of hours (with a jitter of a whole hour)
scheduler.add_job(DM.run_reminders, "interval", hours=2, jitter=60 * 60)

# Update the tasks statuses every 3 hours
scheduler.add_job(DB.update_all_task_statuses, "interval", hours=3, jitter=60 * 60)


def main():
    parser = argparse.ArgumentParser(description="Run the bot")
    parser.add_argument("--poll", action="store_true")

    scheduler.start()
    args = parser.parse_args()
    if args.poll:
        bot.remove_webhook()
        bot.polling()
    else:
        web_hook()
        server.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))


if __name__ == "__main__":
    main()
