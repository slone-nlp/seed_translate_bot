#!/usr/bin/python3
# -*- coding: utf-8 -*-
import argparse
import logging
import os

import sentry_sdk

from app import bot, server, web_hook

logging.basicConfig(level=logging.DEBUG)

logger = logging.getLogger(__name__)

if os.getenv("SENTRY_DSN", None) is not None:
    sentry_sdk.init(os.environ["SENTRY_DSN"])  # type: ignore


def main():
    parser = argparse.ArgumentParser(description="Run the bot")
    parser.add_argument("--poll", action="store_true")

    args = parser.parse_args()
    if args.poll:
        bot.remove_webhook()
        bot.polling()
    else:
        web_hook()
        server.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))


if __name__ == "__main__":
    main()
