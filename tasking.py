from typing import List, Optional, Tuple

import texts
from models import Database, TransInput, TransResult, TransTask, UserState, TransLabel, TransStatus
from states import States


def do_assign_input(
    user: UserState, db: Database, task: TransTask
) -> Tuple[str, List[str]]:
    # we do a loop, because we may need to skip some inputs
    for attempt in range(100):
        inp: Optional[TransInput] = db.get_next_unsolved_input(
            task=task,
            prev_sent_id=user.curr_sent_id,
        )
        # No input means that the task is completed
        if inp is None:
            task.locked = False
            task.completions += 1
            # TODO: check the conditions whether the task is completed, and update ts status
            db.save_task(task)
            user.curr_sent_id = None
            user.curr_task_id = None
            user.state_id = States.SUGGEST_ONE_MORE_TASK
            return "В данном задании закончились примеры. Хотите взять ещё одно?", [
                texts.RESP_YES,
                texts.RESP_NO,
            ]

        # depending on the task, either choose the candidates to score or ask for a new translation
        candidates = db.get_translations_for_input(inp)
        other_candidates = [candidate for candidate in candidates if candidate.user_id != user.user_id]
        if len(other_candidates) > 0:
            # Case 1: ask to score a candidate!
            candidate = other_candidates[0]
            label = db.create_label(user_id=user.user_id, trans_result=candidate)
            return do_ask_coherence(user=user, db=db, inp=inp, res=candidate, label=label)
        else:
            # Case 2: nothing to score; start directly by asking for a translation
            if db.user_has_unscored_translations_for_input(user_id=user.user_id, input_id=inp.input_id):
                # if there is a translation by the current user, don't ask for a new one, and skip to the next input
                continue
            return do_ask_to_translate(user=user, db=db, inp=inp)
    return f"Произошло что-то странное. Пожалуйста, напишите @cointegrated, что по задаче {task.task_id} вам не смогли выдать текст.", []


def do_ask_to_translate(
    user: UserState, db: Database, inp: TransInput,
) -> Tuple[str, List[str]]:
    src_text = inp.source
    response = (
        f"Вот исходный текст: *{src_text}*\n\nПожалуйста, предложите его перевод:"
    )
    # TODO: maybe indicate the target language.
    user.state_id = States.ASK_TRANSLATION
    user.curr_proj_id = inp.project_id
    user.curr_task_id = inp.task_id
    user.curr_sent_id = inp.input_id
    user.curr_result_id = None
    user.curr_label_id = None
    return response, []


def do_ask_coherence(
    user: UserState, db: Database, inp: TransInput, res: TransResult, label: TransLabel,
) -> Tuple[str, List[str]]:
    user.state_id = States.ASK_COHERENCE
    response = f"Вот исходный текст: *{inp.source}*\n\nВот перевод: *{res.translation}*\n\n{texts.COHERENCE_PROMPT}"
    suggests = texts.COHERENCE_RESPONSES

    db.save_label(label)
    user.curr_proj_id = inp.project_id
    user.curr_task_id = inp.task_id
    user.curr_sent_id = inp.input_id
    user.curr_result_id = res.translation_id
    user.curr_label_id = label.label_id
    return response, suggests


def do_ask_xsts(
    user: UserState, db: Database, inp: TransInput, res: TransResult, label: TransLabel,
) -> Tuple[str, List[str]]:
    user.state_id = States.ASK_XSTS
    response = f"Вот исходный текст: *{inp.source}*\n\nВот перевод: *{res.translation}*\n\n{texts.XSTS_PROMPT}"
    suggests = texts.XSTS_RESPONSES

    db.save_label(label)
    user.curr_proj_id = inp.project_id
    user.curr_task_id = inp.task_id
    user.curr_sent_id = inp.input_id
    user.curr_result_id = res.translation_id
    user.curr_label_id = label.label_id
    return response, suggests


def do_save_coherence_and_ask_for_xsts(
    user: UserState, db: Database, user_text: str
) -> Tuple[str, List[str]]:
    # Save the result
    inp = db.get_input(input_id=user.curr_sent_id)
    res = db.get_translation(result_id=user.curr_result_id)
    label = db.get_label(label_id=user.curr_label_id)
    label.coherence_score = texts.COHERENCE_RESPONSES_MAP.get(user_text)
    db.save_label(label)
    # ask for a new translation
    return do_ask_xsts(user=user, db=db, inp=inp, res=res, label=label)


def do_save_xsts_and_ask_for_translation_or_assign_next_input(
    user: UserState, db: Database, user_text: str
) -> Tuple[str, List[str]]:
    # Save the result
    score_value = int(user_text)
    inp = db.get_input(input_id=user.curr_sent_id)
    task = db.get_task(task_id=inp.task_id)
    res = db.get_translation(result_id=user.curr_result_id)
    label = db.get_label(label_id=user.curr_label_id)
    label.semantics_score = score_value
    db.save_label(label)

    # approve or reject the translation based on the label
    project = db.get_project(project_id=user.curr_proj_id)
    if label.is_coherent and label.semantics_score >= project.min_score:
        accepted = True
        res.n_approvals += 1
        if res.n_approvals >= project.overlap and res.status != TransStatus.REJECTED:
            res.status = TransStatus.ACCEPTED
    else:
        accepted = False
        res.status = TransStatus.REJECTED
    db.save_translation(res)

    # if the translation is accepted, the translation input is solved
    if res.status == TransStatus.ACCEPTED:
        inp.solved = True
        db.save_input(inp)

    # if the user has accepted a translation, no reason in asking for a new one; jumping to the next input
    if accepted:
        return do_assign_input(user=user, db=db, task=task)

    # if the user has unscored translations for this input, we won't ask them for new ones
    if db.user_has_unscored_translations_for_input(user_id=user.user_id, input_id=inp.input_id):
        return do_assign_input(user=user, db=db, task=task)

    # ask for a new translation
    return do_ask_to_translate(user=user, db=db, inp=inp)


def do_save_translation_and_ask_for_next(
    user: UserState, db: Database, user_text: str
) -> Tuple[str, List[str]]:
    inp = db.get_input(input_id=user.curr_sent_id)
    translation = db.create_translation(
        user_id=user.user_id,
        trans_input=inp,
        text=user_text,
    )
    db.save_translation(translation)
    # do NOT reset current sent id, because it will be used to determine the next input!
    user.curr_result_id = None
    user.curr_label_id = None

    # Ask for a new translation in the same task
    task = db.get_task(task_id=translation.task_id)
    return do_assign_input(user=user, db=db, task=task)


def do_ask_setup(user: UserState) -> Tuple[str, List[str]]:
    suggests = []
    if not user.src_langs:
        user.state_id = States.SETUP_ASK_SRC_LANG
        response = texts.SETUP_ASK_SRC_LANG
    elif not user.tgt_langs:
        user.state_id = States.SETUP_ASK_TGT_LANG
        response = texts.SETUP_ASK_TGT_LANG
    elif not user.contact:
        user.state_id = States.SETUP_ASK_CONTACT_INFO
        response = texts.SETUP_ASK_CONTACT_INFO
    else:
        user.state_id = None
        response = texts.SETUP_READY
    return response, suggests
