import random
from typing import List, Optional, Tuple

import texts
from language_coding import get_lang_name, LangCodeForm
from models import Database, TransInput, TransResult, TransTask, UserState, TransLabel, TransStatus
from states import States


N_IMPRESSIONS_FOR_INSTRUCTIONS = 3
P_RANDOM_INSTRUCTION = 0.05


def do_assign_input(
    user: UserState, db: Database, task: TransTask
) -> Tuple[str, List[str]]:
    # we do a loop, because we may need to skip some inputs
    prev_sent_id = user.curr_sent_id
    for attempt in range(100):

        inp: Optional[TransInput] = db.get_next_unsolved_input(
            task=task,
            prev_sent_id=prev_sent_id,
        )
        print("attempt", attempt, "trying input:", inp)
        # No input means that the task is completed by the user
        if inp is None:
            # check the conditions whether the task is fully completed, and update ts status
            task.locked = False
            task.completions += 1
            unsolved_input = db.get_next_unsolved_input(task=task, prev_sent_id=None)
            if unsolved_input is None:
                task.completed = True
            db.save_task(task)
            db.add_user_task_link(user_id=user.user_id, task=task)

            user.curr_sent_id = None
            user.curr_task_id = None
            user.state_id = States.SUGGEST_ONE_MORE_TASK
            return "В данном задании закончились примеры. Хотите взять ещё одно?", [
                texts.RESP_YES,
                texts.RESP_NO,
            ]

        # depending on the task, either choose the candidates to score or ask for a new translation
        candidates = db.get_translations_for_input(inp)
        # filter out the translations by the user and the translations that user has already scored
        already_scored_candidates = db.get_translations_ids_scored_by_user(user_id=user.user_id, task_id=task.task_id)
        pending_candidates = [cand for cand in candidates if cand.status == TransStatus.UNCHECKED]

        other_candidates = [candidate for candidate in candidates if candidate.user_id != user.user_id and candidate.translation_id not in already_scored_candidates]
        other_pending = [candidate for candidate in other_candidates if candidate.status == TransStatus.UNCHECKED]
        print(f"for input {inp.input_id} found {len(candidates)} translations: {len(already_scored_candidates)} scored by the user, and {len(other_candidates)} other candidates, including {len(other_pending)} unchecked.")

        # Case 1: there are pending translations by other users, which the current user hasn't scored => asking to score
        if len(other_pending) > 0:
            candidate = other_pending[0]
            print(f"scoring the candidate translation {candidate}")
            label = db.create_label(user_id=user.user_id, trans_result=candidate)
            return do_ask_coherence(user=user, db=db, inp=inp, res=candidate, label=label)

        # Case 2: no translations to score, but there are some pending translatons => skip the input, until the pending translations are scored
        elif len(pending_candidates):
            prev_sent_id = inp.input_id
            print(f"continuing to another input, because there are {len(pending_candidates)} unscored translations for the input {inp.input_id}")
            continue

        # Case 3: no translations to score, no pending translations by the user => asking for a new translation
        else:
            print(f"asking to translate, because for user {user.user_id} and input {inp.input_id}, there are no unscored translations")
            return do_ask_to_translate(user=user, db=db, inp=inp)
    return f"Произошло что-то странное. Пожалуйста, напишите @cointegrated, что по заданию {task.task_id} вам не смогли выдать текст.", []


def do_ask_to_translate(
    user: UserState, db: Database, inp: TransInput,
) -> Tuple[str, List[str]]:
    src_text = inp.source

    proj = db.get_project(project_id=inp.project_id)
    src_lang_phrase = get_lang_name(proj.src_code, code_form_id=LangCodeForm.src)
    tgt_lang_phrase = get_lang_name(proj.tgt_code, code_form_id=LangCodeForm.tgt)
    response = (
        f"Вот исходный текст: <b>{src_text}</b>\n\nПожалуйста, предложите его перевод {src_lang_phrase} {tgt_lang_phrase}:"
    )
    if user.n_translations < N_IMPRESSIONS_FOR_INSTRUCTIONS or random.random() < P_RANDOM_INSTRUCTION:
        response = f"{response}\n\n{texts.TRANSLATION_GUIDELINE}"

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
    response = f"Вот исходный текст: <b>{inp.source}</b>\n\nВот перевод: <b>{res.translation}</b>\n\n{texts.COHERENCE_PROMPT}"
    if user.n_labels < N_IMPRESSIONS_FOR_INSTRUCTIONS or random.random() < P_RANDOM_INSTRUCTION:
        response = f"{response}\n\n{texts.COHERENCE_GUIDELINE}"
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
    response = f"Вот исходный текст: <b>{inp.source}</b>\n\nВот перевод: <b>{res.translation}</b>\n\n{texts.XSTS_PROMPT}"
    if user.n_labels < N_IMPRESSIONS_FOR_INSTRUCTIONS or random.random() < P_RANDOM_INSTRUCTION:
        response = f"{response}\n\n{texts.XSTS_GUIDELINE}"
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

    user.n_labels += 1

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
    # if a translation text is a duplicate, assign it a special status
    other_translations = db.get_translations_for_input(inp=inp)
    for other in other_translations:
        if other.translation == translation.translation and other.translation_id != translation.translation_id:
            translation.status = TransStatus.DUPLICATE
            # TODO (future) maybe, tell the user that the translation is a duplicate and ask for a different one!

    db.save_translation(translation)

    # do NOT reset current sent id, because it will be used to determine the next input!
    user.curr_result_id = None
    user.curr_label_id = None
    user.n_translations += 1

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


def do_get_project_status(user: UserState, db: Database) -> Tuple[str, List[str]]:
    project_id = user.curr_proj_id
    if project_id is None:
        project_id = 1  # TODO (future): propose to choose a project
    stats_dict = db.get_project_stats(project_id=project_id)
    return f"Текущая статистика по проекту #{project_id}: {stats_dict}", []


def do_tell_guidelines(user: UserState, db: Database) -> Tuple[str, List[str]]:
    suggests = []
    response = "\n\n".join([
        texts.GUIDEINES_HEADER,
        texts.COHERENCE_GUIDELINE,
        texts.XSTS_GUIDELINE,
        texts.TRANSLATION_GUIDELINE,
    ])
    return response, suggests


def do_resume_task(user: UserState, db: Database) -> Tuple[str, List[str]]:
    # repeat the last message in the current task, without changing the state
    suggests = []

    task = db.get_task(user.curr_task_id)
    inp = db.get_input(user.curr_sent_id)
    res = db.get_translation(user.curr_result_id)
    label = db.get_label(user.curr_label_id)

    if user.state_id == States.ASK_COHERENCE and inp and res and label:
        response, suggests = do_ask_coherence(
            user=user, db=db, inp=inp, res=res, label=label,
        )
    elif user.state_id == States.ASK_XSTS and inp and res and label:
        response, suggests = do_ask_xsts(
            user=user, db=db, inp=inp, res=res, label=label,
        )
    elif user.state_id == States.ASK_TRANSLATION and inp:
        response, suggests = do_ask_to_translate(
            user=user, db=db, inp=inp,
        )
    elif task:
        response, suggests = do_assign_input(
            user=user, db=db, task=task,
        )
    else:
        response = texts.NO_CURRENT_TASK + "\n" + texts.NAVIGATION
    return response, suggests
