import os
import random
from typing import List, Optional, Tuple

import texts
from language_coding import LangCodeForm, get_lang_name
from models import (
    Database,
    TransInput,
    TransLabel,
    TransResult,
    TransStatus,
    TransTask,
    UserState,
)
from states import States

N_IMPRESSIONS_FOR_INSTRUCTIONS = 3
P_RANDOM_INSTRUCTION = 0.05


def do_assign_input(
    user: UserState, db: Database, task: TransTask
) -> Tuple[str, List[str]]:
    # we do a loop, because we may need to skip some inputs
    assert user.user_id is not None
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
        if inp.input_id != user.curr_sent_id:
            user.pbar_num = (user.pbar_num or 0) + 1

        # depending on the task, either choose the candidates to score or ask for a new translation
        (
            all_translations,
            unchecked_translations_unseen_by_user,
            all_unchecked_translations,
        ) = find_translations_to_score(user=user, db=db, inp=inp)
        print(
            f"for input {inp.input_id} found {len(all_translations)} translations: including {len(all_unchecked_translations)} unchecked, and {len(unchecked_translations_unseen_by_user)} unseen by user."
        )

        # Case 1: there are pending translations by other users, which the current user hasn't scored => asking to score
        if len(unchecked_translations_unseen_by_user) > 0:
            candidate = unchecked_translations_unseen_by_user[0]
            print(f"scoring the candidate translation {candidate}")
            label = db.create_label(user_id=user.user_id, trans_result=candidate)
            return do_ask_xsts(user=user, db=db, inp=inp, res=candidate, label=label)

        # Case 2: no translations to score, but there are some pending translatons => skip the input, until the pending translations are scored
        elif len(all_unchecked_translations):
            prev_sent_id = inp.input_id
            print(
                f"continuing to another input, because there are {len(all_unchecked_translations)} unscored translations for the input {inp.input_id}"
            )
            continue

        # Case 3: no translations to score, no pending translations by the user => asking for a new translation
        else:
            print(
                f"asking to translate, because for user {user.user_id} and input {inp.input_id}, there are no unscored translations"
            )
            return do_ask_to_translate(user=user, db=db, inp=inp)
    return (
        f"Произошло что-то странное. Пожалуйста, напишите @cointegrated, что по заданию {task.task_id} вам не смогли выдать текст.",
        [],
    )


def find_translations_to_score(
    user: UserState, db: Database, inp: TransInput
) -> Tuple[List[TransResult], List[TransResult], List[TransResult]]:
    all_translations = db.get_translations_for_input(inp)
    # filter out the translations by the user and the translations that user has already scored
    assert user.user_id is not None
    already_scored_candidates = db.get_translations_ids_scored_by_user(
        user_id=user.user_id, task_id=inp.task_id
    )
    all_unchecked_translations = [
        cand for cand in all_translations if cand.status == TransStatus.UNCHECKED
    ]

    other_candidates = [
        candidate
        for candidate in all_translations
        if candidate.user_id != user.user_id
        and candidate.translation_id not in already_scored_candidates
    ]
    unchecked_translations_unseen_by_user = [
        candidate
        for candidate in other_candidates
        if candidate.status == TransStatus.UNCHECKED
    ]
    return (
        all_translations,
        unchecked_translations_unseen_by_user,
        all_unchecked_translations,
    )


def do_not_assing_new_task(
    user: UserState,
    db: Database,
) -> Tuple[str, List[str]]:
    response = texts.DO_NOT_ASSIGN_TASK + "\n\n" + texts.MENU
    suggests: List[str] = []
    return response, suggests


def pbar_text(user: UserState) -> str:
    return f"({user.pbar_num}/{user.pbar_den})"


def do_ask_to_translate(
    user: UserState,
    db: Database,
    inp: TransInput,
) -> Tuple[str, List[str]]:
    src_text = inp.source

    proj = db.get_project(project_id=inp.project_id)
    assert proj is not None and proj.src_code is not None and proj.tgt_code is not None
    src_lang_phrase = get_lang_name(proj.src_code, code_form_id=LangCodeForm.src)
    tgt_lang_phrase = get_lang_name(proj.tgt_code, code_form_id=LangCodeForm.tgt)
    response = f"{pbar_text(user)}\nВот исходный текст: <code>{src_text}</code>\n\nПожалуйста, предложите его перевод {src_lang_phrase} {tgt_lang_phrase}:"
    if (
        user.n_translations < N_IMPRESSIONS_FOR_INSTRUCTIONS
        or random.random() < P_RANDOM_INSTRUCTION
        or os.environ.get("FORCE_HINT_TRANSLATION")
    ):
        response = f"{response}\n\n{texts.TRANSLATION_GUIDELINE}"

    user.state_id = States.ASK_TRANSLATION
    user.curr_proj_id = inp.project_id
    user.curr_task_id = inp.task_id
    user.curr_sent_id = inp.input_id
    user.curr_result_id = None
    user.curr_label_id = None
    return response, [texts.COMMAND_SKIP]


def do_ask_coherence(
    user: UserState,
    db: Database,
    inp: TransInput,
    res: TransResult,
    label: TransLabel,
    show_help: Optional[bool] = None,
) -> Tuple[str, List[str]]:
    user.state_id = States.ASK_COHERENCE
    response = f"{pbar_text(user)}\nВот исходный текст: <code>{inp.source}</code>\n\nВот перевод: <code>{res.translation}</code>\n\n{texts.COHERENCE_PROMPT}"
    if (
        user.n_labels < N_IMPRESSIONS_FOR_INSTRUCTIONS
        or random.random() < P_RANDOM_INSTRUCTION
        or show_help
        or os.environ.get("FORCE_HINT_COHERENCE")
    ):
        response = f"{response}\n\n{texts.COHERENCE_GUIDELINE}"
    suggests = texts.COHERENCE_RESPONSES + [texts.COMMAND_SKIP]

    db.save_label(label)
    user.curr_proj_id = inp.project_id
    user.curr_task_id = inp.task_id
    user.curr_sent_id = inp.input_id
    user.curr_result_id = res.translation_id
    user.curr_label_id = label.label_id
    return response, suggests


def do_ask_xsts(
    user: UserState,
    db: Database,
    inp: TransInput,
    res: TransResult,
    label: TransLabel,
    show_help: Optional[bool] = None,
) -> Tuple[str, List[str]]:
    user.state_id = States.ASK_XSTS
    response = f"{pbar_text(user)}\nВот исходный текст: <code>{inp.source}</code>\n\nВот перевод: <code>{res.translation}</code>\n\n{texts.XSTS_PROMPT}"
    if (
        user.n_labels < N_IMPRESSIONS_FOR_INSTRUCTIONS
        or random.random() < P_RANDOM_INSTRUCTION
        or show_help
        or os.environ.get("FORCE_HINT_XSTS")
    ):
        response = f"{response}\n\n{texts.XSTS_GUIDELINE}"
    suggests = texts.XSTS_RESPONSES + [texts.COMMAND_SKIP]

    db.save_label(label)
    user.curr_proj_id = inp.project_id
    user.curr_task_id = inp.task_id
    user.curr_sent_id = inp.input_id
    user.curr_result_id = res.translation_id
    user.curr_label_id = label.label_id
    return response, suggests


def do_save_coherence_and_continue(
    user: UserState, db: Database, user_text: str
) -> Tuple[str, List[str]]:
    assert user.curr_label_id is not None
    label = db.get_label(label_id=user.curr_label_id)
    assert label is not None
    label.coherence_score = texts.COHERENCE_RESPONSES_MAP.get(user_text)
    db.save_label(label)
    return do_finalize_label_and_continue(user=user, db=db, label=label)


def do_save_xsts_and_continue(
    user: UserState, db: Database, user_text: str
) -> Tuple[str, List[str]]:
    score_value = int(user_text)
    assert user.curr_label_id is not None
    label = db.get_label(label_id=user.curr_label_id)
    assert label is not None
    label.semantics_score = score_value
    db.save_label(label)
    return do_finalize_label_and_continue(user=user, db=db, label=label)


def do_finalize_label_and_continue(
    user: UserState, db: Database, label: TransLabel
) -> Tuple[str, List[str]]:
    assert (
        user.curr_proj_id is not None
        and user.curr_task_id is not None
        and user.curr_sent_id is not None
        and user.curr_result_id is not None
    )
    project = db.get_project(project_id=user.curr_proj_id)
    task = db.get_task(task_id=user.curr_task_id)
    inp = db.get_input(input_id=user.curr_sent_id)
    res = db.get_translation(result_id=user.curr_result_id)
    if project is None or task is None or inp is None or res is None:
        return texts.FALLBACK, []

    label_is_good = label.is_positive(semantic_threshold=project.min_score)

    # Case 0: need one more label to get the verdict!
    if label_is_good is None:
        if label.semantics_score is None:
            return do_ask_xsts(user=user, db=db, inp=inp, res=res, label=label)
        elif label.coherence_score is None:
            return do_ask_coherence(user=user, db=db, inp=inp, res=res, label=label)
        else:  # this is not possible!
            return texts.FALLBACK, []

    user.n_labels += 1

    # Case 1: acceptance
    if label_is_good is True:
        accepted = True
        res.n_approvals += 1
        if res.n_approvals >= project.overlap and res.status != TransStatus.REJECTED:
            res.status = TransStatus.ACCEPTED

    # Case 2: rejection
    elif label_is_good is False:
        accepted = False
        res.status = TransStatus.REJECTED
    else:  # this is not possible!
        return texts.FALLBACK, []

    db.save_translation(res)

    # if the translation is accepted, the translation input is solved
    if res.status == TransStatus.ACCEPTED:
        inp.solved = True
        db.save_input(inp)

    # if the user has accepted a translation, no reason in asking for a new one; jumping to the next input
    if accepted:
        return do_assign_input(user=user, db=db, task=task)

    # if translation is rejected, but there is another candidate, assign it!
    (
        all_translations,
        unchecked_translations_unseen_by_user,
        all_unchecked_translations,
    ) = find_translations_to_score(user=user, db=db, inp=inp)
    assert user.user_id is not None
    if len(unchecked_translations_unseen_by_user) > 0:
        candidate = unchecked_translations_unseen_by_user[0]
        print(f"scoring the candidate translation {candidate}")
        label = db.create_label(user_id=user.user_id, trans_result=candidate)
        return do_ask_xsts(user=user, db=db, inp=inp, res=candidate, label=label)

    # if the user has unscored translations for this input, we won't ask them for new ones
    assert user.user_id is not None
    if db.user_has_unscored_translations_for_input(
        user_id=user.user_id, input_id=inp.input_id
    ):
        return do_assign_input(user=user, db=db, task=task)

    # ask for a new translation
    return do_ask_to_translate(user=user, db=db, inp=inp)


def do_save_translation_and_ask_for_next(
    user: UserState, db: Database, user_text: str
) -> Tuple[str, List[str]]:
    assert user.curr_sent_id is not None
    inp = db.get_input(input_id=user.curr_sent_id)
    assert inp is not None
    assert user.user_id is not None
    translation = db.create_translation(
        user_id=user.user_id,
        trans_input=inp,
        text=user_text,
    )
    # if a translation text is a duplicate, assign it a special status
    other_translations = db.get_translations_for_input(inp=inp)
    for other in other_translations:
        if (
            other.translation == translation.translation
            and other.translation_id != translation.translation_id
        ):
            translation.status = TransStatus.DUPLICATE
            # TODO (future) maybe, tell the user that the translation is a duplicate and ask for a different one!

    db.save_translation(translation)

    # do NOT reset current sent id, because it will be used to determine the next input!
    user.curr_result_id = None
    user.curr_label_id = None
    user.n_translations += 1

    # Ask for a new translation in the same task
    task = db.get_task(task_id=translation.task_id)
    assert task is not None
    return do_assign_input(user=user, db=db, task=task)


def do_ask_setup(user: UserState) -> Tuple[str, List[str]]:
    suggests: List[str] = []
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
    lines = [
        f"Текущая статистика по проекту #{project_id}:",
        "<pre>",
        f"  всего предложений:    {stats_dict.get('n_inputs')}",
        f"  частично одобрено:    {stats_dict.get('n_partial')}",
        f"  полностью одобрено:   {stats_dict.get('n_solved')}",
        f"  предложено переводов: {stats_dict.get('n_user_translations')}",
        f"  оценено переводов:    {stats_dict.get('n_labels')}",
        f"  положительных оценок: {stats_dict.get('n_positive_labels')}",
        f"  отрицательных оценок: {stats_dict.get('n_negative_labels')}",
        "</pre>",
    ]
    return "\n".join(lines), []


def do_tell_guidelines(user: UserState, db: Database) -> Tuple[str, List[str]]:
    suggests: List[str] = []
    response = "\n\n".join(
        [
            texts.GUIDELINES_HEADER,
            texts.COHERENCE_GUIDELINE,
            texts.XSTS_GUIDELINE,
            texts.TRANSLATION_GUIDELINE,
        ]
    )
    return response, suggests


def do_resume_task(user: UserState, db: Database) -> Tuple[str, List[str]]:
    # repeat the last message in the current task, without changing the state
    suggests: List[str] = []

    task = db.get_task(user.curr_task_id) if user.curr_task_id is not None else None
    inp = db.get_input(user.curr_sent_id) if user.curr_sent_id is not None else None
    res = (
        db.get_translation(user.curr_result_id)
        if user.curr_result_id is not None
        else None
    )
    label = db.get_label(user.curr_label_id) if user.curr_label_id is not None else None

    if user.state_id == States.ASK_COHERENCE and inp and res and label:
        response, suggests = do_ask_coherence(
            user=user,
            db=db,
            inp=inp,
            res=res,
            label=label,
        )
    elif user.state_id == States.ASK_XSTS and inp and res and label:
        response, suggests = do_ask_xsts(
            user=user,
            db=db,
            inp=inp,
            res=res,
            label=label,
        )
    elif user.state_id == States.ASK_TRANSLATION and inp:
        response, suggests = do_ask_to_translate(
            user=user,
            db=db,
            inp=inp,
        )
    elif task:
        response, suggests = do_assign_input(
            user=user,
            db=db,
            task=task,
        )
    else:
        response = texts.NO_CURRENT_TASK + "\n" + texts.NAVIGATION
    return response, suggests


def do_skip_input(user: UserState, db: Database) -> Tuple[str, List[str]]:
    """Skip the current translation input and go to the next one"""
    suggests: List[str] = []
    task = db.get_task(user.curr_task_id) if user.curr_task_id is not None else None
    if task is None or user.curr_sent_id is None:
        return texts.RESP_NOTHING_TO_SKIP, suggests

    return do_assign_input(user=user, db=db, task=task)
