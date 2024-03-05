#!/usr/bin/python3
# -*- coding: utf-8 -*-
import argparse
import logging
import os
import random
import time
from datetime import datetime
from typing import List

import telebot
from flask import Flask, request

import models
import tasking
import texts
from states import States

logging.basicConfig(level=logging.DEBUG)

logger = logging.getLogger(__name__)


TOKEN = os.environ["TOKEN"]
BASE_URL = os.environ.get("BASE_URL")
MONGO_URL = os.environ.get("MONGODB_URI")
TELEBOT_URL = "telegram/"

bot = telebot.TeleBot(TOKEN)

server = Flask(__name__)

DB: models.Database = models.Database.setup(mongo_url=MONGO_URL)

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


def render_markup(suggests=None, max_columns=3, initial_ratio=2):
    if suggests is None or len(suggests) == 0:
        return telebot.types.ReplyKeyboardRemove(selective=False)
    markup = telebot.types.ReplyKeyboardMarkup(
        row_width=max(1, min(max_columns, int(len(suggests) / initial_ratio)))
    )
    markup.add(*suggests)
    return markup


def text_is_like(text, pattern):
    def preprocess(s):
        return s.lower().strip()

    return preprocess(text) in {preprocess(p) for p in pattern}


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


def get_reply_markup_for_id(user_id):
    user_object = DB.mongo_users.find_one({"user_id": user_id})
    return render_markup_for_user_object(user_object)


def get_suggests_for_user_object(user_object) -> List[str]:
    return []


def shuffled(some_list):
    items = some_list[:]
    random.shuffle(items)
    return items


def render_markup_for_user_object(user_object):
    if user_object is None:
        return render_markup([])
    return render_markup(get_suggests_for_user_object(user_object))


def send_text_to_user(
    user_id, text, reply_markup=None, suggests=None, parse_mode="markdown"
):
    if reply_markup is None:
        reply_markup = render_markup(suggests or [])
    logger.info("Response is:" + text)
    result = bot.send_message(
        user_id, text, reply_markup=reply_markup, parse_mode=parse_mode
    )
    DB.mongo_messages.insert_one(
        {
            "user_id": user_id,
            "from_user": False,
            "text": text,
            "timestamp": datetime.utcnow(),
            "message_id": result.message_id,
        }
    )
    time.sleep(0.3)


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

    text = msg.text
    user_id = msg.from_user.id
    username = msg.from_user.username or "Anonymous"

    DB.mongo_messages.insert_one(
        {
            "user_id": user_id,
            "from_user": True,
            "text": text,
            "timestamp": datetime.utcnow(),
            "message_id": msg.message_id,
        }
    )
    print("got message: '{}' from user {} ({})".format(text, user_id, username))

    user: models.UserState = models.find_user(DB.mongo_users, user=msg.from_user)

    suggested_suggests = get_suggests_for_user_object(user)
    default_markup = render_markup(suggested_suggests)

    if not text:
        send_text_to_user(
            user_id,
            "<i>Я пока не поддерживаю стикеры, фото и т.п.\nПожалуйста, пользуйтесь текстом и смайликами \U0001F642</i>",  # noqa
            reply_markup=default_markup,
        )
        print("class: no text detected")
    elif text in {"/start", "/help"}:
        send_text_to_user(
            user_id, texts.HELP, reply_markup=default_markup, parse_mode="html"
        )

    # The setup scenario (here we enter only!)
    elif text in {"/setup"}:
        response, suggests = tasking.do_ask_setup(user=user)
        DB.save_user(user)
        send_text_to_user(user.user_id, response, suggests=suggests, parse_mode="html")

    # The main scenario
    elif (
        text in {"/task"}
        or (user.state_id == States.SUGGEST_TASK and text in {texts.RESP_SKIP_TASK})
        or (user.state_id == States.SUGGEST_ONE_MORE_TASK and text in {texts.RESP_YES})
    ):
        # TODO: check if there is an unfinished current task, and deal with it properly
        task = DB.get_new_task(user=user)
        if task is None:
            send_text_to_user(
                user_id,
                "Сейчас для вас нет никаких задач! Попробуйте зайти позже, проверить чужие переводы.",
                reply_markup=default_markup,
            )
        else:
            resp = f"Новая задача: #{task.task_id}."
            if task.prompt:
                resp += "\n" + task.prompt
            resp += "\nГотовы к выполнению задачи?"
            suggests = [texts.RESP_TAKE_TASK, texts.RESP_SKIP_TASK]
            user.curr_proj_id = task.project_id
            user.curr_task_id = task.task_id
            user.state_id = States.SUGGEST_TASK
            DB.save_user(user)
            send_text_to_user(
                user_id, resp, suggests=suggests, parse_mode="html"
            )  # For some reason, markdown is malformed with urls
    elif user.state_id == States.SUGGEST_TASK and text in {texts.RESP_TAKE_TASK}:
        task = DB.get_task(user.curr_task_id)
        if task is None:
            send_text_to_user(
                user_id, "Простите, задача потерялась.", reply_markup=default_markup
            )
            user.curr_task_id = None
            user.state_id = None
            DB.save_user(user)
            # TODO: suggest what to do next
        else:
            task.locked = True
            DB.save_task(task)
            resp, suggests = tasking.do_assign_input(user=user, db=DB, task=task)
            DB.save_user(user)
            send_text_to_user(user_id, resp, suggests=suggests)

    elif user.state_id == States.ASK_COHERENCE and text in texts.COHERENCE_RESPONSES:
        resp, suggests = tasking.do_save_coherence_and_ask_for_xsts(
            user=user, db=DB, user_text=text
        )
        DB.save_user(user)
        send_text_to_user(user_id, resp, suggests=suggests)

    elif user.state_id == States.ASK_XSTS and text in texts.XSTS_RESPONSES:
        resp, suggests = tasking.do_save_xsts_and_ask_for_translation(
            user=user, db=DB, user_text=text
        )
        DB.save_user(user)
        send_text_to_user(user_id, resp, suggests=suggests)

    # Free-form inputs; the intent depends only on the state
    # accepting any text as translation!
    elif user.state_id == States.ASK_TRANSLATION:
        resp, suggests = tasking.do_save_translation_and_ask_for_next(
            user=user, db=DB, user_text=text
        )
        DB.save_user(user)
        send_text_to_user(user_id, resp, suggests=suggests)

    elif user.state_id == States.SETUP_ASK_SRC_LANG:
        langs = [lang.strip() for lang in text.strip().split(",")]
        langs = [lang for lang in langs if lang]
        user.src_langs = langs
        response, suggests = tasking.do_ask_setup(user=user)
        DB.save_user(user)
        send_text_to_user(user.user_id, response, suggests=suggests, parse_mode="html")

    elif user.state_id == States.SETUP_ASK_TGT_LANG:
        langs = [lang.strip() for lang in text.strip().split(",")]
        langs = [lang for lang in langs if lang]
        user.tgt_langs = langs
        response, suggests = tasking.do_ask_setup(user=user)
        DB.save_user(user)
        send_text_to_user(user.user_id, response, suggests=suggests, parse_mode="html")

    elif user.state_id == States.SETUP_ASK_CONTACT_INFO:
        user.contact = text
        response, suggests = tasking.do_ask_setup(user=user)
        DB.save_user(user)
        send_text_to_user(user.user_id, response, suggests=suggests, parse_mode="html")

    # The last resort: non-contextual fallback
    else:
        send_text_to_user(
            user_id,
            texts.FALLBACK,
            reply_markup=default_markup,
        )


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
