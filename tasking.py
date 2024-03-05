from typing import List, Optional, Tuple

import texts
from models import Database, TransInput, TransResult, TransTask, UserState
from states import States


def do_assign_input(
    user: UserState, db: Database, task: TransTask
) -> Tuple[str, List[str]]:
    inp: Optional[TransInput] = db.get_next_input(
        task=task, prev_sent_id=user.curr_sent_id
    )
    if inp is None:
        task.locked = False
        task.completions += 1
        # TODO: check the conditions whether the task is completed
        db.save_task(task)
        user.curr_sent_id = None
        user.curr_task_id = None
        user.state_id = States.SUGGEST_ONE_MORE_TASK
        return "В данном задании закончились примеры. Хотите взять ещё одно?", [
            texts.RESP_YES,
            texts.RESP_NO,
        ]

    trans_result = db.create_result(user=user, trans_input=inp)
    # todo: consider also the case of scoring the translations of other users
    trans_result.old_translation = inp.candidate

    # Case 1: start by asking a coherence question (and then XSTS)
    if trans_result.old_translation is not None:
        return do_ask_coherence(user=user, db=db, inp=inp, res=trans_result)

    # Case 2: start directly by asking for a translation
    return do_ask_to_translate(user=user, db=db, inp=inp, res=trans_result)


def do_ask_to_translate(
    user: UserState, db: Database, inp: TransInput, res: TransResult
) -> Tuple[str, List[str]]:
    print("the problematic source is", inp)
    src_text = inp.source
    response = (
        f"Вот исходный текст: *{src_text}*\n\nПожалуйста, предложите его перевод:"
    )
    # TODO: indicate the language.
    user.curr_sent_id = inp.input_id
    user.state_id = States.ASK_TRANSLATION
    db.save_result(res)
    user.curr_result_id = res.submission_id
    return response, []


def do_ask_coherence(
    user: UserState, db: Database, inp: TransInput, res: TransResult
) -> Tuple[str, List[str]]:
    response = f"Вот исходный текст: *{inp.source}*\n\nВот перевод: *{res.old_translation}*\n\n{texts.COHERENCE_PROMPT}"
    suggests = texts.COHERENCE_RESPONSES
    user.curr_sent_id = inp.input_id
    user.state_id = States.ASK_COHERENCE
    db.save_result(res)
    user.curr_result_id = res.submission_id
    return response, suggests


def do_ask_xsts(
    user: UserState, db: Database, inp: TransInput, res: TransResult
) -> Tuple[str, List[str]]:
    response = f"Вот исходный текст: *{inp.source}*\n\nВот перевод: *{res.old_translation}*\n\n{texts.XSTS_PROMPT}"
    suggests = texts.XSTS_RESPONSES
    user.curr_sent_id = inp.input_id
    user.state_id = States.ASK_XSTS
    db.save_result(res)
    user.curr_result_id = res.submission_id
    return response, suggests


def do_save_coherence_and_ask_for_xsts(
    user: UserState, db: Database, user_text: str
) -> Tuple[str, List[str]]:
    # Save the result
    inp = db.get_input(input_id=user.curr_sent_id)
    res = db.get_result(result_id=user.curr_result_id)
    res.old_translation_coherence = texts.COHERENCE_RESPONSES_MAP.get(user_text)
    db.save_result(res)
    # ask for a new translation
    return do_ask_xsts(user=user, db=db, inp=inp, res=res)


def do_save_xsts_and_ask_for_translation(
    user: UserState, db: Database, user_text: str
) -> Tuple[str, List[str]]:
    # Save the result
    score_value = int(user_text)
    inp = db.get_input(input_id=user.curr_sent_id)
    res = db.get_result(result_id=user.curr_result_id)
    res.old_translation_score = score_value
    db.save_result(res)
    # ask for a new translation
    return do_ask_to_translate(user=user, db=db, inp=inp, res=res)


def do_save_translation_and_ask_for_next(
    user: UserState, db: Database, user_text: str
) -> Tuple[str, List[str]]:
    # Save the result
    res = db.get_result(result_id=user.curr_result_id)
    res.new_translation = str(user_text)
    db.save_result(res)
    user.curr_result_id = None

    # Ask for a new translation in the same task
    task = db.get_task(task_id=res.task_id)
    return do_assign_input(user=user, db=db, task=task)
