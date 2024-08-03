#!/usr/bin/python3
# -*- coding: utf-8 -*-
import argparse
import logging
import os

import sentry_sdk
from apscheduler.schedulers.background import BackgroundScheduler  # type: ignore

from app import DM, bot, server, web_hook

logging.basicConfig(level=logging.DEBUG)

logger = logging.getLogger(__name__)

if os.getenv("SENTRY_DSN", None) is not None:
    sentry_sdk.init(os.environ["SENTRY_DSN"])  # type: ignore


def main():
    parser = argparse.ArgumentParser(description="Run the bot")
    parser.add_argument("--poll", action="store_true")

    scheduler = BackgroundScheduler()
    # https://apscheduler.readthedocs.io/en/stable/modules/triggers/cron.html
    # the time in UTC, so the pushes will be sent each 21 pm (by Moscow time)
    scheduler.add_job(DM.run_reminders, "cron", hour=18, jitter=60 * 1)
    # scheduler.add_job(hr.update_data, 'interval', minutes=15, jitter=300)
    # # scheduler.add_job(pusher.wake_up, 'cron', minute='*/5') # debug every 5 minutes
    # scheduler.add_job(pusher.check_jobs, 'interval', minutes=1, jitter=15)

    args = parser.parse_args()
    if args.poll:
        bot.remove_webhook()
        bot.polling()
    else:
        web_hook()
        server.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))


if __name__ == "__main__":
    main()
