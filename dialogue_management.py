import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import List, Union

import telebot  # type: ignore

import models
import tasking
import texts
from states import States

logging.basicConfig(level=logging.DEBUG)

logger = logging.getLogger(__name__)


def render_markup(suggests=None, max_columns=3, initial_ratio=2):
    if suggests is None or len(suggests) == 0:
        return telebot.types.ReplyKeyboardRemove(selective=False)
    markup = telebot.types.ReplyKeyboardMarkup(
        row_width=max(1, min(max_columns, int(len(suggests) / initial_ratio)))
    )
    markup.add(*suggests)
    return markup


@dataclass
class FakeResult:
    user_id: int
    text: str
    message_id: int


class FakeBot:
    def __init__(self):
        self.messages: List[FakeResult] = []

    def send_message(self, user_id, text, reply_markup=None, parse_mode=None) -> FakeResult:
        result = FakeResult(user_id=user_id, text=text, message_id=len(self.messages))
        self.messages.append(result)
        return result

    @property
    def last_message(self):
        return self.messages[-1]


class DialogueManager:
    def __init__(self, db: models.Database, bot: Union[telebot.TeleBot, FakeBot]):
        self.db: models.Database = db
        self.bot: Union[telebot.TeleBot, FakeBot] = bot

    def send_text_to_user(
        self, user_id, text, reply_markup=None, suggests=None, parse_mode="html"
    ):
        if reply_markup is None:
            reply_markup = render_markup(suggests or [])
        logger.info("Response is:" + text)
        result = self.bot.send_message(
            user_id, text, reply_markup=reply_markup, parse_mode=parse_mode
        )
        # For some reason, markdown is malformed with urls
        self.db.mongo_messages.insert_one(
            {
                "user_id": user_id,
                "from_user": False,
                "text": text,
                "timestamp": datetime.utcnow(),
                "message_id": result.message_id,
            }
        )
        time.sleep(0.3)

    def respond(self, msg: telebot.types.Message):
        text = msg.text
        user_id = msg.from_user.id
        username = msg.from_user.username or "Anonymous"

        user: models.UserState = models.find_user(
            self.db.mongo_users, user=msg.from_user
        )

        self.db.mongo_messages.insert_one(
            {
                "user_id": user_id,
                "from_user": True,
                "text": text,
                "timestamp": datetime.utcnow(),
                "message_id": msg.message_id,
                "user_state_id": user.state_id,
            }
        )
        print("got message: '{}' from user {} ({})".format(text, user_id, username))

        suggested_suggests: List[str] = []
        default_markup = render_markup(suggested_suggests)

        if not text:
            self.send_text_to_user(
                user_id,
                "<i>Я пока не поддерживаю стикеры, фото и т.п.\nПожалуйста, пользуйтесь текстом и смайликами \U0001F642</i>",  # noqa
                reply_markup=default_markup,
            )
            print("class: no text detected")
        elif text in {"/start", "/help"}:
            resp = "\n\n".join([texts.HELP, texts.MENU])
            self.send_text_to_user(
                user_id, resp, reply_markup=default_markup, parse_mode="html"
            )

        # The setup scenario (here we enter only!)
        elif text in {"/setup"}:
            response, suggests = tasking.do_ask_setup(user=user)
            self.db.save_user(user)
            self.send_text_to_user(
                user.user_id, response, suggests=suggests, parse_mode="html"
            )

        elif text in {"/stats"}:
            response, suggests = tasking.do_get_project_status(user=user, db=self.db)
            self.db.save_user(user)
            self.send_text_to_user(
                user.user_id, response, suggests=suggests, parse_mode="html"
            )

        elif text in {"/guidelines"}:
            response, suggests = tasking.do_tell_guidelines(user=user, db=self.db)
            self.db.save_user(user)
            self.send_text_to_user(
                user.user_id, response, suggests=suggests, parse_mode="html"
            )

        elif text in {"/resume"}:
            # repeat the last message in the current task, without changing the state
            response, suggests = tasking.do_resume_task(user=user, db=self.db)
            self.db.save_user(user)
            self.send_text_to_user(
                user.user_id, response, suggests=suggests, parse_mode="html"
            )

        # The main scenario
        elif (
            text in {"/task"}
            or (user.state_id == States.SUGGEST_TASK and text in {texts.RESP_SKIP_TASK})
            or (
                user.state_id == States.SUGGEST_ONE_MORE_TASK
                and text in {texts.RESP_YES}
            )
        ):
            # TODO(nice): check if there is an unfinished current task, and deal with it properly
            task = self.db.get_new_task(user=user)
            if task is None:
                self.send_text_to_user(
                    user_id,
                    "Сейчас для вас нет никаких заданий! Попробуйте зайти позже, проверить чужие переводы.",
                    reply_markup=default_markup,
                )
            else:
                resp = f"Новое задание: #{task.task_id}."
                if task.prompt:
                    resp += "\n" + task.prompt
                resp += (
                    "\nГотовы к выполнению этого задания или хотите попробовать другое?"
                )
                suggests = [texts.RESP_TAKE_TASK, texts.RESP_SKIP_TASK]
                user.curr_proj_id = task.project_id
                user.curr_task_id = task.task_id
                user.state_id = States.SUGGEST_TASK
                self.db.save_user(user)
                self.send_text_to_user(
                    user_id, resp, suggests=suggests, parse_mode="html"
                )

        elif user.state_id == States.SUGGEST_ONE_MORE_TASK and text in {texts.RESP_NO}:
            resp, suggests = tasking.do_not_assing_new_task(user=user, db=self.db)
            self.db.save_user(user)
            self.send_text_to_user(user_id, resp, suggests=suggests)

        elif user.state_id == States.SUGGEST_TASK and text in {texts.RESP_TAKE_TASK}:
            task = (
                self.db.get_task(user.curr_task_id)
                if user.curr_task_id is not None
                else None
            )
            if task is None:
                self.send_text_to_user(
                    user_id, texts.RESP_TASK_LOST, reply_markup=default_markup
                )
                user.curr_task_id = None
                user.state_id = None
                self.db.save_user(user)
            else:
                task.locked = True
                self.db.save_task(task)
                user.pbar_num = 0
                user.pbar_den = len(self.db.get_unsolved_inputs_for_task(task=task))
                resp, suggests = tasking.do_assign_input(
                    user=user, db=self.db, task=task
                )
                self.db.save_user(user)
                self.send_text_to_user(user_id, resp, suggests=suggests)

        elif (
            user.state_id == States.ASK_COHERENCE and text in texts.COHERENCE_RESPONSES
        ):
            resp, suggests = tasking.do_save_coherence_and_continue(
                user=user, db=self.db, user_text=text
            )
            self.db.save_user(user)
            self.send_text_to_user(user_id, resp, suggests=suggests)

        elif user.state_id == States.ASK_XSTS and text in texts.XSTS_RESPONSES:
            resp, suggests = tasking.do_save_xsts_and_continue(
                user=user, db=self.db, user_text=text
            )
            self.db.save_user(user)
            self.send_text_to_user(user_id, resp, suggests=suggests)

        # States that expect a fixed text but get something else:
        # re-ask the same question
        elif (
            user.state_id == States.ASK_COHERENCE
            and text not in texts.COHERENCE_RESPONSES
        ):
            assert (
                user.curr_sent_id is not None
                and user.curr_result_id is not None
                and user.curr_label_id is not None
            )
            inp = self.db.get_input(input_id=user.curr_sent_id)
            res = self.db.get_translation(result_id=user.curr_result_id)
            label = self.db.get_label(label_id=user.curr_label_id)
            assert inp is not None and res is not None and label is not None
            resp, suggests = tasking.do_ask_coherence(
                user=user,
                db=self.db,
                inp=inp,
                res=res,
                label=label,
            )
            self.send_text_to_user(user_id, resp, suggests=suggests)
        elif user.state_id == States.ASK_XSTS and text not in texts.XSTS_RESPONSES:
            assert (
                user.curr_sent_id is not None
                and user.curr_result_id is not None
                and user.curr_label_id is not None
            )
            inp = self.db.get_input(input_id=user.curr_sent_id)
            res = self.db.get_translation(result_id=user.curr_result_id)
            label = self.db.get_label(label_id=user.curr_label_id)
            assert inp is not None and res is not None and label is not None
            resp, suggests = tasking.do_ask_xsts(
                user=user,
                db=self.db,
                inp=inp,
                res=res,
                label=label,
            )
            self.send_text_to_user(user_id, resp, suggests=suggests)

        # Free-form inputs; the intent depends only on the state
        # accepting any text as translation!
        elif user.state_id == States.ASK_TRANSLATION:
            resp, suggests = tasking.do_save_translation_and_ask_for_next(
                user=user, db=self.db, user_text=text
            )
            self.db.save_user(user)
            self.send_text_to_user(user_id, resp, suggests=suggests)

        elif user.state_id == States.SETUP_ASK_SRC_LANG:
            langs = [lang.strip() for lang in text.strip().split(",")]
            langs = [lang for lang in langs if lang]
            user.src_langs = langs
            response, suggests = tasking.do_ask_setup(user=user)
            self.db.save_user(user)
            self.send_text_to_user(
                user.user_id, response, suggests=suggests, parse_mode="html"
            )

        elif user.state_id == States.SETUP_ASK_TGT_LANG:
            langs = [lang.strip() for lang in text.strip().split(",")]
            langs = [lang for lang in langs if lang]
            user.tgt_langs = langs
            response, suggests = tasking.do_ask_setup(user=user)
            self.db.save_user(user)
            self.send_text_to_user(
                user.user_id, response, suggests=suggests, parse_mode="html"
            )

        elif user.state_id == States.SETUP_ASK_CONTACT_INFO:
            user.contact = text
            response, suggests = tasking.do_ask_setup(user=user)
            self.db.save_user(user)
            self.send_text_to_user(
                user.user_id, response, suggests=suggests, parse_mode="html"
            )

        # The last resort: non-contextual fallback
        else:
            self.send_text_to_user(
                user_id,
                texts.FALLBACK,
                reply_markup=default_markup,
            )
