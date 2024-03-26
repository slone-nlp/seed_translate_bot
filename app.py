#!/usr/bin/python3
# -*- coding: utf-8 -*-
import logging
import os

import telebot  # type: ignore
from flask import Flask, request

import models
from dialogue_management import DialogueManager

logging.basicConfig(level=logging.DEBUG)

logger = logging.getLogger(__name__)


TOKEN = os.environ["TOKEN"]
BASE_URL = os.environ.get("BASE_URL")
MONGO_URL = os.environ.get("MONGODB_URI")
TELEBOT_URL = "telegram/"

bot = telebot.TeleBot(TOKEN)

server = Flask(__name__)

DB: models.Database = models.Database.setup(mongo_url=MONGO_URL)

DM: DialogueManager = DialogueManager(bot=bot, db=DB)

PROCESSED_MESSAGES = set()


@server.route("/" + TELEBOT_URL)
def web_hook():
    bot.remove_webhook()
    bot.set_webhook(url=BASE_URL + TELEBOT_URL + TOKEN)
    return "!", 200


@server.route("/wakeup/")
def wake_up():
    web_hook()
    return "Маам, ну ещё пять минуточек!", 200


@server.route("/" + TELEBOT_URL + TOKEN, methods=["POST"])
def get_message():
    bot.process_new_updates(
        [telebot.types.Update.de_json(request.stream.read().decode("utf-8"))]
    )
    return "!", 200


ALL_CONTENT_TYPES = [
    "document",
    "text",
    "photo",
    "audio",
    "video",
    "location",
    "contact",
    "sticker",
]


@bot.message_handler(func=lambda message: True, content_types=ALL_CONTENT_TYPES)
def process_message(msg: telebot.types.Message):
    if msg.message_id in PROCESSED_MESSAGES:
        return
    PROCESSED_MESSAGES.add(msg.message_id)
    bot.send_chat_action(msg.chat.id, "typing")

    if msg.chat.type != "private":
        bot.reply_to(
            msg,
            "Я работаю только в приватных чатах. Удалите меня отсюда и напишите мне в личку!",
        )
        return

    DM.respond(msg)
