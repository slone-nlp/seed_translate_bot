import logging
import random
import time
from typing import Dict, List, Optional

import mongomock
import telebot
from pydantic import BaseModel
from pymongo import MongoClient
from pymongo.collection import Collection

logger = logging.getLogger(__name__)

NO_ID = -1


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
    # TODO: reconsider these options; they look too expensive.
    overlap: int = 3
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
    candidate: Optional[str] = None
    meta: Optional[Dict] = None


class TransResult(BaseModel):
    project_id: int
    task_id: int
    input_id: int
    user_id: int
    submission_id: int
    submitted_date: int
    old_translation: Optional[str] = None
    old_translation_coherence: Optional[int] = None
    old_translation_score: Optional[int] = None
    new_translation: Optional[str] = None


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
        # TODO: in the future, filter by the current project and its languages
        unfinished_task_ids = {
            (task["task_id"], task["completions"])
            for task in self.trans_tasks.find({"completed": False, "locked": False})
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

    def get_task(self, task_id: int) -> Optional[TransTask]:
        obj = self.trans_tasks.find_one({"task_id": task_id})
        if obj:
            task = TransTask.model_construct(**obj)
            return task

    def get_next_input(
        self, task: TransTask, prev_sent_id: Optional[int]
    ) -> Optional[TransInput]:
        if prev_sent_id is None:
            prev_sent_id = -1
        all_inputs = [
            TransInput.model_construct(**obj)
            for obj in self.trans_inputs.find({"task_id": task.task_id})
        ]
        # TODO: maybe, consider only the inputs which don't have perfect translations yet.
        prev_inputs = sorted(
            [inp for inp in all_inputs if inp.input_id > prev_sent_id],
            key=lambda x: x.input_id,
        )
        if prev_inputs:
            return prev_inputs[0]

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
        candidate: Optional[str] = None,
        save: bool = False,
    ):
        inp = TransInput(
            project_id=project.project_id,
            task_id=task.task_id,
            input_id=NO_ID,
            source=source,
            candidate=candidate,
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

    def get_result(self, result_id: int) -> Optional[TransResult]:
        obj = self.trans_results.find_one({"submission_id": result_id})
        if obj:
            res = TransResult.model_construct(**obj)
            return res

    def create_result(self, user: UserState, trans_input: TransInput) -> TransResult:
        result = TransResult(
            project_id=trans_input.project_id,
            task_id=trans_input.task_id,
            input_id=trans_input.input_id,
            user_id=user.user_id,
            submission_id=NO_ID,
            submitted_date=int(time.time()),
        )
        return result

    def save_result(self, result: TransResult) -> None:
        if result.submission_id == NO_ID:
            ids = {t["submission_id"] for t in self.trans_results.find({})}
            result.submission_id = max(ids, default=0) + 1
            self.trans_results.insert_one(result.model_dump())
        else:
            self.trans_results.update_one(
                filter={"submission_id": result.submission_id},
                update={"$set": result.model_dump()},
                upsert=True,
            )
