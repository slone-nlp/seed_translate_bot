import os

import pandas as pd
from tqdm.auto import tqdm  # type: ignore

import models

MONGO_URL = os.environ.get("MONGODB_URI")

DB = models.Database.setup(MONGO_URL)

PROMPT_TEMPLATE = (
    "Чтобы приступить к переводу, рекомендуется прочитать статью в Википедии, "
    "откуда были взяты предложения, чтобы лучше понять контекст: {}."
    "\nЕсли у статьи есть русская версия, прочитайте её тоже, чтобы понять общепринятый перевод основных сущностей и понятий."
)

EMPTY_TEXTS = {"-"}


def add_project(
    fn="data/nllb-seed-eng-rus-scored-v1.tsv",
    project_name="NLLB-Seed-eng-rus",
    min_initial_translation_score=3.0,
    src_lang_code="eng",
    tgt_lang_code="rus",
    min_overlap=2,
    min_score=4,
    limit=None,
):
    df = pd.read_csv(fn, sep="\t")
    print(df.isnull().mean())

    project = DB.create_project(title=project_name)
    project.src_code = src_lang_code
    project.tgt_code = tgt_lang_code
    project.overlap = min_overlap
    project.min_score = min_score
    DB.save_project(project)

    n_inputs, n_tasks, n_cands = 0, 0, 0
    groups = list(df.groupby("URL"))
    for url, task_df in tqdm(groups):
        if limit is not None and n_tasks >= limit:
            break
        task = DB.create_task(
            project=project,
            prompt=PROMPT_TEMPLATE.format(url),
        )
        n_tasks += 1
        task_inputs = []
        cand_texts = []
        for i, row in task_df.iterrows():
            src_text, tgt_text, tgt_score = (
                row["eng_Latn"],
                row["candidate"],
                row["candidate_score"],
            )
            if not tgt_text or tgt_text in EMPTY_TEXTS:
                tgt_text = None
            if tgt_score is None or tgt_score < min_initial_translation_score:
                tgt_text = None
            inp = DB.create_input(
                project=project,
                task=task,
                source=src_text,
                save=False,
            )
            task_inputs.append(inp)
            cand_texts.append(tgt_text)
            n_inputs += 1
            n_cands += bool(tgt_text)
            if limit is not None and len(task_inputs) >= limit:
                break
        DB.add_inputs(task_inputs)
        candidates = [
            DB.create_translation(
                user_id=models.NO_USER, trans_input=inp, text=tgt_text
            )
            for tgt_text, inp in zip(cand_texts, task_inputs)
            if tgt_text
        ]
        if len(candidates) > 0:
            DB.add_translations(candidates)

    print(
        f"Created {n_tasks} tasks with {n_inputs} inputs and {n_cands} candidate translations!"
    )


if __name__ == "__main__":
    add_project()
