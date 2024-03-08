import os

import pandas as pd

import models

MONGO_URL = os.environ.get("MONGODB_URI")
DB = models.Database.setup(MONGO_URL)


def export_results(
    fn="data/export/nllb-seed-eng-rus-export.tsv",
    project_id=1,
):
    # TODO: aggregate the results in a smarter way
    sources_df = pd.DataFrame(DB.trans_inputs.find({"project_id": project_id})).set_index("input_id")
    results_df = pd.DataFrame(DB.trans_results.find({"project_id": project_id}))
    results_df["source_text"] = results_df.input_id.apply(lambda x: sources_df.loc[x]["source"])
    results_df.to_csv(fn, sep="\t", index=False)
    print(f"Exported {results_df.shape[0]} results to {fn}!")


if __name__ == "__main__":
    export_results()
