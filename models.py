import logging
import random
import time
from typing import Dict, List, Optional, Set

import mongomock
import telebot
from pydantic import BaseModel
from pymongo import MongoClient
from pymongo.collection import Collection

logger = logging.getLogger(__name__)

NO_ID = -1
NO_USER = -1
COHERENT = 1
INCOHERENT = 0


class UserState(BaseModel):
    # Telegram information
    user_id: Optional[int] = None
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None

    # User information
    src_langs: Optional[List[str]] = None
    tgt_langs: Optional[List[str]] = None
    contact: Optional[str] = None

    # Current task information
    curr_proj_id: Optional[int] = None
    curr_task_id: Optional[int] = None
    curr_sent_id: Optional[int] = None
    curr_result_id: Optional[int] = None
    curr_label_id: Optional[int] = None

    # Dialogue state
    state_id: Optional[str] = None


def update_user_state(users_collection: Collection, state: UserState):
    dumped = state.model_dump()
    print("dumped: ", type(dumped), dumped)
    users_collection.update_one(
        filter={"user_id": state.user_id}, update={"$set": dumped}, upsert=True
    )


def find_user(users_collection: Collection, user: telebot.types.User) -> UserState:
    user_id = user.id
    obj = users_collection.find_one({"user_id": user_id})
    if obj is None:
        print("creating a new user!")
        state = UserState(
            user_id=user_id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
        )
        update_user_state(users_collection, state)
    else:
        print("loading a user!")
        state = UserState.model_construct(**obj)
    return state


class TransProject(BaseModel):
    project_id: int
    title: str
    description: Optional[str] = None
    src_code: Optional[str] = None
    tgt_code: Optional[str] = None
    # how many approvals we want per translation
    overlap: int = 2
    # what is the minimal semantic score (XSTS) considered as approval
    min_score: int = 4


class TransTask(BaseModel):
    task_id: int
    project_id: int
    completions: int = 0
    prompt: Optional[str] = None
    locked: bool = False
    completed: bool = False
    meta: Optional[Dict] = None


class TransInput(BaseModel):
    project_id: int
    task_id: int
    input_id: int
    source: str
    meta: Optional[Dict] = None
    # the input is considered solved if it has an accepted translation result
    solved: bool = False


class TransStatus:
    UNCHECKED = 0
    ACCEPTED = 1
    REJECTED = 2


class TransResult(BaseModel):
    project_id: int
    task_id: int
    input_id: int
    translation_id: int
    user_id: int
    submitted_date: int
    translation: Optional[str] = None
    # approvals are translation labels where both coherence and semantic scores are positive
    n_approvals: int = 0
    # A translation is rejected if it has a negative label.
    # It is approved if it has reached the minimal number of approvals.
    status: int = TransStatus.UNCHECKED


class TransLabel(BaseModel):
    project_id: int
    task_id: int
    input_id: int
    translation_id: int
    label_id: int
    user_id: int
    submitted_date: int
    coherence_score: Optional[int] = None
    semantics_score: Optional[int] = None

    @property
    def is_coherent(self) -> bool:
        return self.coherence_score == COHERENT


class Database:
    def __init__(self, mongo_db):
        # UserState
        self.mongo_users: Collection = mongo_db.get_collection("users")

        # user_id, from_user, text, timestamp, message_id
        self.mongo_messages: Collection = mongo_db.get_collection("messages")

        # translation-related stuff
        self.trans_projects: Collection = mongo_db.get_collection("trans_projects")
        self.trans_tasks: Collection = mongo_db.get_collection("trans_tasks")
        self.trans_inputs: Collection = mongo_db.get_collection("trans_inputs")
        self.trans_results: Collection = mongo_db.get_collection("trans_results")
        self.trans_labels: Collection = mongo_db.get_collection("trans_labels")
        self.user_task_map: Collection = mongo_db.get_collection("user_task_map")

    @classmethod
    def setup(cls, mongo_url: str) -> "Database":
        if mongo_url is not None:
            mongo_client = MongoClient(mongo_url)
            mongo_db = mongo_client.get_default_database()
        else:
            mongo_client = mongomock.MongoClient()
            mongo_db = mongo_client.db
        return Database(mongo_db=mongo_db)

    def save_user(self, user: UserState):
        update_user_state(users_collection=self.mongo_users, state=user)

    def get_new_task(self, user: UserState) -> Optional[TransTask]:
        # TODO(future): in the future, filter by the current project and its languages
        unfinished_task_ids = {
            (task["task_id"], task["completions"])
            for task in self.trans_tasks.find({"completed": False, "locked": False})
        }
        if len(unfinished_task_ids) == 0:
            # TODO(nice): check if there are any tasks that are locked by mistake, and reconsider
            logger.info(f"Did not find any unfinished tasks!")
            return

        # prioritize the tasks that the user has not contributed yet
        user_tasks = {
            obj["task_id"]
            for obj in self.user_task_map.find({"user_id": user.user_id})
        }
        tasks_untouched_by_user = {
            (task_id, completion)
            for task_id, completion in unfinished_task_ids
            if task_id not in user_tasks
        }

        if len(tasks_untouched_by_user) > 0:
            unfinished_task_ids = tasks_untouched_by_user
        else:
            # If all the tasks are touched by the user, apply some more filtering.
            # In principle, we should only keep the tasks where there are unsolved inputs with:
            # - either pending translations that were neither produced nor labeled by the user
            # - or without pending (or accepted) translations at all
            unsolved_inputs = [TransInput.model_construct(obj) for obj in self.trans_inputs.find({"solved": False})]
            pending_translations = [TransResult.model_construct(obj) for obj in self.trans_results.find({"status": TransStatus.UNCHECKED})]
            user_labels = [TransLabel.model_construct(obj) for obj in self.trans_labels.find({"user_id": user.user_id})]

            translation_ids_labeled_by_user = {lab.translation_id for lab in user_labels}
            input_ids_to_label = {
                t.input_id
                for t in pending_translations
                if t.user_id != user.user_id and t.translation_id not in translation_ids_labeled_by_user
            }
            input_ids_with_pending_translations = {t.input_id for t in pending_translations}
            good_task_ids = {
                inp.task_id
                for inp in unsolved_inputs
                if inp.input_id in input_ids_to_label or inp.input_id not in input_ids_with_pending_translations
            }
            unfinished_task_ids = {
                (task_id, completion)
                for task_id, completion in unfinished_task_ids
                if task_id in good_task_ids
            }

        if len(unfinished_task_ids) == 0:
            logger.info(f"Did not find any unfinished tasks!")
            return

        # prioritize the tasks with the lowest number of completions
        min_completion = min(
            [completion for task_id, completion in unfinished_task_ids]
        )
        least_completed_ids = [
            task_id
            for task_id, completion in unfinished_task_ids
            if completion == min_completion
        ]

        task_id = random.choice(least_completed_ids)
        logger.info(
            f"Chose the task {task_id} among {len(unfinished_task_ids)} options."
        )
        return self.get_task(task_id)

    def add_user_task_link(self, user_id: int, task: TransTask):
        obj = {"user_id": user_id, "task_id": task.task_id, "project_id": task.project_id}
        self.user_task_map.update_one(obj, {"$set": obj}, upsert=True)

    def get_project(self, project_id: int) -> Optional[TransProject]:
        obj = self.trans_projects.find_one({"project_id": project_id})
        if obj:
            proj = TransProject.model_construct(**obj)
            return proj

    def get_task(self, task_id: int) -> Optional[TransTask]:
        obj = self.trans_tasks.find_one({"task_id": task_id})
        if obj:
            task = TransTask.model_construct(**obj)
            return task

    def get_next_unsolved_input(
        self, task: TransTask, prev_sent_id: Optional[int] = None,
    ) -> Optional[TransInput]:
        """
        For the given task, get the next input.
        """
        # then we should skip this input
        if prev_sent_id is None:
            prev_sent_id = -1
        all_inputs = [
            TransInput.model_construct(**obj)
            for obj in self.trans_inputs.find({"task_id": task.task_id, "solved": False})
        ]
        prev_inputs = sorted(
            [inp for inp in all_inputs if inp.input_id > prev_sent_id],
            key=lambda x: x.input_id,
        )
        if prev_inputs:
            return prev_inputs[0]

    def user_has_unscored_translations_for_input(self, user_id: int, input_id: int) -> bool:
        found = self.trans_results.find_one({"user_id": user_id, "input_id": input_id, "status": TransStatus.UNCHECKED})
        if found:
            return True
        return False

    def create_project(self, title: str, save: bool = True):
        project_ids = {p["project_id"] for p in self.trans_projects.find({})}
        project_id = max(project_ids, default=0) + 1
        project = TransProject(
            project_id=project_id,
            title=title,
        )
        if save:
            self.save_project(project)
        return project

    def save_project(self, project: TransProject) -> None:
        self.trans_projects.update_one(
            filter={"project_id": project.project_id},
            update={"$set": project.model_dump()},
            upsert=True,
        )

    def create_task(
        self, project: TransProject, prompt: Optional[str] = None, save: bool = True
    ):
        ids = {t["task_id"] for t in self.trans_tasks.find({})}
        task_id = max(ids, default=0) + 1
        task = TransTask(
            project_id=project.project_id,
            task_id=task_id,
            prompt=prompt,
        )
        if save:
            self.save_task(task)
        return task

    def save_task(self, task: TransTask) -> None:
        self.trans_tasks.update_one(
            filter={"task_id": task.task_id},
            update={"$set": task.model_dump()},
            upsert=True,
        )

    def get_input(self, input_id: int) -> Optional[TransInput]:
        obj = self.trans_inputs.find_one({"input_id": input_id})
        if obj:
            inp = TransInput.model_construct(**obj)
            return inp

    def create_input(
        self,
        project: TransProject,
        task: TransTask,
        source: str,
        save: bool = False,
    ):
        inp = TransInput(
            project_id=project.project_id,
            task_id=task.task_id,
            input_id=NO_ID,
            source=source,
        )
        if save:
            self.save_input(inp)
        return inp

    def save_input(self, inp: TransInput) -> None:
        if inp.input_id == NO_ID:
            ids = {inp["input_id"] for inp in self.trans_inputs.find({})}
            inp.input_id = max(ids, default=0) + 1
            self.trans_inputs.insert_one(inp.model_dump())
        else:
            self.trans_inputs.update_one(
                filter={"input_id": inp.input_id},
                update={"$set": inp.model_dump()},
                upsert=True,
            )

    def add_inputs(self, inps: List[TransInput]) -> None:
        ids = {inp["input_id"] for inp in self.trans_inputs.find({})}
        max_id = max(ids, default=0) + 1
        for i, inp in enumerate(inps):
            inp.input_id = max_id + i
        self.trans_inputs.insert_many([inp.model_dump() for inp in inps])

    def get_translation(self, result_id: int) -> Optional[TransResult]:
        obj = self.trans_results.find_one({"translation_id": result_id})
        if obj:
            res = TransResult.model_construct(**obj)
            return res

    def get_translations_for_input(self, inp: TransInput, status: Optional[int] = None) -> List[TransResult]:
        fltr = {
            "input_id": inp.input_id,
            "task_id": inp.task_id,
            "project_id": inp.project_id,
        }
        if status is not None:
            fltr["status"] = status
        results = [
            TransResult.model_construct(**obj)
            for obj in self.trans_results.find(fltr)
        ]
        return results

    def create_translation(self, user_id: int, trans_input: TransInput, text: Optional[str] = None) -> TransResult:
        result = TransResult(
            project_id=trans_input.project_id,
            task_id=trans_input.task_id,
            input_id=trans_input.input_id,
            translation_id=NO_ID,
            user_id=user_id,
            submitted_date=int(time.time()),
            translation=text,
        )
        return result

    def save_translation(self, result: TransResult) -> None:
        if result.translation_id == NO_ID:
            ids = {t["translation_id"] for t in self.trans_results.find({})}
            result.translation_id = max(ids, default=0) + 1
            self.trans_results.insert_one(result.model_dump())
        else:
            self.trans_results.update_one(
                filter={"translation_id": result.translation_id},
                update={"$set": result.model_dump()},
                upsert=True,
            )

    def add_translations(self, translations: List[TransResult]) -> None:
        ids = {tr["translation_id"] for tr in self.trans_results.find({})}
        max_id = max(ids, default=0) + 1
        for i, tr in enumerate(translations):
            tr.translation_id = max_id + i
        self.trans_results.insert_many([tr.model_dump() for tr in translations])

    def get_label(self, label_id: int) -> Optional[TransLabel]:
        obj = self.trans_labels.find_one({"label_id": label_id})
        if obj:
            label = TransLabel.model_construct(**obj)
            return label

    def create_label(self, user_id: int, trans_result: TransResult) -> TransLabel:
        label = TransLabel(
            project_id=trans_result.project_id,
            task_id=trans_result.task_id,
            input_id=trans_result.input_id,
            translation_id=trans_result.translation_id,
            label_id=NO_ID,
            user_id=user_id,
            submitted_date=int(time.time()),
        )
        return label

    def save_label(self, label: TransLabel):
        if label.label_id == NO_ID:
            ids = {t["label_id"] for t in self.trans_labels.find({})}
            label.label_id = max(ids, default=0) + 1
            self.trans_labels.insert_one(label.model_dump())
        else:
            self.trans_labels.update_one(
                filter={"label_id": label.label_id},
                update={"$set": label.model_dump()},
                upsert=True,
            )

    def get_translations_ids_scored_by_user(self, user_id: int, task_id: int) -> Set[int]:
        found = self.trans_labels.find({"user_id": user_id, "task_id": task_id})
        return {item["translation_id"] for item in found}
