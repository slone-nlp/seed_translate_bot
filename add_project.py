import os

import pandas as pd
from tqdm.auto import tqdm

import models

MONGO_URL = os.environ.get("MONGODB_URI")

DB = models.Database.setup(MONGO_URL)

PROMPT_TEMPLATE = """"Чтобы приступить к переводу, рекомендуется прочитать статью в Википедии, 
откуда были взяты предложения, чтобы лучше понять контекст: {}."""

EMPTY_TEXTS = {"-"}


def add_project(fn="data/NLLB-seed-translation - nllb-seed-eng-rus.tsv"):
    df = pd.read_csv(fn, sep="\t")
    print(df.isnull().mean())

    project = DB.create_project(title="NLLB-Seed-eng-rus")

    n_inputs, n_tasks = 0, 0
    groups = list(df.groupby("URL"))
    for url, task_df in tqdm(groups):
        task = DB.create_task(
            project=project,
            prompt=PROMPT_TEMPLATE.format(url),
        )
        n_tasks += 1
        task_inputs = []
        for i, row in task_df.iterrows():
            src_text, tgt_text = row["eng_Latn"], row["Wiki text"]
            if not tgt_text or tgt_text in EMPTY_TEXTS:
                tgt_text = None
            inp = DB.create_input(
                project=project,
                task=task,
                source=src_text,
                candidate=tgt_text,
                save=False,
            )
            task_inputs.append(inp)
            n_inputs += 1
        DB.add_inputs(task_inputs)

    print(f"Created {n_tasks} tasks witn {n_inputs} inputs!")


if __name__ == "__main__":
    add_project()
