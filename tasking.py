from models import Database, TransTask, TransInput, TransResult, UserState
import texts
from states import States
from typing import Optional, Tuple, List


def do_assign_input(user: UserState, db: Database, task: TransTask) -> Tuple[str, List[str]]:
    inp: Optional[TransInput] = db.get_next_input(task=task, prev_sent_id=user.curr_sent_id)
    if inp is None:
        # TODO: maybe unblock the task, if it is blocked
        # TODO: set the state
        return "В данном задании закончились примеры. Хотите взять ещё одно?", ["Да", "Нет"]

    trans_result = db.create_result(user=user, trans_input=inp)
    # todo: consider also the case of scoring the translations of other users
    trans_result.old_translation = inp.candidate

    # Case 1: start by asking an XSTS question
    if trans_result.old_translation is not None:
        # TODO: start by asking the coherence question
        response = f"Вот исходный текст: *{inp.source}*\n\nВот перевод: *{trans_result.old_translation}*\n\n{texts.XSTS_PROMPT}"
        suggests = texts.XSTS_RESPONSES
        user.curr_sent_id = inp.input_id
        user.state_id = States.ASK_XSTS
        db.save_result(trans_result)
        user.curr_result_id = trans_result.submission_id
        return response, suggests

    # Case 2: start by asking for a translation
    return do_ask_to_translate(user=user, db=db, inp=inp, res=trans_result)


def do_ask_to_translate(user: UserState, db: Database, inp: TransInput, res: TransResult) -> Tuple[str, List[str]]:
    print("the problematic source is", inp)
    src_text = inp.source
    response = f"Вот исходный текст: *{src_text}*\n\nПожалуйста, предложите его перевод:"
    # TODO: indicate the language.
    user.curr_sent_id = inp.input_id
    user.state_id = States.ASK_TRANSLATION
    db.save_result(res)
    user.curr_result_id = res.submission_id
    return response, []


def do_save_xsts_and_ask_for_translation(user: UserState, db: Database, user_text: str) -> Tuple[str, List[str]]:
    # Save the result
    score_value = int(user_text)
    inp = db.get_input(input_id=user.curr_sent_id)
    res = db.get_result(result_id=user.curr_result_id)
    res.old_translation_score = score_value
    db.save_result(res)
    # ask for a new translation
    return do_ask_to_translate(user=user, db=db, inp=inp, res=res)


def do_save_translation_and_ask_for_next(user: UserState, db: Database, user_text: str) -> Tuple[str, List[str]]:
    # Save the result
    res = db.get_result(result_id=user.curr_result_id)
    res.new_translation = str(user_text)
    db.save_result(res)
    user.curr_result_id = None

    # Ask for a new translation in the same task
    task = db.get_task(task_id=res.task_id)
    return do_assign_input(user=user, db=db, task=task)
